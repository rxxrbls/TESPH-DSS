"""TESPH DSS Streamlit application entry point."""

import streamlit as st

from utils.components import (
    hide_sidebar_for_logged_out_user,
    inject_global_styles,
    render_login_screen,
    render_sidebar,
)
from utils.auth import is_authenticated
from utils.state import initialize_app_state


st.set_page_config(
    page_title="TESPH Decision Support System",
    page_icon="â˜€ï¸",
    layout="wide",
)

initialize_app_state()
inject_global_styles()

if not is_authenticated():
    hide_sidebar_for_logged_out_user()
    render_login_screen()
    st.stop()

pages = {
    "Overview": [
        st.Page("pages/dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True),
    ],
    "Data": [
        st.Page("pages/data_upload.py", title="Data Upload & ETL", icon=":material/upload_file:"),
    ],
    "Analyze": [
        st.Page("pages/sales_product_analytics.py", title="Sales & Product Analytics", icon=":material/analytics:"),
        st.Page("pages/demand_forecast.py", title="Demand Forecast", icon=":material/trending_up:"),
        st.Page("pages/stock_out_risk.py", title="Stock-Out Risk", icon=":material/warning:"),
    ],
    "Decide": [
        st.Page("pages/replenishment_recommendations.py", title="Replenishment Recommendations", icon=":material/refresh:"),
        st.Page("pages/product_prioritization.py", title="Product Prioritization", icon=":material/format_list_numbered:"),
    ],
}

navigation = st.navigation(pages, position="hidden")
render_sidebar()
navigation.run()
