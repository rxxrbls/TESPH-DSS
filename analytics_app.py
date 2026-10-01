"""Streamlit entry point for the Week 2 descriptive and SKU forecast outputs."""

from dataclasses import asdict
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import streamlit as st

from analytics_data import OUTPUT_DIR, load_transactions
from active_inventory import INVENTORY_PATH, build_active_mapping
from analytics_pipeline import run_analytics_pipeline
from forecasting_pipeline import run_forecasting_pipeline
from methodology_config import ForecastConfig
from sku_forecasting import mapping_template, validate_mapping


ROOT = Path(__file__).resolve().parent
st.set_page_config(page_title="TESPH | Sales & Forecasts", layout="wide")
st.markdown("""<style>
html, body, h1, h2, h3 { letter-spacing: 0; }
h1 { font-size: 28px !important; }
[data-testid="stMetricValue"], [data-testid="stMetricValue"] > div {
    font-size: 24px; line-height: 1.35; white-space: normal;
    overflow: visible; text-overflow: clip; overflow-wrap: anywhere;
}
</style>""", unsafe_allow_html=True)


@st.cache_data(show_spinner=False)
def read_handoff(stamp: int) -> pd.DataFrame:
    return load_transactions()


@st.cache_data(show_spinner=False, max_entries=8)
def descriptive(data: pd.DataFrame, coverage_end: str) -> dict[str, pd.DataFrame]:
    return run_analytics_pipeline(data, coverage_end=coverage_end)


@st.cache_data(show_spinner=False, max_entries=4)
def predictive(data: pd.DataFrame, mapping: pd.DataFrame | None, settings: dict) -> dict[str, pd.DataFrame]:
    return run_forecasting_pipeline(data, mapping=mapping, config=ForecastConfig(**settings))


@st.cache_data(show_spinner=False, max_entries=2)
def current_catalog(data: pd.DataFrame, stamp: int, today: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    return build_active_mapping(data, as_of=today)


def table(frame: pd.DataFrame, name: str) -> None:
    if frame.empty:
        st.info("No matching records.")
        return
    st.dataframe(frame, hide_index=True, width="stretch")
    st.download_button("Download CSV", frame.to_csv(index=False).encode("utf-8"),
                       file_name=name + ".csv", mime="text/csv", icon=":material/download:", key=name)


def export_results(results: dict[str, pd.DataFrame]) -> bytes:
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, frame in results.items():
            archive.writestr(name + ".csv", frame.to_csv(index=False))
    return output.getvalue()


def metric(label: str, value: float, kind: str = "number") -> None:
    formatted = "N/A" if pd.isna(value) else (f"PHP {value:,.2f}" if kind == "money" else
                 f"{value:.2%}" if kind == "rate" else f"{value:,.0f}")
    st.metric(label, formatted)


def sales_view(data: pd.DataFrame) -> None:
    st.title("Sales & Product Analytics")
    dates = pd.to_datetime(data["order_date"])
    columns = st.columns([2, 3])
    with columns[0]:
        interval = st.date_input("Order dates", value=(dates.min().date(), dates.max().date()),
                                 min_value=dates.min().date(), max_value=dates.max().date())
    with columns[1]:
        categories = st.multiselect("Categories", sorted(data["final_category"].dropna().unique()))
    if len(interval) != 2:
        st.info("Select an end date.")
        return
    selected = data.loc[dates.between(pd.Timestamp(interval[0]), pd.Timestamp(interval[1]) + pd.Timedelta(days=1), inclusive="left")]
    if categories:
        selected = selected.loc[selected["final_category"].isin(categories)]
    if selected.empty:
        st.info("No transactions in this selection.")
        return
    with st.spinner("Calculating sales..."):
        results = descriptive(selected, str(interval[1]))
    summary = results["sales_summary"].iloc[0]
    for column, (label, key, kind) in zip(st.columns(4), [
        ("Gross revenue", "Gross Revenue", "money"), ("Gross demand", "Gross Demand", "number"),
        ("Completed orders", "Completed Order Count", "number"), ("Average order value", "Average Order Value", "money")]):
        with column:
            metric(label, summary[key], kind)
    tabs = st.tabs(["Summary", "Products", "Trends", "Returns", "Cancellations", "Movement & Review"])
    with tabs[0]:
        table(results["sales_summary"].T.rename_axis("Metric").reset_index().rename(columns={0: "Value"}).astype(str), "sales_summary")
        table(results["kpis"], "kpis")
        table(results.get("yoy_growth", pd.DataFrame()), "yoy_growth")
    with tabs[1]:
        products = results["product_performance"]
        search = st.text_input("Product or SKU", key="product_search")
        if search:
            products = products.loc[products["Product"].str.contains(search, case=False, regex=False, na=False) |
                                    products["SKU"].str.contains(search, case=False, regex=False, na=False)]
        table(products, "product_performance")
    with tabs[2]:
        trends = results["sales_trends"]
        chart = trends.pivot(index="Time", columns="Category", values="Gross Revenue")
        st.line_chart(chart, color=["#147d64", "#d45d79", "#d4a52c", "#438bc4"] if len(chart.columns) == 4 else None)
        table(trends, "sales_trends")
    with tabs[3]:
        for column, (label, key, kind) in zip(st.columns(3), [
            ("Returned units", "Returned Quantity", "number"), ("Return quantity rate", "Return Quantity Rate", "rate"),
            ("Return order rate", "Return Order Rate", "rate")]):
            with column:
                metric(label, summary[key], kind)
        table(results["return_indicators_by_category"], "returns_by_category")
    with tabs[4]:
        for column, (label, key, kind) in zip(st.columns(3), [
            ("Cancelled orders", "Cancelled Order Count", "number"), ("Cancelled units", "Cancelled Quantity", "number"),
            ("Cancellation rate", "Cancellation Order Rate", "rate")]):
            with column:
                metric(label, summary[key], kind)
        table(results["cancellations"], "cancellations")
        table(results["order_status"], "order_status")
    with tabs[5]:
        st.subheader("Product Movement")
        table(results["movement_classified"], "product_movement")
        st.subheader("Underperforming Products")
        table(results["products_for_review"], "products_for_review")
        table(results["sales_velocity"], "sales_velocity")
    st.download_button("Export analytics", export_results(results), "descriptive_analytics.zip",
                       "application/zip", icon=":material/download:")


def forecast_view(data: pd.DataFrame) -> None:
    st.title("Demand Forecast")
    config = st.session_state.get("forecast_config", asdict(ForecastConfig()))
    mapping = st.session_state.get("sku_mapping")
    inventory_review = pd.DataFrame()
    with st.expander("Forecast Settings", expanded=mapping is None):
        mapping_file = st.file_uploader("Client-approved SKU mapping", type="csv")
        config_file = st.file_uploader("Methodology configuration", type="json")
        st.download_button("Download mapping template", mapping_template(data).to_csv(index=False),
                           "sku_mapping.csv", "text/csv", icon=":material/download:")
        st.download_button("Download configuration", json.dumps(config, indent=2), "forecast_config.json",
                           "application/json", icon=":material/download:")
        if mapping_file is not None:
            mapping_file.seek(0)
            mapping = validate_mapping(pd.read_csv(mapping_file, dtype={"product_key": "string", "SKU": "string"}))
        if config_file is not None:
            config_file.seek(0)
            config = asdict(ForecastConfig(**json.load(config_file)))
        ForecastConfig(**config).validate()
        st.session_state["sku_mapping"] = mapping
        st.session_state["forecast_config"] = config
    if mapping is None and INVENTORY_PATH.exists():
        mapping, inventory_review = current_catalog(data, INVENTORY_PATH.stat().st_mtime_ns,
                                                    str(pd.Timestamp.today().date()))
    with st.spinner("Preparing SKU forecasts..."):
        results = predictive(data, mapping, config)
    results["inventory_review"] = inventory_review
    status = results["selection_status"].iloc[0]
    if results["forecast_output"].empty:
        st.info("No eligible active SKU forecasts. Operational forecasts are withheld.")
    else:
        st.caption(f"{status['Forecast SKU Count']} eligible SKU forecasts | {config['frequency']} periods | Horizon {config['horizon']}")
    output = results["forecast_output"]
    coverage = pd.Timestamp(status["History Coverage End"])
    st.caption(f"Sales coverage through {coverage:%Y-%m-%d}")
    if not output.empty and output["Time"].max().normalize() < pd.Timestamp.today().normalize():
        st.warning("Historical forecast only: the forecast horizon has already ended. Refresh sales data before using these results for current inventory decisions.")
    if not output.empty:
        labels = output.drop_duplicates("SKU").set_index("SKU")["Product"].to_dict()
        sku = st.selectbox("SKU", list(labels), format_func=lambda s: f"{s} | {labels[s]}")
        winner = results["best_methods"].loc[lambda f: f.SKU.eq(sku)].iloc[0]
        st.subheader("Selected Method: " + winner["Method"])
        for column, key in zip(st.columns(4), ["MAE", "RMSE", "MAPE", "R2"]):
            with column:
                value = winner[key]
                label = "Adjusted MAPE" if key == "MAPE" and config["mape_zero_policy"] == "denominator_floor" else key
                st.metric(label, "N/A" if pd.isna(value) else f"{value:,.3f}" + ("%" if key == "MAPE" else ""))
        st.caption(winner["MAPE Status"])
        detail = results["validation_detail"].loc[lambda f: f.SKU.eq(sku) & f.Method.eq(winner["Method"])]
        # Each origin is a separate trace so multi-step holdouts are never averaged.
        origin = st.selectbox("Validation origin", sorted(detail["Origin"].unique()), format_func=lambda d: pd.Timestamp(d).strftime("%Y-%m-%d")) if config["horizon"] > 1 else None
        chart = detail.loc[detail.Origin.eq(origin)] if origin is not None else detail
        st.subheader("Actual vs Forecast")
        st.line_chart(chart.set_index("Time")[["Actual", "Forecast"]], color=["#147d64", "#d45d79"])
        tabs = st.tabs(["SKU Forecast", "Product Totals", "Category Totals", "Evaluation", "Eligibility"])
        for tab, key in zip(tabs, ["forecast_output", "product_forecast", "category_forecast", "validation_metrics", "eligibility"]):
            with tab:
                table(results[key], key)
        with st.expander("Validation Detail"):
            table(results["validation_detail"], "validation_detail")
            table(results["parameter_search"], "parameter_search")
    else:
        table(results["eligibility"], "eligibility")
    if not inventory_review.empty:
        with st.expander("Current Catalog Evidence"):
            table(inventory_review, "inventory_review")
    with st.expander("Methodology"):
        table(results["methodology"], "methodology")
    st.download_button("Export forecast results", export_results(results), "forecast_results.zip",
                       "application/zip", icon=":material/download:")


with st.sidebar:
    logo = ROOT / "assets" / "theeverythingshopph-logo.png"
    if logo.exists():
        st.image(str(logo), width=160)
    st.header("TESPH-DSS")
    view = st.radio("Analytics", ["Sales & Products", "Demand Forecast"])

try:
    source = OUTPUT_DIR / "prepared_transactions.csv"
    data = read_handoff(source.stat().st_mtime_ns)
    st.sidebar.caption(f"{len(data):,} transaction lines")
    if data.empty:
        st.info("The ETL handoff contains no transactions.")
    elif view == "Sales & Products":
        sales_view(data)
    else:
        forecast_view(data)
except (OSError, ValueError, KeyError, TypeError) as error:
    st.error(str(error))
