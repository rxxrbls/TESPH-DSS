"""Pure presentation helpers for SKU-level forecasts."""

import pandas as pd


def sku_forecast_table(results: dict[str, object]) -> pd.DataFrame:
    forecast = results.get("forecast_output")
    if not isinstance(forecast, pd.DataFrame) or forecast.empty:
        return pd.DataFrame()
    if "Method" in forecast:
        forecast = forecast.loc[~forecast["Method"].astype(str).str.contains("Seasonal", case=False, na=False)]
    required = {"SKU", "Time", "Forecast", "Method"}
    if not required.issubset(forecast.columns):
        return pd.DataFrame()
    forecast = forecast.copy()
    forecast["Time"] = pd.to_datetime(forecast["Time"], errors="coerce")
    forecast["Forecast"] = pd.to_numeric(forecast["Forecast"], errors="coerce")
    forecast = forecast.dropna(subset=["SKU", "Time", "Forecast"])
    product_col = next((c for c in ("Product", "Product Name") if c in forecast), None)
    group_columns = ["SKU"] + ([product_col] if product_col else []) + ["Method"]
    totals = forecast.groupby(group_columns, dropna=False, sort=True).agg(
        **{"Projected Units": ("Forecast", "sum"), "Forecast Days": ("Time", "nunique")}
    ).reset_index()
    totals = totals.loc[totals["Forecast Days"].eq(7)].copy()
    if totals.empty:
        return pd.DataFrame()
    forecast = forecast.merge(totals[group_columns], on=group_columns, how="inner")
    totals = totals.rename(columns={"Projected Units": "7-Day Projected Units"})
    forecast["Forecast Detail"] = forecast.apply(
        lambda r: f"{r['Time']:%Y-%m-%d}: {r['Forecast']:g}", axis=1
    )
    detail = forecast.groupby(group_columns, dropna=False, sort=True)["Forecast Detail"].agg("; ".join).reset_index()
    return totals.merge(detail, on=group_columns, how="left")


def sku_forecast_horizon(
    results: dict[str, object], table: pd.DataFrame
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    if table.empty:
        return None
    forecast = results.get("forecast_output")
    if not isinstance(forecast, pd.DataFrame) or "Method" not in forecast:
        return None
    forecast = forecast.loc[~forecast["Method"].astype(str).str.contains("Seasonal", case=False, na=False)]
    if not {"SKU", "Time", "Method"}.issubset(forecast.columns):
        return None
    eligible = table[["SKU", "Method"]].drop_duplicates()
    forecast = forecast.merge(eligible, on=["SKU", "Method"], how="inner")
    forecast["Time"] = pd.to_datetime(forecast["Time"], errors="coerce").dt.normalize()
    dates = pd.DatetimeIndex(forecast["Time"].dropna().unique()).sort_values()
    if len(dates) != 7 or not dates.equals(pd.date_range(dates[0], periods=7, freq="D")):
        return None
    return pd.Timestamp(dates[0]), pd.Timestamp(dates[-1])
