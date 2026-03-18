"""Pre-trade risk management — prevent catastrophic losses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

import structlog

from kalshi_bot.api.models import Market, ProposedOrder
from kalshi_bot.config.settings import Settings

log = structlog.get_logger()


class RiskDecision(str, Enum):
    ALLOW = "allow"
    REDUCE = "reduce"
    REJECT = "reject"


@dataclass
class RiskResult:
    decision: RiskDecision
    reason: str
    adjusted_count: int | None = None  # for REDUCE decisions


class RiskManager:
    """Pre-trade risk checks. Must pass before any order is placed."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._daily_pnl_cents: int = 0
        self._trading_halted: bool = False

    def reset_daily(self) -> None:
        """Call at start of each trading day."""
        self._daily_pnl_cents = 0
        self._trading_halted = False

    def record_fill(self, pnl_cents: int) -> None:
        """Update daily P&L after a fill."""
        self._daily_pnl_cents += pnl_cents
        if self._daily_pnl_cents <= -(self.settings.max_daily_loss * 100):
            self._trading_halted = True
            log.error(
                "daily_loss_limit_hit",
                daily_pnl=self._daily_pnl_cents / 100,
                limit=self.settings.max_daily_loss,
            )

    def check_order(
        self,
        order: ProposedOrder,
        market: Market | None,
        current_position: int,
        total_exposure_cents: int,
        balance_cents: int,
        event_exposure_cents: int = 0,
        total_portfolio_cents: int = 0,
    ) -> RiskResult:
        """Run all pre-trade risk checks on a proposed order.

        Args:
            order: The proposed order.
            market: Market details (for checking hours, status).
            current_position: Net position in this market (positive = long YES).
            total_exposure_cents: Total portfolio exposure in cents.
            balance_cents: Available balance in cents.
            event_exposure_cents: Total exposure in this event's markets.
            total_portfolio_cents: Total portfolio value for concentration check.

        Returns:
            RiskResult with decision and reason.
        """
        # 0. Trading halted?
        if self._trading_halted:
            return RiskResult(RiskDecision.REJECT, "trading halted: daily loss limit hit")

        # 1. Market must be open
        if market and market.status != "open":
            return RiskResult(RiskDecision.REJECT, f"market not open: {market.status}")

        # 2. Check time to close
        if market and market.close_time:
            now = datetime.now(timezone.utc)
            hours_to_close = (market.close_time - now).total_seconds() / 3600
            if hours_to_close < self.settings.min_hours_to_close:
                return RiskResult(
                    RiskDecision.REJECT,
                    f"too close to market close: {hours_to_close:.1f}h < {self.settings.min_hours_to_close}h",
                )

        # 3. Per-market position limit
        new_position = current_position
        if order.action.value == "buy":
            new_position += order.count
        else:
            new_position -= order.count

        max_pos = self.settings.max_position_per_market
        if abs(new_position) > max_pos:
            allowed = max_pos - abs(current_position)
            if allowed <= 0:
                return RiskResult(RiskDecision.REJECT, f"position limit reached: {current_position}/{max_pos}")
            return RiskResult(
                RiskDecision.REDUCE,
                f"position limit: reducing {order.count} → {allowed}",
                adjusted_count=allowed,
            )

        # 4. Total portfolio exposure
        order_exposure = order.count * order.price_cents
        new_total = total_exposure_cents + order_exposure
        max_exposure = self.settings.max_total_exposure * 100
        if new_total > max_exposure:
            return RiskResult(
                RiskDecision.REJECT,
                f"total exposure would exceed limit: {new_total/100:.0f} > {self.settings.max_total_exposure}",
            )

        # 5. Concentration limit
        if total_portfolio_cents > 0:
            new_event_exposure = event_exposure_cents + order_exposure
            concentration = new_event_exposure / total_portfolio_cents
            if concentration > self.settings.max_event_concentration:
                return RiskResult(
                    RiskDecision.REJECT,
                    f"event concentration too high: {concentration:.1%} > {self.settings.max_event_concentration:.0%}",
                )

        # 6. Balance reserve
        min_reserve = self.settings.min_balance_reserve * 100
        if balance_cents - order_exposure < min_reserve:
            return RiskResult(
                RiskDecision.REJECT,
                f"insufficient balance: {balance_cents/100:.2f} - {order_exposure/100:.2f} < {self.settings.min_balance_reserve} reserve",
            )

        return RiskResult(RiskDecision.ALLOW, "all checks passed")
