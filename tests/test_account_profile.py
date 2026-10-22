from __future__ import annotations

import re
import smtplib
from urllib.parse import parse_qs, urlsplit

from utils import account_store


def _prepare_account(monkeypatch, tmp_path, email: str = "owner@example.com") -> None:
    monkeypatch.setattr(account_store, "RUNTIME_DIR", tmp_path / "runtime")
    monkeypatch.setattr(account_store, "OPERATIONAL_DB_PATH", tmp_path / "account.db")
    monkeypatch.setattr(account_store, "LOGO_DIR", tmp_path / "logos")
    monkeypatch.setattr(
        account_store,
        "_configured_auth",
        lambda: {"username": "owner", "password": "ConfiguredPass1", "email": "configured@example.com"},
    )
    with account_store._connect() as conn:
        conn.execute(
            """
            INSERT INTO app_users (username, password_hash, email, password_changed_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("owner", "unchanged-password-hash", email, "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )


def test_profile_save_updates_business_and_username_without_changing_password(monkeypatch, tmp_path):
    _prepare_account(monkeypatch, tmp_path)

    result = account_store.save_account_profile(
        current_username="owner",
        username="shop_admin",
        email="owner@example.com",
        business_name="New Shop Name",
        logo_content=b"new logo bytes",
        logo_extension="png",
    )

    assert result.success
    assert result.saved_fields == ("Username", "Business Name", "Business Logo")
    assert account_store.get_account_profile("shop_admin").username == "shop_admin"
    assert account_store.get_business_name() == "New Shop Name"
    assert account_store.get_logo_path().read_bytes() == b"new logo bytes"
    with account_store._connect() as conn:
        row = conn.execute("SELECT password_hash FROM app_users WHERE username = ?", ("shop_admin",)).fetchone()
    assert row["password_hash"] == "unchanged-password-hash"


def test_profile_save_updates_full_name_without_changing_username(monkeypatch, tmp_path):
    _prepare_account(monkeypatch, tmp_path)

    result = account_store.save_account_profile(
        current_username="owner",
        username="owner",
        email="owner@example.com",
        business_name="TheEverythingShopPH",
        full_name="Juliana Alejo",
    )

    assert result.success
    assert result.saved_fields == ("Full Name",)
    assert result.username == "owner"
    profile = account_store.get_account_profile("owner")
    assert profile is not None
    assert profile.username == "owner"
    assert profile.full_name == "Juliana Alejo"


def test_password_change_records_character_count_for_profile_mask(monkeypatch, tmp_path):
    _prepare_account(monkeypatch, tmp_path)
    with account_store._connect() as conn:
        conn.execute(
            "UPDATE app_users SET password_hash = ? WHERE username = ?",
            (account_store._hash_password("OldPassword1"), "owner"),
        )

    success, _ = account_store.change_password("owner", "OldPassword1", "NewPassword123")

    assert success
    assert account_store.get_account_profile("owner").password_length == len("NewPassword123")


def test_email_is_pending_until_verified_and_configured_email_does_not_overwrite_it(monkeypatch, tmp_path):
    _prepare_account(monkeypatch, tmp_path)
    monkeypatch.setattr(account_store, "password_reset_email_configured", lambda: True)
    monkeypatch.setattr(
        account_store,
        "_email_config",
        lambda: {
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_username": "smtp-user",
            "smtp_password": "smtp-password",
            "from_email": "noreply@example.com",
            "app_base_url": "https://example.com",
        },
    )

    class FakeSMTP:
        sent_messages = []

        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self):
            pass

        def login(self, *_args):
            pass

        def send_message(self, message):
            self.sent_messages.append(message)

    monkeypatch.setattr(account_store.smtplib, "SMTP", FakeSMTP)
    result = account_store.save_account_profile(
        current_username="owner",
        username="new_owner",
        email="verified@example.com",
        business_name="TheEverythingShopPH",
    )

    assert result.success
    assert result.pending_email == "verified@example.com"
    assert account_store.get_account_profile("new_owner").email == "owner@example.com"
    assert account_store.get_account_profile("owner") is None
    message = FakeSMTP.sent_messages[-1]
    verification_url = re.search(r"https://\S+", message.get_content()).group(0)
    token = parse_qs(urlsplit(verification_url).query)["verify_email_token"][0]

    verified, message_text = account_store.verify_account_email(token)

    assert verified
    assert "verified" in message_text.lower()
    assert account_store.get_account_profile("new_owner").email == "verified@example.com"
    assert account_store.verify_account_email(token)[0] is False


def test_email_delivery_failure_rolls_back_all_profile_changes(monkeypatch, tmp_path):
    _prepare_account(monkeypatch, tmp_path)
    monkeypatch.setattr(account_store, "password_reset_email_configured", lambda: True)
    monkeypatch.setattr(
        account_store,
        "_email_config",
        lambda: {
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_username": "smtp-user",
            "smtp_password": "smtp-password",
            "from_email": "noreply@example.com",
            "app_base_url": "https://example.com",
        },
    )

    class FailingSMTP:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def starttls(self):
            raise smtplib.SMTPException("delivery failed")

    monkeypatch.setattr(account_store.smtplib, "SMTP", FailingSMTP)
    result = account_store.save_account_profile(
        current_username="owner",
        username="new_owner",
        email="new@example.com",
        business_name="Unsaved Name",
        logo_content=b"image",
        logo_extension="png",
    )

    assert not result.success
    assert account_store.get_account_profile("owner").email == "owner@example.com"
    assert account_store.get_business_name() == account_store.DEFAULT_BUSINESS_NAME
    with account_store._connect() as conn:
        assert conn.execute("SELECT 1 FROM app_users WHERE username = ?", ("new_owner",)).fetchone() is None
        assert conn.execute("SELECT 1 FROM app_settings WHERE key = 'business_logo_path'").fetchone() is None
        assert conn.execute("SELECT 1 FROM account_email_verification_tokens").fetchone() is None
    assert list((tmp_path / "logos").glob("*")) == []


def test_invalid_profile_fields_do_not_change_saved_values(monkeypatch, tmp_path):
    _prepare_account(monkeypatch, tmp_path)

    result = account_store.save_account_profile(
        current_username="owner",
        username="invalid name",
        email="not-an-email",
        business_name="",
    )

    assert not result.success
    assert account_store.get_account_profile("owner").email == "owner@example.com"
    assert account_store.get_business_name() == account_store.DEFAULT_BUSINESS_NAME
