import pytest

from app import stats


def test_sample_size_matches_textbook_value():
    # 20% -> 22%, alpha 0.05, power 0.8: ~6,510 per variant (pooled-variance formula)
    assert stats.sample_size_per_variant(0.20, 0.10) == 6510


def test_run_time_rounds_up():
    assert stats.run_time_days(6510, 1000) == 14


def test_sample_size_rejects_impossible_target():
    with pytest.raises(ValueError):
        stats.sample_size_per_variant(0.95, 0.10)
