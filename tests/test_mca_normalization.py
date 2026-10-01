from src.prescriptive.mca import min_max_normalize


# KAN-265 - VALIDATE TA-APPROVED MIN-MAX NORMALIZATION


def test_benefit_normalization():
    result = min_max_normalize(
        value=60,
        min_value=20,
        max_value=100,
        direction="benefit",
    )

    assert result == 0.5


def test_cost_normalization():
    result = min_max_normalize(
        value=60,
        min_value=20,
        max_value=100,
        direction="cost",
    )

    assert result == 0.5


def test_benefit_minimum():
    result = min_max_normalize(
        value=20,
        min_value=20,
        max_value=100,
        direction="benefit",
    )

    assert result == 0.0


def test_benefit_maximum():
    result = min_max_normalize(
        value=100,
        min_value=20,
        max_value=100,
        direction="benefit",
    )

    assert result == 1.0


def test_cost_minimum():
    result = min_max_normalize(
        value=20,
        min_value=20,
        max_value=100,
        direction="cost",
    )

    assert result == 1.0


def test_cost_maximum():
    result = min_max_normalize(
        value=100,
        min_value=20,
        max_value=100,
        direction="cost",
    )

    assert result == 0.0


def test_equal_min_max():
    result = min_max_normalize(
        value=50,
        min_value=50,
        max_value=50,
        direction="benefit",
    )

    assert result == 0.5