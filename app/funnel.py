"""Funnel metrics from the GA4 export: conversion per step, data-quality flags, biggest leak.

Every number the app shows or sends to the LLM is computed here.
"""

from pathlib import Path

import pandas as pd

from app import stats

STEPS = [
    "visitors",
    "viewed_product",
    "added_to_cart",
    "began_checkout",
    "added_payment",
    "purchased",
]
SEGMENTS = ["device", "medium"]
# GA4 anonymisation buckets: kept in totals, never reported as "the" leaky segment.
UNKNOWN_MEDIUMS = {"(data deleted)", "<Other>"}
MIN_SEGMENT_USERS = 500  # segments with fewer users at the leaky step are too noisy to name
MAX_TEST_DAYS = 28  # a leak is "testable" if its A/B test can finish within this many days

DEFAULT_CSV = Path(__file__).resolve().parent.parent / "data" / "funnel.csv"


def load(path=DEFAULT_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    missing = set(STEPS + SEGMENTS) - set(df.columns)
    if missing:
        raise ValueError(f"CSV is missing columns: {sorted(missing)}")
    return df


def make_strict(df: pd.DataFrame) -> pd.DataFrame:
    """Cap each step at the previous one, row by row, so the funnel never goes up."""
    strict = df.copy()
    strict[STEPS] = strict[STEPS].cummin(axis=1)
    return strict


def quality_flags(df: pd.DataFrame) -> list[dict]:
    """One flag per step that exceeds the previous step on any row."""
    flags = []
    for prev, step in zip(STEPS, STEPS[1:]):
        bad = df[df[step] > df[prev]]
        if bad.empty:
            continue
        flags.append({
            "step": step,
            "previous_step": prev,
            "rows_affected": len(bad),
            "share_of_rows": round(len(bad) / len(df), 3),
            "excess_users": int((bad[step] - bad[prev]).sum()),
        })
    return flags


def conversion(df: pd.DataFrame, by: str | None = None) -> pd.DataFrame:
    """Users and step-to-step conversion per step, overall or per segment.

    Returns one row per (segment, step) with: users, conversion from the previous
    step, conversion from visitors, and users lost at this step.
    """
    groups = df.groupby(by)[STEPS].sum() if by else df[STEPS].sum().to_frame("all").T
    rows = []
    for segment, totals in groups.iterrows():
        for i, step in enumerate(STEPS):
            users = int(totals[step])
            prev = int(totals[STEPS[i - 1]]) if i else users
            rows.append({
                "segment": segment,
                "step": step,
                "users": users,
                "step_conversion": users / prev if prev else 0.0,
                "overall_conversion": users / totals["visitors"] if totals["visitors"] else 0.0,
                "lost": prev - users,
            })
    out = pd.DataFrame(rows)
    if by:
        out.insert(0, "dimension", by)
    return out


def segment_leaks(df: pd.DataFrame, mde: float = 0.10) -> pd.DataFrame:
    """Every step × segment that converts below the overall step rate, with its test run time.

    `lost_vs_overall` is the number of users the segment loses beyond what the overall
    rate would lose: entered × (overall rate − segment rate). It is the size of the leak.
    """
    overall = conversion(df).set_index("step")["step_conversion"]
    days = df["date"].nunique()
    frames = []
    for dim in SEGMENTS:
        seg = conversion(df, by=dim)
        seg = seg[seg["step"] != STEPS[0]].copy()
        seg["entered"] = seg["users"] + seg["lost"]
        seg = seg[seg["entered"] >= MIN_SEGMENT_USERS]
        if dim == "medium":
            seg = seg[~seg["segment"].isin(UNKNOWN_MEDIUMS)]
        frames.append(seg)
    out = pd.concat(frames, ignore_index=True)
    out["overall_step_conversion"] = out["step"].map(overall)
    out["lost_vs_overall"] = out["entered"] * (out["overall_step_conversion"] - out["step_conversion"])
    out["run_time_days"] = pd.to_numeric(
        [_run_time(r.step_conversion, mde, r.entered / days) for r in out.itertuples()]
    )
    return out


def _run_time(baseline: float, mde: float, daily: float) -> int | None:
    try:
        return stats.experiment_numbers(baseline, mde, daily)["run_time_days"]
    except ValueError:  # baseline 0 or 1, or the target rate would exceed 100%
        return None


def _leak(df: pd.DataFrame, seg: pd.Series) -> dict:
    """A leak as JSON: the step overall plus one segment of it."""
    overall = conversion(df).set_index("step").loc[seg["step"]]
    rate = float(overall["step_conversion"])
    seg_rate = float(seg["step_conversion"])
    return {
        "step": seg["step"],
        "from_step": STEPS[STEPS.index(seg["step"]) - 1],
        "users_entering": int(overall["users"] + overall["lost"]),
        "users_lost": int(overall["lost"]),
        "step_conversion": round(rate, 4),
        "worst_segment": {
            "dimension": seg["dimension"],
            "value": seg["segment"],
            "users_entering": int(seg["entered"]),
            "step_conversion": round(seg_rate, 4),
            "gap_vs_overall_pp": round((seg_rate - rate) * 100, 1),
            "users_lost_vs_overall": round(float(seg["lost_vs_overall"])),
            "test_run_time_days": None if pd.isna(seg["run_time_days"]) else int(seg["run_time_days"]),
        },
    }


def biggest_leak(df: pd.DataFrame, mde: float = 0.10) -> dict:
    """The step with the largest absolute drop, and the segment where that step converts worst."""
    overall = conversion(df)
    step = overall.iloc[1:].sort_values("lost", ascending=False).iloc[0]["step"]
    segs = segment_leaks(df, mde)
    worst = segs[segs["step"] == step].sort_values("step_conversion").iloc[0]
    return _leak(df, worst)


def testable_leak(df: pd.DataFrame, mde: float = 0.10, max_days: int = MAX_TEST_DAYS) -> dict | None:
    """The step × segment losing the most users vs. the overall rate whose test fits in `max_days`."""
    segs = segment_leaks(df, mde)
    ok = segs[(segs["lost_vs_overall"] > 0) & (segs["run_time_days"] <= max_days)]
    if ok.empty:
        return None
    return _leak(df, ok.sort_values("lost_vs_overall", ascending=False).iloc[0])


def summary(df: pd.DataFrame, strict: bool = False, mde: float = 0.10) -> dict:
    """Everything the LLM chain needs, as plain JSON-able values."""
    flags = quality_flags(df)
    data = make_strict(df) if strict else df
    overall = conversion(data)
    days = df["date"].nunique()
    return {
        "view": "strict" if strict else "raw",
        "date_range": [df["date"].min().date().isoformat(), df["date"].max().date().isoformat()],
        "days": days,
        "funnel": [
            {
                "step": r.step,
                "users": r.users,
                "step_conversion": round(r.step_conversion, 4),
                "overall_conversion": round(r.overall_conversion, 4),
            }
            for r in overall.itertuples()
        ],
        "biggest_leak": biggest_leak(data, mde),
        "testable_leak": testable_leak(data, mde),
        "max_test_days": MAX_TEST_DAYS,
        "mde_relative": mde,
        "daily_visitors": round(int(df["visitors"].sum()) / days),
        "data_quality_flags": flags,
    }
