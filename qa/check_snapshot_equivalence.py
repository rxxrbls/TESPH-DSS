"""Compare saved pre-optimization and final isolated Star Schema snapshots."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = ROOT / ".artifacts/qa"


def main():
    before, after = WORK / "before_full_seed.db", WORK / "full_seed.db"
    if not before.is_file() or not after.is_file():
        raise FileNotFoundError("Both saved isolated snapshots are required")
    results = {}
    with closing(sqlite3.connect(before.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.execute("ATTACH DATABASE ? AS candidate", (after.as_uri() + "?mode=ro",))
        for table in ("prepared_transactions", "fact_sales", "dim_product", "dim_date", "dim_order", "dim_shipping", "dim_payment"):
            counts = [connection.execute(f"SELECT count(*) FROM {schema}.{table}").fetchone()[0] for schema in ("main", "candidate")]
            # Include rowid to verify order and duplicate multiplicity as well
            # as every value; plain EXCEPT alone only compares distinct rows.
            differences = [connection.execute(
                f"SELECT count(*) FROM (SELECT rowid, * FROM {left}.{table} EXCEPT SELECT rowid, * FROM {right}.{table})"
            ).fetchone()[0] for left, right in (("main", "candidate"), ("candidate", "main"))]
            assert counts[0] == counts[1] and differences == [0, 0], (table, counts, differences)
            results[table] = {"before_rows": counts[0], "after_rows": counts[1], "before_only": differences[0], "after_only": differences[1]}
    expected = json.loads((WORK / "fixtures.json").read_text())["baseline_sha256"]
    actual = hashlib.sha256((ROOT / "final_outputs/prepared_transactions.csv").read_bytes()).hexdigest()
    assert actual == expected, "Governed baseline changed"
    import pandas as pd
    from runtime_data_store import _restore_prepared_dtypes, load_active_state
    with closing(sqlite3.connect(after.as_uri() + "?mode=ro", uri=True)) as connection:
        legacy = _restore_prepared_dtypes(pd.read_sql_query("SELECT * FROM prepared_transactions", connection))
    restored = load_active_state(db_path=after).transactions
    pd.testing.assert_frame_equal(restored, legacy, check_exact=True)
    report = {"passed": True, "tables": results, "governed_baseline_sha256": actual,
              "chunked_restore": "Exact frame/dtype/index equality with original full-table SQL read",
              "comparison": "All columns and rowid, both directions; counts and duplicate multiplicity preserved"}
    (ROOT / "validation_outputs/integration_qa/snapshot_equivalence.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
