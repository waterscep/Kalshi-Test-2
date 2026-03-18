"""Tests for cross-strike arbitrage detection."""

from kalshi_bot.strategy.cross_strike_arb import BracketQuote, find_arbitrage


class TestFindArbitrage:
    def test_buy_all_arb(self):
        """Detect arb when total ask < 100 (buy all brackets profitably)."""
        brackets = [
            BracketQuote(ticker="T1", yes_bid=10, yes_ask=15),
            BracketQuote(ticker="T2", yes_bid=20, yes_ask=25),
            BracketQuote(ticker="T3", yes_bid=30, yes_ask=35),
            BracketQuote(ticker="T4", yes_bid=10, yes_ask=15),
        ]
        # Total ask = 15 + 25 + 35 + 15 = 90 < 98 → arb!
        arb = find_arbitrage(brackets)
        assert arb is not None
        assert arb.direction == "buy_all_yes"
        assert arb.profit_cents == 10  # 100 - 90
        assert len(arb.trades) == 4

    def test_sell_all_arb(self):
        """Detect arb when total bid > 100 (sell all brackets profitably)."""
        brackets = [
            BracketQuote(ticker="T1", yes_bid=30, yes_ask=35),
            BracketQuote(ticker="T2", yes_bid=35, yes_ask=40),
            BracketQuote(ticker="T3", yes_bid=25, yes_ask=30),
            BracketQuote(ticker="T4", yes_bid=15, yes_ask=20),
        ]
        # Total bid = 30 + 35 + 25 + 15 = 105 > 102 → arb!
        arb = find_arbitrage(brackets)
        assert arb is not None
        assert arb.direction == "sell_all_yes"
        assert arb.profit_cents == 5  # 105 - 100

    def test_no_arb_efficient_market(self):
        """No arb when prices are reasonable."""
        brackets = [
            BracketQuote(ticker="T1", yes_bid=15, yes_ask=20),
            BracketQuote(ticker="T2", yes_bid=25, yes_ask=30),
            BracketQuote(ticker="T3", yes_bid=30, yes_ask=35),
            BracketQuote(ticker="T4", yes_bid=20, yes_ask=25),
        ]
        # Total ask = 110, total bid = 90 → no arb
        arb = find_arbitrage(brackets)
        assert arb is None

    def test_single_bracket_no_arb(self):
        """Single bracket can't be arbed."""
        brackets = [BracketQuote(ticker="T1", yes_bid=50, yes_ask=55)]
        arb = find_arbitrage(brackets)
        assert arb is None

    def test_arb_respects_buffer(self):
        """Total ask of 97 is arb (< 98), but 99 is not."""
        brackets = [
            BracketQuote(ticker="T1", yes_bid=30, yes_ask=48),
            BracketQuote(ticker="T2", yes_bid=45, yes_ask=51),
        ]
        # Total ask = 99 → NOT arb (need < 98)
        arb = find_arbitrage(brackets)
        assert arb is None
