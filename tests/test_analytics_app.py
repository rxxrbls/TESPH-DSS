"""UI contracts using synthetic data, never live approval claims."""

from dataclasses import asdict
from pathlib import Path

import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from test_week2 import approved_mapping, settings, transactions


@pytest.fixture
def app(monkeypatch):
    data = transactions()
    monkeypatch.setattr("analytics_data.load_transactions", lambda: data.copy())
    st.cache_data.clear()
    result = AppTest.from_file(Path(__file__).resolve().parents[1] / "analytics_app.py", default_timeout=30).run()
    yield result
    st.cache_data.clear()


def assert_healthy(app):
    assert not app.exception
    assert not app.error


def test_descriptive_views_and_filters(app):
    assert_healthy(app)
    assert len(app.tabs) == 6
    assert app.metric[0].value == "PHP 1,200.00"
    app.text_input(key="product_search").set_value("does-not-exist").run()
    assert_healthy(app)
    assert any("No matching records" in i.value for i in app.info)


def test_forecast_without_mapping_is_explicit(app):
    app.radio[0].set_value("Demand Forecast").run()
    assert_healthy(app)
    assert any("Operational forecasts are withheld" in i.value for i in app.info)


def test_forecast_shows_selected_method_metrics_and_sku_choice(app):
    app.session_state["sku_mapping"] = approved_mapping(transactions())
    app.session_state["forecast_config"] = asdict(settings(validation_periods=5))
    app.radio[0].set_value("Demand Forecast").run()
    assert_healthy(app)
    assert [m.label for m in app.metric] == ["MAE", "RMSE", "Adjusted MAPE", "R2"]
    assert app.metric[2].value != "N/A"
    assert len(app.tabs) == 5
    app.selectbox[0].set_value("002").run()
    assert_healthy(app)
    assert any(s.value.startswith("Selected Method:") for s in app.subheader)


def test_multi_step_chart_has_explicit_origin(app):
    app.session_state["sku_mapping"] = approved_mapping(transactions())
    app.session_state["forecast_config"] = asdict(settings(horizon=2))
    app.radio[0].set_value("Demand Forecast").run()
    assert_healthy(app)
    assert app.selectbox[1].label == "Validation origin"
    app.selectbox[1].select_index(1).run()
    assert_healthy(app)
