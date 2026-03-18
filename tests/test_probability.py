"""Tests for the weather probability engine — the core edge."""

import pytest

from kalshi_bot.weather.probability import (
    bracket_probability,
    compute_all_bracket_probabilities,
)


class TestBracketProbability:
    """Test ensemble → probability conversion."""

    def test_all_members_in_bracket(self):
        """If all ensemble members are in the bracket, probability ≈ 1."""
        values = [70.0, 71.0, 72.0, 73.0, 74.0] * 6  # 30 members, all in [65, 80)
        prob = bracket_probability(values, 65.0, 80.0)
        assert prob > 0.95

    def test_no_members_in_bracket(self):
        """If no ensemble members are in the bracket, probability ≈ 0."""
        values = [90.0, 91.0, 92.0, 93.0, 94.0] * 6
        prob = bracket_probability(values, 60.0, 65.0)
        assert prob < 0.05

    def test_half_members_in_bracket(self):
        """If roughly half are in bracket, probability ≈ 0.5."""
        values = list(range(60, 80))  # 60, 61, ..., 79
        prob = bracket_probability(values, 70.0, 80.0)
        assert 0.35 < prob < 0.65

    def test_unbounded_below(self):
        """Test below-range bracket (low=None)."""
        values = [30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0]
        prob = bracket_probability(values, None, 40.0)
        # 2 of 7 members below 40 = 28.6% empirical
        assert 0.1 < prob < 0.5

    def test_unbounded_above(self):
        """Test above-range bracket (high=None)."""
        values = [30.0, 35.0, 40.0, 45.0, 50.0, 55.0, 60.0]
        prob = bracket_probability(values, 50.0, None)
        # 3 of 7 members >= 50 = 42.9% empirical
        assert 0.2 < prob < 0.7

    def test_both_unbounded(self):
        """Both bounds None → probability = 1."""
        prob = bracket_probability([50.0, 60.0], None, None)
        assert prob == 1.0

    def test_empty_ensemble(self):
        """Empty ensemble → probability = 0."""
        prob = bracket_probability([], 50.0, 60.0)
        assert prob == 0.0

    def test_narrow_bracket_uses_fitted(self):
        """Narrow bracket with few members should still give reasonable probability."""
        # Normal-ish distribution centered at 70, narrow bracket at 70-71
        values = [68.0, 69.0, 69.5, 70.0, 70.5, 71.0, 71.5, 72.0]
        prob = bracket_probability(values, 70.0, 71.0)
        # Should be reasonable (not 0 or 1)
        assert 0.05 < prob < 0.5


class TestAllBracketProbabilities:
    """Test that bracket probabilities are normalized correctly."""

    def test_probabilities_sum_to_one(self):
        """All bracket probabilities should sum to 1.0."""
        values = [65.0, 67.0, 69.0, 71.0, 73.0, 75.0] * 5
        brackets = [
            (None, 66.0),   # below 66
            (66.0, 68.0),
            (68.0, 70.0),
            (70.0, 72.0),
            (72.0, 74.0),
            (74.0, None),   # above 74
        ]
        probs = compute_all_bracket_probabilities(values, brackets)
        assert len(probs) == 6
        assert abs(sum(probs) - 1.0) < 1e-10

    def test_peak_bracket_has_highest_probability(self):
        """The bracket containing the ensemble mean should have highest prob."""
        # Tight distribution around 70°F
        values = [69.0, 69.5, 70.0, 70.5, 71.0] * 6
        brackets = [
            (None, 68.0),
            (68.0, 70.0),
            (70.0, 72.0),  # should be highest
            (72.0, 74.0),
            (74.0, None),
        ]
        probs = compute_all_bracket_probabilities(values, brackets)
        # Bracket [70, 72) should have highest probability
        assert probs[2] == max(probs)

    def test_empty_ensemble_uniform(self):
        """Empty ensemble should return uniform distribution."""
        probs = compute_all_bracket_probabilities([], [(60.0, 70.0), (70.0, 80.0)])
        assert probs == [0.5, 0.5]

    def test_single_member(self):
        """Single ensemble member: bracket containing it gets most probability."""
        probs = compute_all_bracket_probabilities(
            [72.0],
            [(None, 70.0), (70.0, 74.0), (74.0, None)],
        )
        assert probs[1] > probs[0]
        assert probs[1] > probs[2]
