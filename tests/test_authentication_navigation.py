"""Regression coverage for authentication-gated application navigation."""

from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

import runtime_data_store
import utils.components as components
import utils.state as state


APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
NAVIGATION_LABELS = (
    "Dashboard",
    "Data Upload & ETL",
    "Sales & Product Analytics",
    "Demand Forecast",
    "Stock-Out Risk",
    "Replenishment Recommendations",
    "Product Prioritization",
)


def run_app() -> AppTest:
    return AppTest.from_file(APP_PATH, default_timeout=30).run()


def sidebar_content(app: AppTest) -> str:
    return "\n".join(str(getattr(element, "value", getattr(element, "label", ""))) for element in app.sidebar)


def test_logged_out_session_shows_only_login_and_hides_sidebar_navigation():
    app = run_app()

    assert not app.exception
    assert [input.label for input in app.text_input] == ["Username", "Password"]
    assert not app.sidebar.markdown
    assert not any(label in sidebar_content(app) for label in NAVIGATION_LABELS)
    logged_out_styles = "\n".join(markdown.value for markdown in app.markdown)
    assert '[data-testid="stSidebar"]' in logged_out_styles
    assert '[data-testid="stExpandSidebarButton"]' in logged_out_styles


def test_bootstrap_from_active_db_does_not_run_derived_pipelines_during_auth(monkeypatch):
    calls = []
    runtime = type(
        "Runtime",
        (),
        {
            "transactions": __import__("pandas").DataFrame({"Order ID": ["A"]}),
            "dataset_id": "dataset-1",
        },
    )()
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(runtime_data_store, "load_active_state", lambda *args, **kwargs: runtime)
    monkeypatch.setattr(state, "has_valid_analytics_for_active_dataset", lambda: False)
    monkeypatch.setattr(state, "has_valid_forecast_for_active_dataset", lambda: False)

    def record_analytics(frame):
        calls.append("analytics")
        return {"sales_summary": __import__("pandas").DataFrame({"Gross Revenue": [1.0]})}

    def record_forecast(frame):
        calls.append("forecast")
        return {"forecast_output": __import__("pandas").DataFrame({"SKU": ["SKU-1"], "Forecast": [1.0]})}

    monkeypatch.setattr("analytics_pipeline.run_analytics_pipeline", record_analytics)
    monkeypatch.setattr("forecasting_pipeline.run_forecasting_pipeline", record_forecast)

    state.bootstrap_from_active_db()

    assert calls == []


def test_invalid_login_remains_on_login_without_navigation(monkeypatch):
    monkeypatch.setattr(components, "is_authentication_configured", lambda: True)
    monkeypatch.setattr(components, "authenticate", lambda username, password: False)
    app = run_app()

    app.text_input[0].set_value("invalid-user")
    app.text_input[1].set_value("invalid-password")
    app.button[0].click().run()

    assert not app.exception
    assert any(error.value == "Invalid username or password." for error in app.error)
    assert [input.label for input in app.text_input] == ["Username", "Password"]
    assert not app.sidebar.markdown
    assert not any(label in sidebar_content(app) for label in NAVIGATION_LABELS)


def test_valid_login_exposes_all_authorized_navigation(monkeypatch):
    monkeypatch.setattr(components, "is_authentication_configured", lambda: True)
    monkeypatch.setattr(components, "authenticate", lambda username, password: True)
    app = run_app()

    app.text_input[0].set_value("authorized-user")
    app.text_input[1].set_value("valid-password")
    app.button[0].click().run()

    assert not app.exception
    assert app.session_state["authenticated"] is True
    rendered_sidebar = sidebar_content(app)
    assert all(label in rendered_sidebar for label in NAVIGATION_LABELS)
    authenticated_styles = "\n".join(markdown.value for markdown in app.markdown)
    assert '[data-testid="stExpandSidebarButton"] { display:none !important; }' not in authenticated_styles


def test_authenticated_sidebar_keeps_streamlits_native_collapse_controls_available():
    app_source = APP_PATH.read_text(encoding="utf-8")
    component_source = Path(components.__file__).read_text(encoding="utf-8")

    assert "initial_sidebar_state" not in app_source
    assert '[data-testid="stHeader"] * { pointer-events:none' not in component_source
    assert "def hide_sidebar_for_logged_out_user" in component_source
