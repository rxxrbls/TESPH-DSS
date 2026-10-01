"""Validate Star Schema database integrity and relationships."""
import sqlite3
from contextlib import closing
from pathlib import Path
from etl_config import RUNTIME_DB_PATH

INTEGRITY_CHECKS = [
    ("dim_product PK unique",
     "SELECT COUNT(*) - COUNT(DISTINCT product_key) FROM dim_product"),
    ("dim_date PK unique",
     "SELECT COUNT(*) - COUNT(DISTINCT date_key) FROM dim_date"),
    ("dim_order PK unique",
     'SELECT COUNT(*) - COUNT(DISTINCT "Order ID") FROM dim_order'),
    ("dim_shipping PK unique",
     "SELECT COUNT(*) - COUNT(DISTINCT shipping_key) FROM dim_shipping"),
    ("dim_payment PK unique",
     "SELECT COUNT(*) - COUNT(DISTINCT payment_key) FROM dim_payment"),
    ("fact_sales PK unique",
     "SELECT COUNT(*) - COUNT(DISTINCT sales_line_key) FROM fact_sales"),
    ("fact → dim_product orphans",
     """SELECT COUNT(*) FROM fact_sales f
        LEFT JOIN dim_product d ON f.product_key = d.product_key
        WHERE d.product_key IS NULL"""),
    ("fact → dim_date orphans",
     """SELECT COUNT(*) FROM fact_sales f
        LEFT JOIN dim_date d ON f.date_key = d.date_key
        WHERE d.date_key IS NULL AND f.date_key IS NOT NULL"""),
    ("fact → dim_order orphans",
     """SELECT COUNT(*) FROM fact_sales f
        LEFT JOIN dim_order d ON f."Order ID" = d."Order ID"
        WHERE d."Order ID" IS NULL"""),
    ("fact → dim_shipping orphans",
     """SELECT COUNT(*) FROM fact_sales f
        LEFT JOIN dim_shipping d ON f.shipping_key = d.shipping_key
        WHERE d.shipping_key IS NULL"""),
    ("fact → dim_payment orphans",
     """SELECT COUNT(*) FROM fact_sales f
        LEFT JOIN dim_payment d ON f.payment_key = d.payment_key
        WHERE d.payment_key IS NULL"""),
]

def validate_database(db_path: Path = RUNTIME_DB_PATH) -> list[dict]:
    """Run all integrity checks. Returns list of {check, expected, actual, status}."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found at {db_path}")
        
    results = []
    with closing(sqlite3.connect(db_path)) as conn:
        for check_name, query in INTEGRITY_CHECKS:
            try:
                count = conn.execute(query).fetchone()[0]
                results.append({
                    "check": check_name,
                    "expected": 0,
                    "actual": count,
                    "status": "PASS" if count == 0 else "FAIL",
                })
            except sqlite3.OperationalError as e:
                results.append({
                    "check": check_name,
                    "expected": 0,
                    "actual": -1,
                    "status": f"ERROR: {str(e)}"
                })
    return results

if __name__ == "__main__":
    import sys
    print(f"Validating database at {RUNTIME_DB_PATH} ...")
    try:
        checks = validate_database()
        all_passed = True
        for c in checks:
            status_symbol = "PASS" if c["status"] == "PASS" else "FAIL"
            # Replace non-ASCII arrow so the output is safe on Windows charmap.
            check_name = c["check"].replace("\u2192", "->")
            print(f"{status_symbol} {check_name}: Expected {c['expected']}, Actual {c['actual']}")
            if c["status"] != "PASS":
                all_passed = False
        sys.exit(0 if all_passed else 1)
    except Exception as exc:
        print(f"Validation failed: {exc}")
        sys.exit(1)
