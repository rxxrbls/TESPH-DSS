"""Real headless Edge acceptance check of app.py with an isolated runtime DB.

The temporary entry point configures only test credentials/runtime paths. All
pages, login checks, ETL, analytics and forecasts run the production code.
"""
from pathlib import Path
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".artifacts/qa/browser"
OUTPUT = ROOT / "validation_outputs/integration_qa/browser"


def main():
    global WORK, OUTPUT
    three = "--three" in sys.argv
    if three:
        from uuid import uuid4
        WORK = ROOT / ".artifacts/qa/browser_three" / uuid4().hex
        OUTPUT = ROOT / "validation_outputs/three_criterion_mca/browser"
    from playwright.sync_api import sync_playwright, expect
    expect.set_options(timeout=180000)
    expected_mca_path = ROOT / "validation_outputs/five_criterion_mca/uploaded_stock_mca_audit.csv"
    if not expected_mca_path.is_file():
        raise RuntimeError("Run validate_approved_mca.py and qa/check_uploaded_mca.py before browser QA")
    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / ".artifacts/qa/full_seed.db", WORK / "runtime.db")
    entry = ROOT / ".qa_browser_entry.py"
    if entry.exists():
        raise RuntimeError("Temporary browser entry already exists; inspect it before retrying")
    entry.write_text('''from pathlib import Path
import os
import runpy
import etl_config
etl_config.RUNTIME_DB_PATH = Path(os.environ["TESPH_QA_DATABASE"])
etl_config.RUNTIME_DATA_DIR = etl_config.RUNTIME_DB_PATH.parent
import utils.auth
utils.auth._configured_credentials = lambda: (os.environ["TESPH_QA_USERNAME"], os.environ["TESPH_QA_PASSWORD"])
runpy.run_path(str(Path(__file__).parent / "app.py"), run_name="__main__")
''', encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, TESPH_QA_DATABASE=str(WORK / "runtime.db"), TESPH_QA_USERNAME="qa-local",
               TESPH_QA_PASSWORD=secrets.token_urlsafe(24), PYTHONIOENCODING="utf-8")
    checks, errors = [], []
    completed = False
    def record(name):
        checks.append(name)
        print("PASS " + name, flush=True)
    with (WORK / "server.log").open("w", encoding="utf-8") as log:
        server = subprocess.Popen([sys.executable, "-m", "streamlit", "run", str(entry),
                                   "--server.address=127.0.0.1", f"--server.port={port}",
                                   "--server.headless=true", "--server.fileWatcherType=none", "--browser.gatherUsageStats=false"],
                                  cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(60):
                try:
                    urllib.request.urlopen(url + "/_stcore/health", timeout=1)
                    break
                except OSError:
                    if server.poll() is not None:
                        raise RuntimeError("QA Streamlit server failed; see isolated server.log")
                    time.sleep(.5)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel="msedge", headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 1000})
                page.set_default_timeout(180000)
                page.on("pageerror", lambda error: errors.append(str(error)))
                def screenshot(name):
                    expect(page.get_by_role("button", name="Stop", exact=True)).not_to_be_visible()
                    assert page.get_by_test_id("stException").count() == 0
                    page.screenshot(path=str(OUTPUT / (name + ".png")), full_page=True)
                def navigate(name):
                    page.get_by_test_id("stSidebar").get_by_text(name, exact=True).click()
                page.goto(url)
                page.get_by_label("Username", exact=True).fill(env["TESPH_QA_USERNAME"])
                page.get_by_label("Password", exact=True).fill("incorrect")
                page.get_by_role("button", name="Sign In", exact=True).click()
                expect(page.get_by_text("Invalid username or password.", exact=True)).to_be_visible()
                record("Invalid login rejected")
                page.get_by_label("Password", exact=True).fill(env["TESPH_QA_PASSWORD"])
                page.get_by_role("button", name="Sign In", exact=True).click()
                page.locator(".kpi-value").first.wait_for()
                screenshot("dashboard")
                record("Login and actual-data dashboard")
                navigate("Demand Forecast")
                expect(page.get_by_text("Forecast Method Accuracy", exact=True)).to_be_visible()
                expect(page.get_by_text("Every actual demand observation", exact=False)).to_be_visible()
                with page.expect_download() as download_info:
                    page.get_by_role("button", name="Download full-precision validation metrics", exact=True).click()
                downloaded = WORK / "frontend_validation_metrics.csv"
                download_info.value.save_as(downloaded)
                import pandas as pd
                actual = pd.read_csv(downloaded, dtype={"SKU": "string"})
                expected_metrics = pd.read_csv(ROOT / "validation_outputs/forecast_accuracy/validation_metrics.csv", dtype={"SKU": "string"})
                pd.testing.assert_frame_equal(actual, expected_metrics, check_exact=False, rtol=1e-10, atol=1e-12)
                record("Browser metric download matches independent actual-data audit")
                screenshot("forecast-accuracy")
                record("Forecast metrics and no-demand explanation visible")
                navigate("Data Upload & ETL")
                upload = page.get_by_test_id("stFileUploader").first.locator("input[type=file]")
                upload.set_input_files({"name": "invalid.csv", "mimeType": "text/csv", "buffer": b"bad_column\ninvalid\n"})
                expect(page.locator(".upload-summary .file-name")).to_have_text("invalid.csv")
                expect(page.get_by_role("button", name="Stop", exact=True)).not_to_be_visible()
                page.get_by_role("button", name="Process dataset", exact=True).click()
                expect(page.get_by_text("Issues found", exact=True)).to_be_visible()
                record("Invalid upload reported without losing active data")
                upload.set_input_files(str(ROOT / "raw_data/2022/Order.all.AUG2022.xlsx"))
                expect(page.locator(".upload-summary .file-name")).to_have_text("Order.all.AUG2022.xlsx")
                expect(page.get_by_role("button", name="Stop", exact=True)).not_to_be_visible()
                page.get_by_role("button", name="Process dataset", exact=True).click()
                expect(page.get_by_text("New rows added", exact=True)).to_be_visible()
                values = page.get_by_test_id("stMetric").filter(has_text="New rows added")
                expect(values.get_by_test_id("stMetricValue")).to_have_text("0")
                record("Real historical XLSX repeat adds zero rows")
                stock_upload = page.get_by_test_id("stFileUploader").nth(1).locator("input[type=file]")
                stock_upload.set_input_files(str(ROOT / "raw_data/current_stock/shopee_current_stock_raw_2026-09-09.xlsx"))
                date_input = page.get_by_label("Stock snapshot as-of date", exact=True)
                expect(date_input).to_be_visible()
                # Current Streamlit uses accessible date segments, whereas
                # older versions exposed a single text input.
                if date_input.get_attribute("role") == "group":
                    for segment, value in (("year", "2026"), ("month", "9"), ("day", "9")):
                        field = date_input.get_by_role("spinbutton", name=re.compile(segment, re.I))
                        field.fill(value)
                        field.press("Tab")
                else:
                    date_input.fill("2026/09/09")
                    date_input.press("Enter")
                page.get_by_text("I confirm this date, including the latest-transaction-date fallback if needed", exact=True).click()
                page.get_by_text("I confirm Stock is net sellable quantity (on-hand minus reserved/allocated)", exact=True).click()
                page.get_by_role("button", name="Validate stock data", exact=True).click()
                expect(page.get_by_text("Current-stock snapshot validated and connected outputs refreshed.", exact=True)).to_be_visible()
                record("Actual stock workbook connects derived outputs")
                for name, expected in [("Stock-Out Risk", "Stock-Out Risk"),
                                       ("Product Prioritization", "MCA readiness"),
                                       ("Replenishment Recommendations", "Replenishment Recommendations")]:
                    navigate(name)
                    expect(page.get_by_text(expected, exact=True).last).to_be_visible()
                    expect(page.locator('[data-testid="stDataFrame"]:visible').first).to_be_visible()
                    if name == "Product Prioritization":
                        expect(page.get_by_text("20%", exact=False)).to_be_visible()
                        with page.expect_download() as mca_download:
                            page.get_by_role("button", name="Download MCA readiness audit", exact=True).click()
                        mca_path = WORK / "frontend_mca_readiness.csv"
                        mca_download.value.save_as(mca_path)
                        MCA_CRITERIA = json.loads((ROOT / "validation_outputs/five_criterion_mca/summary.json").read_text())["criteria"]
                        actual_mca = pd.read_csv(mca_path, dtype={"SKU": "string"})
                        expected_mca = pd.read_csv(ROOT / "validation_outputs/five_criterion_mca/uploaded_stock_mca_audit.csv", dtype={"SKU": "string"})
                        assert "Stock-Out Frequency" not in actual_mca
                        pd.testing.assert_frame_equal(
                            actual_mca.set_index("SKU")[list(MCA_CRITERIA)].sort_index(),
                            expected_mca.set_index("SKU")[list(MCA_CRITERIA)].sort_index(),
                            check_exact=False, rtol=1e-10, atol=1e-12,
                        )
                        record("Five-criterion MCA CSV matches independent actual-data audit")
                    screenshot(name.lower().replace(" ", "-"))
                    record(name + " renders connected data")
                if three:
                    navigate("Data Upload & ETL")
                    page.get_by_text("Return/refund data — three-criterion MCA", exact=True).click()
                    page.get_by_test_id("stFileUploader").nth(2).locator("input[type=file]").set_input_files(
                        str(ROOT.parent / "RETURN_REFUND_HANDOFF-20261016T123959Z-1-001.zip"))
                    page.get_by_text("Coverage is confirmed for the selected request dates, including empty monthly files. Later requests are outside this assessment.", exact=True).click()
                    page.get_by_role("button", name="Validate and refresh three-criterion MCA", exact=True).click()
                    expect(page.get_by_text("Return/refund evidence reviewed. Provisional MCA and connected outputs refreshed.", exact=True)).to_be_visible()
                    record("Actual return/refund ZIP accepted with explicit coverage")
                    page.get_by_role("button", name="Validate and refresh three-criterion MCA", exact=True).click()
                    expect(page.get_by_role("button", name="Stop", exact=True)).not_to_be_visible()
                    import sqlite3
                    def audit_count(kind):
                        with sqlite3.connect(WORK / "runtime_return_review.db") as db:
                            return sum(json.loads(payload)["batch_type"] == kind for (payload,) in db.execute("SELECT payload FROM audit"))
                    def wait_for_audit(kind, expected):
                        deadline = time.monotonic() + 60
                        while audit_count(kind) < expected and time.monotonic() < deadline:
                            assert page.get_by_test_id("stException").count() == 0
                            page.wait_for_timeout(250)
                        assert audit_count(kind) == expected
                    wait_for_audit("return_refund", 2 * 3705)
                    record("Repeat return upload appends a fresh review without duplicating quantities")
                    navigate("Product Prioritization")
                    expect(page.get_by_text("Provisional equal-third weights", exact=False)).to_be_visible()
                    for label, filename in [("Download MCA readiness audit", "mca_audit.csv"),
                                            ("Download MCA rankings", "mca_results.csv"),
                                            ("Download weight comparison", "mca_sensitivity.csv")]:
                        with page.expect_download() as download:
                            page.get_by_role("button", name=label, exact=True).click()
                        target = WORK / filename
                        download.value.save_as(target)
                        actual_frame = pd.read_csv(target, dtype={"SKU": "string"})
                        expected_frame = pd.read_csv(ROOT / "validation_outputs/three_criterion_mca" / filename, dtype={"SKU": "string"})
                        pd.testing.assert_frame_equal(actual_frame, expected_frame, check_exact=False, rtol=1e-10, atol=1e-12)
                        record(label + " matches independent three-criterion backend")
                    screenshot("three-criterion-prioritization")
                    navigate("Data Upload & ETL")
                    page.get_by_test_id("stFileUploader").nth(0).locator("input[type=file]").set_input_files(str(ROOT / "raw_data/2022/Order.all.AUG2022.xlsx"))
                    expect(page.locator(".upload-summary .file-name")).to_have_text("Order.all.AUG2022.xlsx")
                    page.get_by_role("button", name="Process dataset", exact=True).click()
                    expect(page.get_by_text("New rows added", exact=True)).to_be_visible()
                    expect(page.get_by_role("button", name="Stop", exact=True)).not_to_be_visible()
                    wait_for_audit("sales", 3705)
                    record("Repeat sales upload triggers persisted request re-evaluation")
                    navigate("Replenishment Recommendations")
                page.get_by_test_id("stSidebarCollapseButton").click(timeout=10000)
                expect(page.get_by_test_id("stSidebar")).to_have_attribute("aria-expanded", "false")
                page.set_viewport_size({"width": 390, "height": 844})
                title_box = page.locator(".topbar-title").bounding_box()
                assert title_box and title_box["width"] > 100 and title_box["height"] < 40, title_box
                page.screenshot(path=str(OUTPUT / "mobile-replenishment.png"), full_page=True, animations="disabled")
                record("Mobile header fits; collapsed-sidebar viewport captured")
                page.set_viewport_size({"width": 1440, "height": 1000})
                page.reload()
                expect(page.get_by_role("button", name="Sign In", exact=True)).to_be_visible()
                record("Browser refresh restores login gate")
                assert not errors, errors
                completed = True
                browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)
            entry.unlink(missing_ok=True)
            (OUTPUT / "summary.json").write_text(json.dumps({"passed": completed, "checks": checks, "browser_errors": errors,
                "scope": "Isolated app.py process, actual datasets, local QA credentials; desktop Edge headless and mobile viewport screenshot"}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
