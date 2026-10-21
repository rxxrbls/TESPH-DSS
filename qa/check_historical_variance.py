"""Retrospective mechanics checks at fixed earlier month ends; no live writes."""
from pathlib import Path
import hashlib
import json
import sys
import zipfile
import pandas as pd
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analytics_data import load_transactions
from analytics_pipeline import run_analytics_pipeline
from forecasting_pipeline import run_forecasting_pipeline
from etl_config import InventoryConfig
from etl_inventory import load_current_inventory, build_inventory_crosswalk
from prescriptive_pipeline import build_sku_mapping_from_stock_upload, run_prescriptive_pipeline
from three_criterion_mca import Coverage, rank_scenarios


def main():
    out = ROOT / 'validation_outputs/historical_variance'
    out.mkdir(parents=True, exist_ok=True)
    source = ROOT / '.artifacts/qa/integration_readiness/prepared_transactions.csv'
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    tx = load_transactions(source)
    dates = pd.to_datetime(tx.order_date).dt.normalize()
    dim = pd.read_csv(source.parent / 'dim_product.csv', dtype='string')
    cfg = InventoryConfig(stock_as_of=pd.Timestamp('2026-09-09'), stock_definition_confirmed=True)
    cross = build_inventory_crosswalk(load_current_inventory(cfg), dim, cfg)
    archive_path = ROOT.parent / 'RETURN_REFUND_HANDOFF-20261016T123959Z-1-001.zip'
    with zipfile.ZipFile(archive_path) as z:
        rr = pd.read_csv(z.open(next(n for n in z.namelist() if n.endswith('/prepared_return_refund_backend.csv'))), dtype=str, keep_default_na=False)
    request_dates = pd.to_datetime(rr['Return Creation Time'], format='mixed', errors='raise').dt.normalize()
    summaries = []
    # Predeclared consecutive completed month ends; retain every result, not just favorable ones.
    for end in ('2025-12-31', '2026-01-31', '2026-02-28', '2026-03-31'):
        print('Historical mechanics assessment: ' + end, flush=True)
        subset = tx.loc[dates.le(end)].copy()
        evidence = rr.loc[request_dates.le(end)].copy()
        mapping, _ = build_sku_mapping_from_stock_upload(subset, cross,
            stock_as_of=cfg.stock_as_of, as_of='2026-10-20')
        forecasts = run_forecasting_pipeline(subset, mapping=mapping, coverage_end=end)
        analytics = run_analytics_pipeline(subset)
        coverage = Coverage('2020-05-22', end, '2020-05-01', end,
                            '2026-10-15', '2026-10-16', established=True)
        results = run_prescriptive_pipeline(subset, analytics, forecasts, cross,
            as_of='2026-10-20', mca_return_snapshot=evidence, mca_coverage=coverage)
        scenarios, comparison, summary = rank_scenarios(results['mca_audit'])
        summary.update({'order_end':end, 'sales_rows':len(subset), 'request_lines':len(evidence),
            'nonzero_forecast_skus':int(forecasts['forecast_output'].groupby('SKU').Forecast.sum().gt(0).sum())})
        baseline = scenarios['equal_thirds']
        velocity_order = baseline.sort_values(['Sales Velocity','SKU'], ascending=[False,True]).SKU.tolist()
        velocity_ranks = {sku:i+1 for i,sku in enumerate(velocity_order)}
        summary['rank_changes_vs_sales_velocity_only'] = int(baseline.apply(
            lambda row: row['Priority Rank'] != velocity_ranks[row.SKU], axis=1).sum())
        summary['forecast_at_least_0_01_units_skus'] = int(baseline['Forecasted Demand'].ge(.01).sum())
        summary['magnitude_note'] = '0.01 units is a reporting diagnostic only; no scoring or eligibility threshold changed.'
        for label, frame in {'readiness':results['mca_audit'], 'sensitivity':comparison, **scenarios}.items():
            frame.to_csv(out / (end + '_' + label + '.csv'), index=False)
        summaries.append(summary)
        print(json.dumps(summary), flush=True)
    report = {'approved_baseline':'equal_thirds', 'source_sha256':digest,
        'refund_archive_sha256':hashlib.sha256(archive_path.read_bytes()).hexdigest(),
        'assessments':summaries,
        'scope':'Expanded assessment across four earlier periods within available history, not additional sales after April 24. Retrospective mechanics only: September catalog is a fixed current-identity filter, not proof of historical stock/activity; October refund outcomes cannot reconstruct historical status availability. No risk/replenishment recommendations are published.',
        'final_signoff':False}
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
    (out / 'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
