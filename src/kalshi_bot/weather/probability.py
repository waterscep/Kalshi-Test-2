"""Convert ensemble forecasts into bracket probabilities — the core edge."""

from __future__ import annotations

import numpy as np
from scipy.stats import norm


def bracket_probability(
    ensemble_values: list[float],
    low: float | None,
    high: float | None,
) -> float:
    """Compute P(low <= observation < high) from ensemble distribution.

    Uses a blend of empirical counting and fitted normal CDF.
    The blend weights empirical more heavily when enough ensemble members
    fall in the bracket, and falls back to the fitted distribution for
    thin-tail brackets where empirical counts are noisy.

    Args:
        ensemble_values: One forecast value per ensemble member (°F or inches).
        low: Lower bound of bracket. None means -infinity (below-range bracket).
        high: Upper bound of bracket. None means +infinity (above-range bracket).

    Returns:
        Probability estimate in [0, 1].
    """
    if not ensemble_values:
        return 0.0

    n = len(ensemble_values)
    arr = np.array(ensemble_values)

    # --- Empirical probability ---
    if low is None and high is not None:
        in_bracket = np.sum(arr < high)
    elif low is not None and high is None:
        in_bracket = np.sum(arr >= low)
    elif low is not None and high is not None:
        in_bracket = np.sum((arr >= low) & (arr < high))
    else:
        return 1.0  # no bounds → certainty

    empirical_prob = float(in_bracket) / n

    # --- Fitted normal probability ---
    mu = float(np.mean(arr))
    sigma = float(np.std(arr, ddof=1)) if n > 1 else 0.5
    sigma = max(sigma, 0.5)  # floor to avoid degenerate distributions

    if low is None:
        fitted_prob = float(norm.cdf(high, mu, sigma))
    elif high is None:
        fitted_prob = 1.0 - float(norm.cdf(low, mu, sigma))
    else:
        fitted_prob = float(norm.cdf(high, mu, sigma) - norm.cdf(low, mu, sigma))

    # --- Blend ---
    # Trust empirical when we have >= 5 members in the bracket;
    # otherwise lean on the fitted distribution (better for tail events).
    empirical_weight = min(float(in_bracket) / 5.0, 1.0)
    blended = empirical_weight * empirical_prob + (1 - empirical_weight) * fitted_prob

    return max(0.0, min(1.0, blended))


def compute_all_bracket_probabilities(
    ensemble_values: list[float],
    brackets: list[tuple[float | None, float | None]],
) -> list[float]:
    """Compute probabilities for all brackets in an event, normalized to sum to 1.

    Args:
        ensemble_values: One value per ensemble member.
        brackets: List of (low, high) tuples. None means unbounded edge.

    Returns:
        List of probabilities, same length as brackets, summing to 1.0.
    """
    if not ensemble_values:
        n = len(brackets)
        return [1.0 / n] * n if n > 0 else []

    raw = [bracket_probability(ensemble_values, low, high) for low, high in brackets]

    total = sum(raw)
    if total <= 0:
        n = len(brackets)
        return [1.0 / n] * n

    # Normalize to sum to 1
    return [p / total for p in raw]
