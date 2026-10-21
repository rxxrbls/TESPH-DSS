"""TA-requested synthetic staging check; never modifies real business data."""
from pathlib import Path
import io
import json
import sqlite3
import sys
import tempfile
import gc
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest
from test_week3_prescriptive_pipeline import _pipeline_inputs
from mca_refresh import refresh_connected
from three_criterion_mca import Coverage, RATE
from utils.state import DEFAULT_STATE, DataStatus


def run(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    tx0, an0, fc0, st0 = _pipeline_inputs()
    txs, stocks, forecasts, requests = [], [], [], []
    for i in range(8):
        sku, key, product, order = f'SYNTH-{i}', f'SYNTH-P{i}', f'Synthetic product {i}', f'SYNTH-O{i}'
        tx = tx0.iloc[:1].copy()
        for col, val in {'Order ID':order,'SKU Reference No.':sku,'Product Name':product,
                         'product_key':key,'final_base_product_name':product,'Variation Name':'',
                         'Quantity':100,'Returned quantity':0,'Total Buyer Payment':10000}.items(): tx[col]=val
        txs.append(tx)
        stock=st0.iloc[:1].copy(); stock['SKU']=sku; stock['product_key']=key
        stocks.append(stock)
        fc=fc0['forecast_output'].query("SKU == 'SKU-A'").copy()
        fc['SKU']=sku; fc['Product']=product; forecasts.append(fc)
        requests.append({'Return ID':f'SYNTH-R{i}','Order ID':order,'Product Name':product,
            'Variation Name':'','product_key':key,'Return Creation Time':'2026-09-02',
            'Return / Refund Status':'Request Refunded','Return Quantity':(i+1)*5,
            'Return/Refund Solution':'Refund Only','Refund Completed Time':''})
    tx=pd.concat(txs,ignore_index=True); stock=pd.concat(stocks,ignore_index=True)
    forecasts={'forecast_output':pd.concat(forecasts,ignore_index=True)}
    analytics={'sales_velocity':pd.DataFrame({'Product Key':[f'SYNTH-P{i}' for i in range(8)],'Sales Velocity':[10.]*8})}
    cov=Coverage('2026-09-01','2026-09-02','2026-09-01','2026-09-02','2026-10-15','2026-10-16',True)
    with tempfile.TemporaryDirectory(prefix='tesph_synthetic_') as tmp:
        db=Path(tmp)/'review.db'
        result=refresh_connected(tx,analytics,forecasts,stock,snapshot=pd.DataFrame(requests),
            coverage=cov,batch_type='return_refund',store_path=db,as_of='2026-09-28')
        ranked=result['mca_results'].sort_values(RATE).reset_index(drop=True)
        rates=np.arange(5,41,5,dtype=float)
        expected=(40-rates)/35
        np.testing.assert_allclose(ranked[RATE],rates)
        np.testing.assert_allclose(ranked['Normalized '+RATE],expected)
        np.testing.assert_allclose(ranked['SKU Priority Score'],(1+expected)/3)
        assert ranked['SKU Priority Score'].is_monotonic_decreasing
        with sqlite3.connect(db) as con:
            persisted=json.loads(con.execute("SELECT payload FROM state WHERE name='outputs'").fetchone()[0])
            saved=pd.read_json(io.StringIO(persisted['mca_results']),orient='table')
            assert con.execute('SELECT COUNT(*) FROM audit').fetchone()[0]==8
        con.close()
        pd.testing.assert_frame_equal(saved,result['mca_results'],check_dtype=False,atol=1e-14,rtol=1e-14)
        repeat=refresh_connected(tx,analytics,forecasts,stock,batch_type='stock',store_path=db,as_of='2026-09-28')
        pd.testing.assert_frame_equal(repeat['mca_results'],result['mca_results'])
        app=AppTest.from_file(ROOT/'pages/product_prioritization.py',default_timeout=30)
        for key,value in {**DEFAULT_STATE,'authenticated':True,'_runtime_authority_loaded':True,
            'data_status':DataStatus.DATA_READY.value,'active_dataset_id':'synthetic',
            'forecast_dataset_id':'synthetic','analytics_dataset_id':'synthetic',
            'analytics_results':analytics,'forecast_results':forecasts,**result}.items(): app.session_state[key]=value
        from streamlit.runtime.memory_media_file_storage import MemoryMediaFileStorage
        storage = MemoryMediaFileStorage("/mock/media")
        with patch("streamlit.testing.v1.app_test.MemoryMediaFileStorage", return_value=storage):
            app.run()
        assert not app.exception
        shown=next(t.value for t in app.dataframe if 'SKU Priority Score' in t.value)
        pd.testing.assert_frame_equal(shown,result['mca_results'])
        # Verify actual download-button payload stored by Streamlit's media manager.
        buttons=app.get('download_button')
        ranking_button=next(b for b in buttons if b.label=='Download MCA rankings')
        url=ranking_button.proto.url
        file_id=url.rsplit('/',1)[-1].split('.')[0]
        media=storage.get_file(file_id)
        downloaded=pd.read_csv(io.BytesIO(media.content))
        pd.testing.assert_frame_equal(downloaded,result['mca_results'],check_dtype=False)
        gc.collect()
    ranked.to_csv(output/'synthetic_rankings.csv',index=False)
    summary={'data_type':'SYNTHETIC ONLY — not empirical Chapter 4 results','skus':8,
        'rates_percent':rates.tolist(),'expected_cost_normalization':'(40-rate)/35',
        'expected_score':'(0.5+0.5+normalized_return_rate)/3',
        'checks':['connected pipeline','independent hand formula','SQLite persisted outputs',
                  '8 audit events','repeat stock refresh','production page AppTest','actual CSV download payload'],
        'status':'passed','scope':'Local staging component flow; merged frontend/demo acceptance still required'}
    (output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    return summary

if __name__=='__main__':
    print(json.dumps(run(ROOT/'validation_outputs/synthetic_mca'),indent=2))
