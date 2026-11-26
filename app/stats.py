"""Sample size and run time for a two-proportion A/B test. No LLM involved."""

import math
from statistics import NormalDist


def sample_size_per_variant(
    baseline: float, mde_relative: float, alpha: float = 0.05, power: float = 0.8
) -> int:
    """Users needed in each variant to detect a relative lift of `mde_relative`.

    Two-sided test of two proportions (normal approximation, pooled variance under H0).
    Example: baseline 0.20, mde_relative 0.10 means detecting 20% -> 22%.
    """
    if not 0 < baseline < 1:
        raise ValueError("baseline must be between 0 and 1")
    p1 = baseline
    p2 = baseline * (1 + mde_relative)
    if not 0 < p2 < 1 or p1 == p2:
        raise ValueError("baseline × (1 + MDE) must be between 0 and 1 and differ from baseline")

    z_alpha = NormalDist().inv_cdf(1 - alpha / 2)
    z_beta = NormalDist().inv_cdf(power)
    p_bar = (p1 + p2) / 2
    numerator = (
        z_alpha * math.sqrt(2 * p_bar * (1 - p_bar))
        + z_beta * math.sqrt(p1 * (1 - p1) + p2 * (1 - p2))
    ) ** 2
    return math.ceil(numerator / (p2 - p1) ** 2)


def run_time_days(n_per_variant: int, daily_users: float, variants: int = 2) -> int:
    """Days until every variant has `n_per_variant` users, if all `daily_users` enter the test."""
    if daily_users <= 0:
        raise ValueError("daily_users must be positive")
    return math.ceil(n_per_variant * variants / daily_users)


def experiment_numbers(
    baseline: float, mde_relative: float, daily_users: float, alpha: float = 0.05, power: float = 0.8
) -> dict:
    n = sample_size_per_variant(baseline, mde_relative, alpha, power)
    return {
        "baseline_rate": round(baseline, 4),
        "mde_relative": mde_relative,
        "target_rate": round(baseline * (1 + mde_relative), 4),
        "alpha": alpha,
        "power": power,
        "sample_size_per_variant": n,
        "daily_users_at_step": round(daily_users),
        "run_time_days": run_time_days(n, daily_users),
    }
