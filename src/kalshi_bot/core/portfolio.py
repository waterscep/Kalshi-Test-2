"""Portfolio tracking: positions, P&L, and balance."""

from __future__ import annotations

from dataclasses import dataclass, field

import structlog

from kalshi_bot.api.client import KalshiClient
from kalshi_bot.api.models import Position

log = structlog.get_logger()


@dataclass
class PortfolioState:
    """Current portfolio state."""
    balance_cents: int = 0
    positions: dict[str, int] = field(default_factory=dict)  # ticker → net contracts
    exposure_cents: dict[str, int] = field(default_factory=dict)  # ticker → exposure
    realized_pnl_cents: int = 0

    @property
    def total_exposure_cents(self) -> int:
        return sum(self.exposure_cents.values())

    def event_exposure_cents(self, event_ticker: str) -> int:
        """Total exposure across all markets in an event."""
        return sum(
            exp for ticker, exp in self.exposure_cents.items()
            if ticker.startswith(event_ticker.split("-")[0])
        )


class PortfolioTracker:
    """Tracks positions and P&L, syncing periodically with the API."""

    def __init__(self, client: KalshiClient) -> None:
        self.client = client
        self.state = PortfolioState()

    async def sync(self) -> PortfolioState:
        """Fetch current positions and balance from API."""
        try:
            balance = await self.client.get_balance()
            self.state.balance_cents = balance.balance
        except Exception as e:
            log.error("balance_sync_failed", error=str(e))

        try:
            positions = await self.client.get_positions()
            self.state.positions.clear()
            self.state.exposure_cents.clear()
            for pos in positions:
                net = pos.net_position
                if net != 0:
                    self.state.positions[pos.ticker] = net
                if pos.market_exposure > 0:
                    self.state.exposure_cents[pos.ticker] = pos.market_exposure
        except Exception as e:
            log.error("positions_sync_failed", error=str(e))

        log.info(
            "portfolio_synced",
            balance=self.state.balance_cents / 100,
            positions=len(self.state.positions),
            total_exposure=self.state.total_exposure_cents / 100,
        )
        return self.state

    def record_fill(
        self, ticker: str, side: str, action: str, price_cents: int, count: int
    ) -> None:
        """Update local state after a fill (before next API sync)."""
        current = self.state.positions.get(ticker, 0)

        if action == "buy" and side == "yes":
            self.state.positions[ticker] = current + count
            self.state.balance_cents -= price_cents * count
        elif action == "sell" and side == "yes":
            self.state.positions[ticker] = current - count
            self.state.balance_cents += price_cents * count
        elif action == "buy" and side == "no":
            self.state.positions[ticker] = current - count
            self.state.balance_cents -= (100 - price_cents) * count
        elif action == "sell" and side == "no":
            self.state.positions[ticker] = current + count
            self.state.balance_cents += (100 - price_cents) * count

        log.info(
            "fill_recorded",
            ticker=ticker,
            side=side,
            action=action,
            price=price_cents,
            count=count,
            new_position=self.state.positions[ticker],
            balance=self.state.balance_cents / 100,
        )
