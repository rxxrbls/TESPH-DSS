"""Human-readable ETL error messages for the upload UI."""

ERROR_MESSAGES = {
    "ingestion_failed": (
        "We couldn't read your file. Please ensure it is a valid CSV or XLSX "
        "export from Shopee Seller Centre and try again."
    ),
    "empty_file": (
        "The uploaded file appears to be empty. Please check that your Shopee "
        "export contains transaction data."
    ),
    "missing_required_columns": (
        "Your file is missing required columns. A Shopee export must include: "
        "Order ID, Product Name, Quantity, and Order Creation Date."
    ),
    "data_type_validation_failed": (
        "Some values in your file have unexpected formats (e.g., text in a "
        "numeric field, or unparseable dates). Review the details below and "
        "re-export from Shopee."
    ),
    "transformation_failed": (
        "We encountered an error while building the analytical tables from "
        "your data. This usually indicates a structural issue with the export."
    ),
    "schema_validation_failed": (
        "The processed data does not match the expected column structure. "
        "This may indicate the Shopee export format has changed."
    ),
}

def get_user_message(error_key: str, technical_detail: str = "") -> str:
    """Return a user-friendly error message, with optional technical detail."""
    base = ERROR_MESSAGES.get(error_key, "An unexpected error occurred.")
    if technical_detail:
        return f"{base}\n\n**Technical detail:** {technical_detail}"
    return base
