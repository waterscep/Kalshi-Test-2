"""Tests for risk management."""

from datetime import datetime, timedelta, timezone

from kalshi_bot.api.models import Market, OrderAction, OrderSide, ProposedOrder
from kalshi_bot.config.settings import Settings
from kalshi_bot.risk.manager import RiskDecision, RiskManager


def _make_settings(**overrides) -> Settings:
    defaults = dict(
        kalshi_api_key_id="test",
        kalshi_private_key_path="test.pem",
        max_position_per_market=100,
        max_total_exposure=5000,
        max_daily_loss=500,
        max_event_concentration=0.30,
        min_balance_reserve=200,
        min_hours_to_close=1,
    )
    defaults.update(overrides)
    return Settings(**defaults)


def _make_order(ticker="TEST-T1", count=10, price=50) -> ProposedOrder:
    return ProposedOrder(
        ticker=ticker,
        side=OrderSide.YES,
        action=OrderAction.BUY,
        price_cents=price,
        count=count,
    )


def _make_market(status="open", hours_to_close=5) -> Market:
    close_time = datetime.now(timezone.utc) + timedelta(hours=hours_to_close)
    return Market(ticker="TEST-T1", status=status, close_time=close_time)


class TestRiskManager:
    def test_allows_normal_order(self):
        rm = RiskManager(_make_settings())
        result = rm.check_order(
            order=_make_order(),
            market=_make_market(),
            current_position=0,
            total_exposure_cents=0,
            balance_cents=100_000,
        )
        assert result.decision == RiskDecision.ALLOW

    def test_rejects_closed_market(self):
        rm = RiskManager(_make_settings())
        result = rm.check_order(
            order=_make_order(),
            market=_make_market(status="closed"),
            current_position=0,
            total_exposure_cents=0,
            balance_cents=100_000,
        )
        assert result.decision == RiskDecision.REJECT
        assert "not open" in result.reason

    def test_rejects_near_close(self):
        rm = RiskManager(_make_settings(min_hours_to_close=2))
        result = rm.check_order(
            order=_make_order(),
            market=_make_market(hours_to_close=1),
            current_position=0,
            total_exposure_cents=0,
            balance_cents=100_000,
        )
        assert result.decision == RiskDecision.REJECT
        assert "close" in result.reason

    def test_reduces_at_position_limit(self):
        rm = RiskManager(_make_settings(max_position_per_market=50))
        result = rm.check_order(
            order=_make_order(count=20),
            market=_make_market(),
            current_position=40,  # 40 + 20 = 60 > 50
            total_exposure_cents=0,
            balance_cents=100_000,
        )
        assert result.decision == RiskDecision.REDUCE
        assert result.adjusted_count == 10  # 50 - 40

    def test_rejects_when_fully_at_limit(self):
        rm = RiskManager(_make_settings(max_position_per_market=50))
        result = rm.check_order(
            order=_make_order(count=10),
            market=_make_market(),
            current_position=50,
            total_exposure_cents=0,
            balance_cents=100_000,
        )
        assert result.decision == RiskDecision.REJECT

    def test_rejects_excessive_exposure(self):
        rm = RiskManager(_make_settings(max_total_exposure=1000))
        result = rm.check_order(
            order=_make_order(count=50, price=50),  # 50 * 50 = 2500¢ = $25
            market=_make_market(),
            current_position=0,
            total_exposure_cents=99_000,  # already at $990
            balance_cents=100_000,
        )
        assert result.decision == RiskDecision.REJECT
        assert "exposure" in result.reason

    def test_rejects_insufficient_balance(self):
        rm = RiskManager(_make_settings(min_balance_reserve=200))
        result = rm.check_order(
            order=_make_order(count=10, price=50),  # costs 500¢
            market=_make_market(),
            current_position=0,
            total_exposure_cents=0,
            balance_cents=20_500,  # 20500 - 500 = 20000 = $200 reserve exactly
        )
        # 20500 - 500 = 20000 = 200*100 → NOT less than reserve
        assert result.decision == RiskDecision.ALLOW

    def test_rejects_below_reserve(self):
        rm = RiskManager(_make_settings(min_balance_reserve=200))
        result = rm.check_order(
            order=_make_order(count=10, price=50),
            market=_make_market(),
            current_position=0,
            total_exposure_cents=0,
            balance_cents=20_400,  # 20400 - 500 = 19900 < 20000 reserve
        )
        assert result.decision == RiskDecision.REJECT

    def test_daily_loss_halts_trading(self):
        rm = RiskManager(_make_settings(max_daily_loss=100))
        # Simulate losing $100
        rm.record_fill(-10_000)  # -$100 in cents
        result = rm.check_order(
            order=_make_order(),
            market=_make_market(),
            current_position=0,
            total_exposure_cents=0,
            balance_cents=100_000,
        )
        assert result.decision == RiskDecision.REJECT
        assert "halted" in result.reason

    def test_daily_reset(self):
        rm = RiskManager(_make_settings(max_daily_loss=100))
        rm.record_fill(-10_000)
        assert rm._trading_halted
        rm.reset_daily()
        assert not rm._trading_halted
