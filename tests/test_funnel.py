import io

import pytest

from app import funnel

CSV = """date,device,medium,visitors,viewed_product,added_to_cart,began_checkout,added_payment,purchased
2020-11-01,mobile,organic,1000,200,20,30,10,5
2020-11-01,desktop,organic,1000,400,100,60,40,30
"""


def sample():
    return funnel.load(io.StringIO(CSV))


def test_quality_flags_find_non_monotonic_step():
    flags = funnel.quality_flags(sample())
    assert [(f["step"], f["rows_affected"], f["excess_users"]) for f in flags] == [("began_checkout", 1, 10)]


def test_strict_caps_each_step_at_previous():
    strict = funnel.make_strict(sample())
    assert strict.loc[0, "began_checkout"] == 20
    assert strict.loc[0, "added_payment"] == 10
    assert funnel.quality_flags(strict) == []


def test_conversion_overall():
    overall = funnel.conversion(sample()).set_index("step")
    assert overall.loc["viewed_product", "users"] == 600
    assert overall.loc["viewed_product", "step_conversion"] == pytest.approx(0.3)
    assert overall.loc["viewed_product", "lost"] == 1400


def test_biggest_leak_and_worst_segment():
    leak = funnel.biggest_leak(sample())
    assert leak["step"] == "viewed_product"
    assert leak["users_lost"] == 1400
    seg = leak["worst_segment"]
    assert seg["value"] == "mobile"
    assert seg["step_conversion"] == pytest.approx(0.2)
    assert seg["users_lost_vs_overall"] == 100  # 1000 × (0.3 − 0.2)


def test_testable_leak_respects_max_days():
    # 1 day of data and 1,000 mobile visitors/day: the 20% -> 22% test needs ~13 days
    leak = funnel.testable_leak(sample(), mde=0.10, max_days=28)
    assert leak["worst_segment"]["value"] == "mobile"
    assert leak["worst_segment"]["test_run_time_days"] <= 28
    assert funnel.testable_leak(sample(), mde=0.10, max_days=5) is None


def test_ga4_sample_testable_leak_differs_from_biggest():
    # On the GA4 sample the worst segment of the biggest leak (cpc) needs > 28 days.
    m = funnel.summary(funnel.load())
    assert m["biggest_leak"]["worst_segment"]["test_run_time_days"] > 28
    assert m["testable_leak"]["worst_segment"]["test_run_time_days"] <= 28
