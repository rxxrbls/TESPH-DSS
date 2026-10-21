from qa.synthetic_mca_staging import run


def test_eight_sku_synthetic_staging(tmp_path):
    assert run(tmp_path)['status'] == 'passed'
