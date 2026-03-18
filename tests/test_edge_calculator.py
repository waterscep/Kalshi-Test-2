"""Tests for edge detection logic."""

from kalshi_bot.strategy.edge_calculator import (
    apply_flb_adjustment,
    compute_edge,
    find_edges,
)


class TestComputeEdge:
    def test_buy_edge_when_model_higher(self):
        """Model says 83%, market says 74% → buy YES edge of 9¢."""
        edge, side = compute_edge(0.83, 74)
        assert side == "buy_yes"
        assert abs(edge - 9.0) < 0.1

    def test_sell_edge_when_model_lower(self):
        """Model says 30%, market says 45% → sell YES edge of 15¢."""
        edge, side = compute_edge(0.30, 45)
        assert side == "sell_yes"
        assert abs(edge - 15.0) < 0.1

    def test_no_edge_when_equal(self):
        """Model matches market → zero edge."""
        edge, _ = compute_edge(0.50, 50)
        assert abs(edge) < 0.1

    def test_small_buy_edge(self):
        edge, side = compute_edge(0.55, 52)
        assert side == "buy_yes"
        assert abs(edge - 3.0) < 0.1


class TestFLBAdjustment:
    def test_favorite_gets_bonus(self):
        """Contracts > 80¢ get bonus edge (favorites are underpriced)."""
        adjusted = apply_flb_adjustment(5.0, 85, favorite_bonus=1)
        assert adjusted == 6.0

    def test_longshot_gets_bonus_for_selling(self):
        """Contracts < 20¢ get bonus edge (longshots are overpriced)."""
        adjusted = apply_flb_adjustment(5.0, 15, longshot_penalty=1)
        assert adjusted == 6.0

    def test_midrange_no_adjustment(self):
        """Contracts 20-80¢ get no FLB adjustment."""
        adjusted = apply_flb_adjustment(5.0, 50)
        assert adjusted == 5.0


class TestFindEdges:
    def test_finds_obvious_edge(self):
        """Should find edge when model strongly disagrees with market."""
        probs = [0.05, 0.10, 0.50, 0.25, 0.10]
        tickers = ["T1", "T2", "T3", "T4", "T5"]
        prices = [5, 10, 35, 25, 10]  # T3 is 50% model vs 35¢ market

        signals = find_edges(probs, tickers, prices, min_edge_cents=3)
        assert len(signals) > 0
        # T3 should be the top signal (15¢ edge)
        assert signals[0].ticker == "T3"
        assert signals[0].side == "buy_yes"
        assert signals[0].edge_cents > 10

    def test_no_edge_when_market_is_efficient(self):
        """No signals when model matches market."""
        probs = [0.10, 0.20, 0.40, 0.20, 0.10]
        tickers = ["T1", "T2", "T3", "T4", "T5"]
        prices = [10, 20, 40, 20, 10]

        signals = find_edges(probs, tickers, prices, min_edge_cents=3)
        assert len(signals) == 0

    def test_respects_min_edge_threshold(self):
        """Should filter out small edges below threshold."""
        probs = [0.52]
        tickers = ["T1"]
        prices = [50]  # 2¢ edge

        signals = find_edges(probs, tickers, prices, min_edge_cents=3)
        assert len(signals) == 0

    def test_sorted_by_edge_descending(self):
        """Signals should be sorted by edge size, best first."""
        probs = [0.60, 0.80]
        tickers = ["T1", "T2"]
        prices = [40, 50]  # T1: 20¢ edge, T2: 30¢ edge

        signals = find_edges(probs, tickers, prices, min_edge_cents=3)
        assert len(signals) == 2
        assert signals[0].edge_cents >= signals[1].edge_cents
