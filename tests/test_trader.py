"""Tests for Kelly criterion position sizing."""

from kalshi_bot.strategy.sizing import kelly_contracts, kelly_contracts_sell


class TestKellyContracts:
    def test_positive_edge_produces_contracts(self):
        """When model > market, should produce > 0 contracts."""
        count = kelly_contracts(
            model_prob=0.80,
            market_price_cents=60,
            bankroll_cents=100_000,  # $1000
        )
        assert count > 0

    def test_no_edge_produces_zero(self):
        """When model <= market, should produce 0 contracts."""
        count = kelly_contracts(
            model_prob=0.50,
            market_price_cents=55,
            bankroll_cents=100_000,
        )
        assert count == 0

    def test_larger_edge_produces_more_contracts(self):
        """More edge → more contracts."""
        small = kelly_contracts(0.60, 50, 100_000)
        large = kelly_contracts(0.80, 50, 100_000)
        assert large > small

    def test_respects_max_contracts(self):
        """Should cap at max_contracts."""
        count = kelly_contracts(
            model_prob=0.99,
            market_price_cents=10,
            bankroll_cents=10_000_000,
            max_contracts=50,
        )
        assert count <= 50

    def test_zero_bankroll(self):
        count = kelly_contracts(0.80, 60, 0)
        assert count == 0

    def test_quarter_kelly_is_conservative(self):
        """Quarter Kelly should produce ~4x fewer contracts than full Kelly."""
        full = kelly_contracts(0.70, 50, 10_000, fraction=1.0, max_contracts=1000)
        quarter = kelly_contracts(0.70, 50, 10_000, fraction=0.25, max_contracts=1000)
        assert quarter < full
        # Quarter Kelly should be roughly 1/4 of full Kelly
        if full > 0:
            assert 0.15 < quarter / full < 0.35


class TestKellyContractsSell:
    def test_positive_sell_edge(self):
        """When model < market (YES overpriced), should sell contracts."""
        count = kelly_contracts_sell(
            model_prob=0.30,
            market_price_cents=50,
            bankroll_cents=100_000,
        )
        assert count > 0

    def test_no_sell_edge(self):
        """When model >= market, selling has no edge."""
        count = kelly_contracts_sell(
            model_prob=0.60,
            market_price_cents=50,
            bankroll_cents=100_000,
        )
        assert count == 0
