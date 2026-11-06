"""Operational account, branding, and recovery storage for the TESPH DSS."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import logging
import os
import re
import secrets
import smtplib
import struct
import time
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import quote

import streamlit as st


RUNTIME_DIR = Path("runtime_data")
OPERATIONAL_DB_PATH = RUNTIME_DIR / "app_account.db"
BRANDING_DIR = RUNTIME_DIR / "branding"
LOGO_DIR = BRANDING_DIR / "logos"
DEFAULT_BUSINESS_NAME = "TheEverythingShopPH"
DEFAULT_LOGO_PATH = Path("assets/theeverythingshopph-logo.png")
PASSWORD_ITERATIONS = 260_000
TOTP_INTERVAL_SECONDS = 30
TOTP_DIGITS = 6
PROFILE_EMAIL_TOKEN_MINUTES = 30
USERNAME_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{3,64}$")
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class AccountProfile:
    username: str
    full_name: str
    email: str
    password_length: int | None


@dataclass(frozen=True)
class ProfileUpdateResult:
    success: bool
    message: str
    username: str
    saved_fields: tuple[str, ...] = ()
    pending_email: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _connect() -> sqlite3.Connection:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(OPERATIONAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    _ensure_tables(conn)
    return conn


def _ensure_tables(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            password_length INTEGER,
            email TEXT,
            password_changed_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    user_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(app_users)").fetchall()
    }
    if "password_length" not in user_columns:
        conn.execute("ALTER TABLE app_users ADD COLUMN password_length INTEGER")
    if "totp_secret" not in user_columns:
        conn.execute("ALTER TABLE app_users ADD COLUMN totp_secret TEXT")
    if "totp_enabled" not in user_columns:
        conn.execute("ALTER TABLE app_users ADD COLUMN totp_enabled INTEGER NOT NULL DEFAULT 0")
    if "full_name" not in user_columns:
        conn.execute("ALTER TABLE app_users ADD COLUMN full_name TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            event_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS account_email_verification_tokens (
            token_hash TEXT PRIMARY KEY,
            username TEXT NOT NULL,
            pending_email TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _configured_auth() -> dict[str, str]:
    try:
        auth_config = st.secrets.get("auth", {})
    except (FileNotFoundError, KeyError, OSError):
        auth_config = {}
    result: dict[str, str] = {}
    for key in ("username", "password", "email", "full_name"):
        value = auth_config.get(key) if hasattr(auth_config, "get") else None
        if isinstance(value, str) and value.strip():
            result[key] = value.strip()
    result.setdefault("username", os.getenv("TESPH_AUTH_USERNAME", "").strip())
    result.setdefault("password", os.getenv("TESPH_AUTH_PASSWORD", "").strip())
    result.setdefault("email", os.getenv("TESPH_AUTH_EMAIL", "").strip())
    return {key: value for key, value in result.items() if value}


def _hash_password(password: str, *, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return "pbkdf2_sha256${}${}${}".format(
        PASSWORD_ITERATIONS,
        base64.b64encode(salt).decode("ascii"),
        base64.b64encode(digest).decode("ascii"),
    )


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, int(iterations))
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, OSError):
        return False


def _bootstrap_user(conn: sqlite3.Connection) -> None:
    configured = _configured_auth()
    username = configured.get("username")
    password = configured.get("password")
    if not username or not password:
        return
    existing = conn.execute(
        "SELECT email, full_name FROM app_users WHERE username = ?",
        (username,),
    ).fetchone()
    configured_email = configured.get("email")
    if existing:
        configured_full_name = configured.get("full_name")
        updates: list[str] = []
        values: list[str] = []
        if configured_email and not existing["email"]:
            updates.append("email = ?")
            values.append(configured_email)
        if configured_full_name and not existing["full_name"]:
            updates.append("full_name = ?")
            values.append(configured_full_name)
        if updates:
            now = _utc_now().isoformat()
            values.extend([now, username])
            conn.execute(
                f"UPDATE app_users SET {', '.join(updates)}, updated_at = ? WHERE username = ?",
                tuple(values),
            )
            conn.commit()
        return
    if conn.execute("SELECT 1 FROM app_users LIMIT 1").fetchone():
        return
    now = _utc_now().isoformat()
    conn.execute(
        """
        INSERT INTO app_users (username, password_hash, password_length, email, full_name, password_changed_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (username, _hash_password(password), len(password), configured.get("email"), configured.get("full_name"), now, now),
    )
    conn.commit()


def is_auth_configured() -> bool:
    with _connect() as conn:
        _bootstrap_user(conn)
        row = conn.execute("SELECT 1 FROM app_users LIMIT 1").fetchone()
        return row is not None


def authenticate_user(username: str, password: str) -> bool:
    with _connect() as conn:
        _bootstrap_user(conn)
        row = conn.execute(
            "SELECT username, password_hash FROM app_users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None or not _verify_password(password, row["password_hash"]):
            conn.execute(
                "INSERT INTO auth_events (username, event_type, created_at) VALUES (?, ?, ?)",
                (username, "login_failed", _utc_now().isoformat()),
            )
            conn.commit()
            return False
        conn.execute(
            "INSERT INTO auth_events (username, event_type, created_at) VALUES (?, ?, ?)",
            (username, "login_success", _utc_now().isoformat()),
        )
        conn.commit()
        return True


def _normalize_totp_secret(secret: str) -> str:
    return "".join(str(secret).strip().upper().split())


def generate_totp_secret() -> str:
    """Create a Google Authenticator-compatible base32 TOTP secret."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def get_totp_setup_uri(username: str, secret: str, issuer: str = DEFAULT_BUSINESS_NAME) -> str:
    """Return an otpauth URI that authenticator apps can import."""
    label = f"{issuer}:{username}"
    return (
        "otpauth://totp/"
        f"{quote(label)}?secret={quote(_normalize_totp_secret(secret))}"
        f"&issuer={quote(issuer)}&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_INTERVAL_SECONDS}"
    )


def _totp_code(secret: str, counter: int) -> str:
    normalized = _normalize_totp_secret(secret)
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(normalized + padding, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    token = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(token % (10**TOTP_DIGITS)).zfill(TOTP_DIGITS)


def verify_totp_code(secret: str, code: str, *, valid_window: int = 1) -> bool:
    """Validate a 6-digit authenticator code with minor clock drift tolerance."""
    cleaned = "".join(character for character in str(code).strip() if character.isdigit())
    if len(cleaned) != TOTP_DIGITS:
        return False
    try:
        counter = int(time.time() // TOTP_INTERVAL_SECONDS)
        for offset in range(-valid_window, valid_window + 1):
            if hmac.compare_digest(_totp_code(secret, counter + offset), cleaned):
                return True
    except (binascii.Error, ValueError):
        return False
    return False


def is_two_factor_enabled(username: str) -> bool:
    with _connect() as conn:
        _bootstrap_user(conn)
        row = conn.execute(
            "SELECT totp_enabled FROM app_users WHERE username = ?",
            (username,),
        ).fetchone()
    return bool(row and row["totp_enabled"])


def enable_two_factor(username: str, secret: str, code: str) -> tuple[bool, str]:
    """Enable TOTP 2FA after verifying the first code from the authenticator app."""
    normalized = _normalize_totp_secret(secret)
    if not normalized:
        return False, "Two-factor setup could not be started. Try again."
    if not verify_totp_code(normalized, code):
        return False, "The verification code is invalid. Check Google Authenticator and try again."
    now = _utc_now().isoformat()
    with _connect() as conn:
        _bootstrap_user(conn)
        updated = conn.execute(
            "UPDATE app_users SET totp_secret = ?, totp_enabled = 1, updated_at = ? WHERE username = ?",
            (normalized, now, username),
        )
        if updated.rowcount != 1:
            return False, "The signed-in account could not be found."
        conn.execute(
            "INSERT INTO auth_events (username, event_type, created_at) VALUES (?, ?, ?)",
            (username, "two_factor_enabled", now),
        )
        conn.commit()
    return True, "Two-factor authentication is enabled."


def disable_two_factor(username: str) -> tuple[bool, str]:
    now = _utc_now().isoformat()
    with _connect() as conn:
        _bootstrap_user(conn)
        updated = conn.execute(
            "UPDATE app_users SET totp_secret = NULL, totp_enabled = 0, updated_at = ? WHERE username = ?",
            (now, username),
        )
        if updated.rowcount != 1:
            return False, "The signed-in account could not be found."
        conn.execute(
            "INSERT INTO auth_events (username, event_type, created_at) VALUES (?, ?, ?)",
            (username, "two_factor_disabled", now),
        )
        conn.commit()
    return True, "Two-factor authentication is disabled."


def verify_user_two_factor(username: str, code: str) -> bool:
    with _connect() as conn:
        _bootstrap_user(conn)
        row = conn.execute(
            "SELECT totp_secret, totp_enabled FROM app_users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None or not row["totp_enabled"] or not row["totp_secret"]:
            return False
        ok = verify_totp_code(str(row["totp_secret"]), code)
        conn.execute(
            "INSERT INTO auth_events (username, event_type, created_at) VALUES (?, ?, ?)",
            (username, "two_factor_success" if ok else "two_factor_failed", _utc_now().isoformat()),
        )
        conn.commit()
        return ok


def password_meets_requirements(password: str) -> tuple[bool, str]:
    if len(password) < 8:
        return False, "New password must be at least 8 characters long."
    if not any(char.isupper() for char in password):
        return False, "New password must include at least one uppercase letter."
    if not any(char.islower() for char in password):
        return False, "New password must include at least one lowercase letter."
    if not any(char.isdigit() for char in password):
        return False, "New password must include at least one number."
    return True, ""


def change_password(username: str, current_password: str, new_password: str) -> tuple[bool, str]:
    with _connect() as conn:
        _bootstrap_user(conn)
        row = conn.execute(
            "SELECT password_hash FROM app_users WHERE username = ?",
            (username,),
        ).fetchone()
        if row is None or not _verify_password(current_password, row["password_hash"]):
            return False, "Current password is incorrect."
        valid, message = password_meets_requirements(new_password)
        if not valid:
            return False, message
        now = _utc_now().isoformat()
        conn.execute(
            "UPDATE app_users SET password_hash = ?, password_length = ?, password_changed_at = ?, updated_at = ? WHERE username = ?",
            (_hash_password(new_password), len(new_password), now, now, username),
        )
        conn.execute(
            "INSERT INTO auth_events (username, event_type, created_at) VALUES (?, ?, ?)",
            (username, "password_changed", now),
        )
        conn.commit()
    return True, "Password updated. Please sign in again."


def get_business_name() -> str:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = 'business_name'").fetchone()
    return row["value"] if row else DEFAULT_BUSINESS_NAME


def set_business_name(name: str) -> tuple[bool, str]:
    cleaned = " ".join(name.strip().split())
    if not cleaned:
        return False, "Business name cannot be empty."
    now = _utc_now().isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at) VALUES ('business_name', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (cleaned, now),
        )
        conn.commit()
    return True, "Business name saved."


def get_logo_path() -> Path:
    with _connect() as conn:
        row = conn.execute("SELECT value FROM app_settings WHERE key = 'business_logo_path'").fetchone()
    if row:
        path = Path(row["value"])
        if path.exists() and path.is_file():
            return path
    return DEFAULT_LOGO_PATH


def save_logo_file(content: bytes, extension: str) -> Path:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    safe_extension = extension.lower().lstrip(".")
    filename = f"business_logo.{safe_extension}"
    path = LOGO_DIR / filename
    path.write_bytes(content)
    now = _utc_now().isoformat()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at) VALUES ('business_logo_path', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (str(path), now),
        )
        conn.commit()
    return path


def get_account_profile(username: str) -> AccountProfile | None:
    with _connect() as conn:
        _bootstrap_user(conn)
        row = conn.execute(
            "SELECT username, full_name, email, password_length FROM app_users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None:
        return None
    return AccountProfile(
        username=row["username"],
        full_name=row["full_name"] or row["username"],
        email=row["email"] or "",
        password_length=row["password_length"],
    )


def get_pending_account_email(username: str) -> str | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT pending_email, expires_at
            FROM account_email_verification_tokens
            WHERE username = ? AND used_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (username,),
        ).fetchone()
    if row is None or datetime.fromisoformat(row["expires_at"]) <= _utc_now():
        return None
    return str(row["pending_email"])


class _ProfileEmailDeliveryError(Exception):
    """Raised when profile email verification cannot be delivered."""


def save_account_profile(
    current_username: str,
    username: str,
    email: str,
    business_name: str,
    full_name: str | None = None,
    logo_content: bytes | None = None,
    logo_extension: str | None = None,
) -> ProfileUpdateResult:
    cleaned_username = username.strip()
    cleaned_full_name = " ".join(full_name.strip().split()) if full_name is not None else None
    cleaned_email = email.strip()
    cleaned_business_name = " ".join(business_name.strip().split())

    if cleaned_full_name is not None and not cleaned_full_name:
        return ProfileUpdateResult(False, "Full Name cannot be empty.", current_username)
    if cleaned_full_name is not None and len(cleaned_full_name) > 80:
        return ProfileUpdateResult(False, "Full Name must be 80 characters or fewer.", current_username)
    if not cleaned_username:
        return ProfileUpdateResult(False, "Username cannot be empty.", current_username)
    if cleaned_username != current_username and USERNAME_PATTERN.fullmatch(cleaned_username) is None:
        return ProfileUpdateResult(
            False,
            "Username must be 3–64 characters and use only letters, numbers, periods, underscores, or hyphens.",
            current_username,
        )
    if not cleaned_business_name:
        return ProfileUpdateResult(False, "Business name cannot be empty.", current_username)
    if cleaned_email and EMAIL_PATTERN.fullmatch(cleaned_email) is None:
        return ProfileUpdateResult(False, "Enter a valid email address.", current_username)
    if logo_content is not None:
        if logo_extension is None or logo_extension.lower().lstrip(".") not in {"png", "jpg", "jpeg"}:
            return ProfileUpdateResult(False, "Logo must be a PNG, JPG, or JPEG image.", current_username)
    elif logo_extension is not None:
        return ProfileUpdateResult(False, "A logo file is required for the selected image type.", current_username)

    email_config = _email_config()
    if not is_email_delivery_configured() and cleaned_email:
        with _connect() as conn:
            _bootstrap_user(conn)
            existing = conn.execute(
                "SELECT email FROM app_users WHERE username = ?",
                (current_username,),
            ).fetchone()
        if existing is not None and cleaned_email.casefold() != str(existing["email"] or "").casefold():
            return ProfileUpdateResult(
                False,
                "Email changes require configured email delivery so the new address can be verified.",
                current_username,
            )

    staged_logo: Path | None = None
    new_logo_path: Path | None = None
    previous_logo_path: Path | None = None
    if logo_content is not None and logo_extension is not None:
        try:
            LOGO_DIR.mkdir(parents=True, exist_ok=True)
            extension = logo_extension.lower().lstrip(".")
            new_logo_path = LOGO_DIR / f"business_logo_{secrets.token_hex(8)}.{extension}"
            staged_logo = LOGO_DIR / f".{new_logo_path.name}.tmp"
            staged_logo.write_bytes(logo_content)
        except OSError:
            LOGGER.warning("Could not stage a replacement business logo.", exc_info=True)
            if staged_logo is not None and staged_logo.exists():
                try:
                    staged_logo.unlink()
                except OSError:
                    LOGGER.warning("Could not remove a partial logo upload at %s.", staged_logo, exc_info=True)
            return ProfileUpdateResult(
                False,
                "The logo could not be prepared. No profile changes were saved.",
                current_username,
            )

    conn: sqlite3.Connection | None = None
    committed = False
    try:
        conn = _connect()
        with conn:
            _bootstrap_user(conn)
            account = conn.execute(
                "SELECT username, full_name, email FROM app_users WHERE username = ?",
                (current_username,),
            ).fetchone()
            if account is None:
                return ProfileUpdateResult(False, "The signed-in account could not be found.", current_username)

            username_changed = cleaned_username != current_username
            full_name_changed = (
                cleaned_full_name is not None
                and cleaned_full_name != str(account["full_name"] or account["username"])
            )
            email_changed = cleaned_email.casefold() != str(account["email"] or "").casefold()
            business_row = conn.execute(
                "SELECT value FROM app_settings WHERE key = 'business_name'",
            ).fetchone()
            stored_business_name = business_row["value"] if business_row else DEFAULT_BUSINESS_NAME
            business_name_changed = cleaned_business_name != stored_business_name
            logo_setting = conn.execute(
                "SELECT value FROM app_settings WHERE key = 'business_logo_path'",
            ).fetchone()
            if logo_setting:
                previous_logo_path = Path(logo_setting["value"])

            if username_changed:
                duplicate_username = conn.execute(
                    "SELECT 1 FROM app_users WHERE lower(username) = lower(?) AND username != ?",
                    (cleaned_username, current_username),
                ).fetchone()
                if duplicate_username:
                    return ProfileUpdateResult(False, "That username is already in use.", current_username)

            if email_changed:
                if not cleaned_email:
                    return ProfileUpdateResult(False, "Email address cannot be empty.", current_username)
                duplicate_email = conn.execute(
                    "SELECT 1 FROM app_users WHERE lower(email) = lower(?) AND username != ?",
                    (cleaned_email, current_username),
                ).fetchone()
                if duplicate_email:
                    return ProfileUpdateResult(False, "That email address is already associated with an account.", current_username)
                if not is_email_delivery_configured():
                    return ProfileUpdateResult(
                        False,
                        "Email changes require configured email delivery so the new address can be verified.",
                        current_username,
                    )

            logo_changed = logo_content is not None
            if not (username_changed or full_name_changed or business_name_changed or logo_changed or email_changed):
                return ProfileUpdateResult(True, "There are no profile changes to save.", current_username)

            now = _utc_now()
            now_text = now.isoformat()
            pending_email: str | None = None
            if username_changed:
                conn.execute(
                    "UPDATE app_users SET username = ?, updated_at = ? WHERE username = ?",
                    (cleaned_username, now_text, current_username),
                )
                conn.execute(
                    "UPDATE account_email_verification_tokens SET used_at = ? "
                    "WHERE username = ? AND used_at IS NULL",
                    (now_text, current_username),
                )

            if full_name_changed and cleaned_full_name is not None:
                conn.execute(
                    "UPDATE app_users SET full_name = ?, updated_at = ? WHERE username = ?",
                    (cleaned_full_name, now_text, cleaned_username),
                )

            if business_name_changed:
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at) VALUES ('business_name', ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (cleaned_business_name, now_text),
                )

            saved_fields: list[str] = []
            if username_changed:
                saved_fields.append("Username")
            if full_name_changed:
                saved_fields.append("Full Name")
            if business_name_changed:
                saved_fields.append("Business Name")

            if logo_changed and new_logo_path is not None and staged_logo is not None:
                conn.execute(
                    """
                    INSERT INTO app_settings (key, value, updated_at) VALUES ('business_logo_path', ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (str(new_logo_path), now_text),
                )
                os.replace(staged_logo, new_logo_path)
                saved_fields.append("Business Logo")

            if email_changed:
                raw_token = secrets.token_urlsafe(32)
                token_hash = _hash_token(raw_token)
                expires_at = now + timedelta(minutes=PROFILE_EMAIL_TOKEN_MINUTES)
                conn.execute(
                    "UPDATE account_email_verification_tokens SET used_at = ? "
                    "WHERE username = ? AND used_at IS NULL",
                    (now_text, cleaned_username),
                )
                conn.execute(
                    """
                    INSERT INTO account_email_verification_tokens
                        (token_hash, username, pending_email, expires_at, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (token_hash, cleaned_username, cleaned_email, expires_at.isoformat(), now_text),
                )
                verification_url = (
                    f"{email_config['app_base_url'].rstrip('/')}"
                    f"{'&' if '?' in email_config['app_base_url'] else '?'}"
                    f"verify_email_token={quote(raw_token)}"
                )
                message = EmailMessage()
                message["Subject"] = "Verify your TESPH DSS account email"
                message["From"] = email_config["from_email"]
                message["To"] = cleaned_email
                message.set_content(
                    "A request was made to use this address for TheEverythingShopPH DSS account recovery.\n\n"
                    f"Verify this address within {PROFILE_EMAIL_TOKEN_MINUTES} minutes:\n{verification_url}\n\n"
                    "If you did not request this change, you can ignore this message."
                )
                try:
                    with smtplib.SMTP(
                        email_config["smtp_host"],
                        int(email_config["smtp_port"]),
                        timeout=15,
                    ) as smtp:
                        smtp.starttls()
                        smtp.login(email_config["smtp_username"], email_config["smtp_password"])
                        smtp.send_message(message)
                except (OSError, smtplib.SMTPException, ValueError) as exc:
                    LOGGER.warning("Could not send account email verification.", exc_info=True)
                    raise _ProfileEmailDeliveryError(
                        "The verification email could not be sent. No profile changes were saved."
                    ) from exc
                pending_email = cleaned_email

            if saved_fields or pending_email:
                conn.execute(
                    "INSERT INTO auth_events (username, event_type, created_at) VALUES (?, ?, ?)",
                    (cleaned_username, "profile_updated", now_text),
                )

        committed = True
    except _ProfileEmailDeliveryError as exc:
        return ProfileUpdateResult(False, str(exc), current_username)
    except (sqlite3.Error, OSError):
        LOGGER.warning("Could not save the account profile.", exc_info=True)
        return ProfileUpdateResult(
            False,
            "Profile changes could not be saved; the previous values were kept.",
            current_username,
        )
    finally:
        if conn is not None:
            conn.close()
        if not committed:
            if staged_logo is not None and staged_logo.exists():
                staged_logo.unlink()
            if new_logo_path is not None and new_logo_path.exists():
                new_logo_path.unlink()

    if previous_logo_path is not None and previous_logo_path.parent == LOGO_DIR and previous_logo_path != new_logo_path:
        try:
            previous_logo_path.unlink(missing_ok=True)
        except OSError:
            LOGGER.warning("Could not remove the previous business logo at %s.", previous_logo_path, exc_info=True)

    if pending_email:
        if saved_fields:
            message = (
                f"Saved {', '.join(saved_fields)}. A verification link was sent to {pending_email}; "
                "the recovery email will not change until it is verified."
            )
        else:
            message = (
                f"No profile fields were saved yet. A verification link was sent to {pending_email}; "
                "the recovery email will not change until it is verified."
            )
    elif saved_fields:
        message = f"Saved {', '.join(saved_fields)}."
    else:
        message = "There are no profile changes to save."
    return ProfileUpdateResult(
        True,
        message,
        cleaned_username,
        tuple(saved_fields),
        pending_email,
    )


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _email_config() -> dict[str, str]:
    try:
        config = st.secrets.get("email", {})
    except (FileNotFoundError, KeyError, OSError):
        config = {}
    values = {
        "smtp_host": os.getenv("TESPH_SMTP_HOST", ""),
        "smtp_port": os.getenv("TESPH_SMTP_PORT", ""),
        "smtp_username": os.getenv("TESPH_SMTP_USERNAME", ""),
        "smtp_password": os.getenv("TESPH_SMTP_PASSWORD", ""),
        "from_email": os.getenv("TESPH_FROM_EMAIL", ""),
        "app_base_url": os.getenv("TESPH_APP_BASE_URL", ""),
    }
    for key in values:
        value = config.get(key) if hasattr(config, "get") else None
        if isinstance(value, str) and value.strip():
            values[key] = value.strip()
    return values


def is_email_delivery_configured() -> bool:
    config = _email_config()
    required = ("smtp_host", "smtp_port", "smtp_username", "smtp_password", "from_email", "app_base_url")
    return all(config.get(key) for key in required)


password_reset_email_configured = is_email_delivery_configured


def verify_account_email(token: str) -> tuple[bool, str]:
    now = _utc_now()
    token_hash = _hash_token(token)
    with _connect() as conn:
        with conn:
            row = conn.execute(
                """
                SELECT username, pending_email, expires_at, used_at
                FROM account_email_verification_tokens
                WHERE token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None or row["used_at"] is not None:
                return False, "This email verification link is invalid or has already been used."

            if datetime.fromisoformat(row["expires_at"]) <= now:
                conn.execute(
                    "UPDATE account_email_verification_tokens SET used_at = ? WHERE token_hash = ?",
                    (now.isoformat(), token_hash),
                )
                return False, "This email verification link has expired. Submit the email address again to get a new link."

            duplicate = conn.execute(
                "SELECT 1 FROM app_users WHERE lower(email) = lower(?) AND username != ?",
                (row["pending_email"], row["username"]),
            ).fetchone()
            if duplicate:
                conn.execute(
                    "UPDATE account_email_verification_tokens SET used_at = ? WHERE token_hash = ?",
                    (now.isoformat(), token_hash),
                )
                return False, "This email address is already associated with another account."

            updated = conn.execute(
                "UPDATE app_users SET email = ?, updated_at = ? WHERE username = ?",
                (row["pending_email"], now.isoformat(), row["username"]),
            )
            if updated.rowcount != 1:
                conn.execute(
                    "UPDATE account_email_verification_tokens SET used_at = ? WHERE token_hash = ?",
                    (now.isoformat(), token_hash),
                )
                return False, "The account for this email verification link could not be found."

            conn.execute(
                "UPDATE account_email_verification_tokens SET used_at = ? "
                "WHERE username = ? AND used_at IS NULL",
                (now.isoformat(), row["username"]),
            )
            conn.execute(
                "INSERT INTO auth_events (username, event_type, created_at) VALUES (?, ?, ?)",
                (row["username"], "email_verified", now.isoformat()),
            )
    return True, "Email address verified and saved."

