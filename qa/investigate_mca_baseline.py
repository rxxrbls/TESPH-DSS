"""Read-only baseline diagnosis; no eligibility, status or weight changes."""
from pathlib import Path
import sys,json,zipfile
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from analytics_data import load_transactions
from analytics_calculations import prepare_transactions
from etl_config import InventoryConfig
from etl_inventory import load_current_inventory,build_inventory_crosswalk
from prescriptive_pipeline import build_sku_mapping_from_stock_upload
from star_schema_db import read_runtime_star_schema
out=ROOT/'validation_outputs/mca_investigation'; out.mkdir(exist_ok=True)
tx=load_transactions(); prep=prepare_transactions(tx)
cfg=InventoryConfig(stock_as_of=pd.Timestamp('2026-09-09'),stock_definition_confirmed=True)
dim=read_runtime_star_schema(ROOT/'.artifacts/qa/full_seed.db')['dim_product']
cross=build_inventory_crosswalk(load_current_inventory(cfg),dim,cfg)
mp,invreview=build_sku_mapping_from_stock_upload(tx,cross,stock_as_of=cfg.stock_as_of,as_of='2026-10-20')
accepted=mp.loc[mp.SKU.notna()]
with zipfile.ZipFile(ROOT.parent/'RETURN_REFUND_HANDOFF-20261016T123959Z-1-001.zip') as z:
 rr=pd.read_csv(z.open(next(n for n in z.namelist() if n.endswith('/prepared_return_refund_backend.csv'))),dtype=str,keep_default_na=False)
end=prep.Time.max().normalize(); positive=prep.loc[prep['Gross Demand'].gt(0)]
profile=prep.groupby('Product Key').agg(first_seen=('Time','min'),last_seen=('Time','max'),units=('Gross Demand','sum'))
profile['last_positive']=positive.groupby('Product Key').Time.max()
for days in (14,30,90,365):
 profile[f'units_last_{days}d']=positive.loc[positive.Time.dt.normalize().gt(end-pd.Timedelta(days=days))].groupby('Product Key')['Gross Demand'].sum()
profile=profile.fillna({c:0 for c in profile if c.startswith('units_')})
profile['request_lines']=rr.groupby('product_key').size()
profile['refunded_lines']=rr.loc[rr['Return / Refund Status'].eq('Request Refunded')].groupby('product_key').size()
profile[['request_lines','refunded_lines']]=profile[['request_lines','refunded_lines']].fillna(0)
profile['days_since_positive']=(end-profile.last_positive.dt.normalize()).dt.days
current=accepted.merge(profile,left_on='product_key',right_index=True)
current.to_csv(out/'current_catalog_history.csv',index=False)
cross.groupby(['match_status','review_reasons'],dropna=False).size().rename('rows').reset_index().to_csv(out/'stock_exclusion_counts.csv',index=False)
keys=set(accepted.product_key)
# Distinct original SKU identities; no remapping or stock-pool guessing.
skus=prep.dropna(subset=['SKU']).groupby('Product Key').SKU.agg(lambda x: sorted(set(x)))
unique=skus.loc[skus.map(len).eq(1)].map(lambda x:x[0])
unique=unique.loc[~unique.duplicated(False)]
hist=profile.loc[profile.index.isin(unique.index)].copy(); hist['SKU']=unique
hist=hist.join(prep[['Product Key','Product','Category']].drop_duplicates().set_index('Product Key'))
hist.to_csv(out/'unique_historical_sku_history.csv')
summary={'sales_end':str(end),'transaction_rows':len(tx),'historical_product_keys':len(profile),'stock_rows':len(cross),'stock_status':cross.match_status.value_counts().to_dict(),'accepted_stock_skus':len(accepted),'current_total_historical_units':float(current.units.sum()),'current_last_positive_min':str(current.last_positive.min()),'current_last_positive_max':str(current.last_positive.max()),'current_no_positive_history':int(current.last_positive.isna().sum()),'current_positive_last_30d':int(current.units_last_30d.gt(0).sum()),'all_products_positive_last_30d':int(profile.units_last_30d.gt(0).sum()),'current_requests':int(rr.product_key.isin(keys).sum()),'current_refunded_lines':int((rr.product_key.isin(keys)&rr['Return / Refund Status'].eq('Request Refunded')).sum()),'unique_historical_skus':len(hist),'unique_historical_skus_positive_last_30d':int(hist.units_last_30d.gt(0).sum()),'unique_historical_skus_with_refunded_lines':int(hist.refunded_lines.gt(0).sum()),'unique_historical_skus_positive_last_30d_and_refunded':int((hist.units_last_30d.gt(0)&hist.refunded_lines.gt(0)).sum())}
# Compare refund product keys against every inventory candidate, including rejected ambiguous pools.
all_candidates=set(k.strip() for v in cross.candidate_product_keys.fillna('') for k in v.split(' | ') if k.strip())
summary['request_lines_in_any_stock_candidate']=int(rr.product_key.isin(all_candidates).sum())
summary['refunded_lines_in_any_stock_candidate']=int((rr.product_key.isin(all_candidates)&rr['Return / Refund Status'].eq('Request Refunded')).sum())
# Further read-only checks: distinguish product-level overlap from eligible SKU overlap.
summary['inventory_eligibility_reasons']=invreview.Reason.value_counts().to_dict()
summary['missing_sku_transaction_rows']=int(prep.SKU.isna().sum())
summary['historical_keys_without_sku']=int((~profile.index.isin(skus.index)).sum())
summary['historical_keys_multiple_skus']=int(skus.map(len).gt(1).sum())
safe=cross.loc[cross.match_status.eq('candidate')]
safekeys=set(safe.product_key.dropna())
summary['request_lines_in_unambiguous_stock_candidates']=int(rr.product_key.isin(safekeys).sum())
summary['refunded_lines_in_unambiguous_stock_candidates']=int((rr.product_key.isin(safekeys)&rr['Return / Refund Status'].eq('Request Refunded')).sum())
summary['unambiguous_stock_candidates_without_sku']=int(safe.SKU.isna().sum())
cohort=prep.loc[prep['Product Key'].isin(keys)].copy()
april=prep.loc[prep.Time.dt.normalize().between('2026-04-01','2026-04-24')].copy()
summary['april_status_counts_all']=april['Order Status'].value_counts().to_dict()
summary['april_current_catalog_status_counts']=cohort.loc[cohort.Time.dt.normalize().between('2026-04-01','2026-04-24'),'Order Status'].value_counts().to_dict()
summary['april_all_rows']=len(april)
summary['april_positive_demand_rows']=int(april['Gross Demand'].gt(0).sum())
summary['april_noncancelled_zero_demand_rows']=int((~april['Is Cancelled'] & april['Gross Demand'].eq(0)).sum())
# Show fixed recent month-end windows without choosing a favorable date.
windows=[]
for cutoff in pd.to_datetime(['2025-12-31','2026-01-31','2026-02-28','2026-03-31','2026-04-24']):
 recent=positive.loc[positive.Time.dt.normalize().between(cutoff-pd.Timedelta(days=29),cutoff)]
 windows.append({'cutoff':str(cutoff.date()),'current_catalog_products_positive_30d':recent.loc[recent['Product Key'].isin(keys),'Product Key'].nunique(),'all_products_positive_30d':recent['Product Key'].nunique()})
summary['fixed_window_activity_diagnostics']=windows
from forecasting_pipeline import run_forecasting_pipeline
forecasts=run_forecasting_pipeline(tx,mapping=mp)
forecasts['best_methods'].to_csv(out/'current_selected_methods.csv',index=False)
forecasts['forecast_output'].to_csv(out/'current_forecasts.csv',index=False)
forecasts['eligibility'].groupby('Reason',dropna=False).size().rename('products').to_csv(out/'forecast_eligibility_counts.csv')
summary['forecast_winning_methods']=forecasts['best_methods'].Method.value_counts().to_dict()
summary['forecast_rows']=len(forecasts['forecast_output'])
summary['forecast_all_exact_zero']=bool(forecasts['forecast_output'].Forecast.eq(0).all())
summary['forecast_end']=str(forecasts['forecasting_dataset'].Time.max())
summary['validation_actual_nonzero_rows']=int(forecasts['validation_detail'].Actual.ne(0).sum())
summary['validation_rows']=len(forecasts['validation_detail'])
(out/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary,indent=2))

# Spot-check original exports; counts exclude weight fields, which are not IDs.
raw_checks={}
for filename in ['raw_data/2026/Order.all.APRIL2026.xlsx', 'raw_data/2026/Order.all.MARCH2026.xlsx', 'raw_data/2022/Order.all.AUG2022.xlsx']:
    raw=pd.read_excel(ROOT/filename,dtype=str,keep_default_na=False)
    raw_checks[filename]={'rows':len(raw),'sku_fields':{c:int(raw[c].str.strip().ne('').sum()) for c in ('Parent SKU Reference No.', 'SKU Reference No.') if c in raw},'statuses':raw['Order Status'].value_counts().to_dict()}
(out/'raw_export_checks.json').write_text(json.dumps(raw_checks,indent=2),encoding='utf-8')
