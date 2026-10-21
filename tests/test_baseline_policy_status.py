import pandas as pd
from three_criterion_mca import RATE, SCENARIOS, rank_scenarios


def test_approved_baseline_is_distinct_from_pending_validation_and_comparison():
    data = pd.DataFrame({'SKU':['A','B'], 'Sales Velocity':[1,2],
                         'Forecasted Demand':[3,1], RATE:[0,10]})
    scenarios, _, summary = rank_scenarios(data)
    assert all(w == 1/3 for w in SCENARIOS['equal_thirds'].values())
    assert summary['approved_baseline'] == 'equal_thirds'
    assert summary['final_weights_locked'] is True
    assert summary['final_validation_pending'] is True
    assert scenarios['equal_thirds']['Approval Status'].str.contains('TA-approved').all()
    assert scenarios['volume_quality']['Approval Status'].str.contains('not the approved baseline').all()
