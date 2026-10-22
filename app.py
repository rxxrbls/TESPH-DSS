"""TESPH DSS Streamlit application entry point."""

import streamlit as st

from utils.account_store import verify_account_email
from utils.components import (
    hide_sidebar_for_logged_out_user,
    inject_global_styles,
    render_login_screen,
    render_sidebar,
)
from utils.auth import is_authenticated
from utils.state import initialize_app_state, restore_runtime_authority


st.set_page_config(
    page_title="TESPH Decision Support System",
    page_icon="â˜€ï¸",
    layout="wide",
)

initialize_app_state()
inject_global_styles()

verification_token = st.query_params.get("verify_email_token")
if verification_token:
    verification_result = verify_account_email(str(verification_token))
    st.query_params.pop("verify_email_token", None)
    st.session_state["account_email_verification_notice"] = verification_result

verification_notice = st.session_state.pop("account_email_verification_notice", None)
if verification_notice:
    verified, message = verification_notice
    if verified:
        st.success(message)
    else:
        st.error(message)

if not is_authenticated():
    hide_sidebar_for_logged_out_user()
    render_login_screen()
    st.stop()

restore_runtime_authority()

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
    "Support": [
        st.Page("pages/settings.py", title="Settings", icon=":material/settings:"),
        st.Page("pages/help_user_guide.py", title="Help & User Guide", icon=":material/help:"),
    ],
}

navigation = st.navigation(pages, position="hidden")
render_sidebar()
navigation.run()
