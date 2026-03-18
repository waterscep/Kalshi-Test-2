"""Main trading engine: orchestrates forecast → edge → risk → orders."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from itertools import groupby
from operator import attrgetter

import structlog

from kalshi_bot.api.client import KalshiClient
from kalshi_bot.api.models import Market, Orderbook
from kalshi_bot.api.ws import KalshiWebSocket
from kalshi_bot.config.settings import Settings
from kalshi_bot.core.order_manager import OrderManager
from kalshi_bot.core.portfolio import PortfolioTracker
from kalshi_bot.risk.manager import RiskManager
from kalshi_bot.strategy.trader import WeatherTrader

log = structlog.get_logger()

# Kalshi weather series prefixes to scan
WEATHER_SERIES = ["HIGHNY", "LOWNY", "HIGHCHI", "LOWCHI", "HIGHMIA", "LOWMIA", "HIGHAUS", "LOWAUS"]


class TradingEngine:
    """Main async engine that ties everything together."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = KalshiClient(settings)
        self.portfolio = PortfolioTracker(self.client)
        self.risk_manager = RiskManager(settings)
        self.order_manager = OrderManager(self.client, self.risk_manager)
        self.trader = WeatherTrader(settings)
        self.ws: KalshiWebSocket | None = None

        self._active_markets: dict[str, Market] = {}  # ticker → Market
        self._orderbooks: dict[str, Orderbook] = {}    # ticker → Orderbook
        self._running = False

    async def start(self) -> None:
        """Initialize and start the trading loop."""
        log.info("engine_starting", dry_run=self.settings.dry_run)

        # Initial sync
        await self.portfolio.sync()
        log.info(
            "initial_state",
            balance=self.portfolio.state.balance_cents / 100,
            positions=len(self.portfolio.state.positions),
        )

        # Scan for weather markets
        await self._scan_markets()

        self._running = True

        # Launch concurrent tasks
        tasks = [
            asyncio.create_task(self._trading_loop()),
            asyncio.create_task(self._market_scan_loop()),
            asyncio.create_task(self._portfolio_sync_loop()),
        ]

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            log.info("engine_shutting_down")
        finally:
            await self._shutdown()

    async def stop(self) -> None:
        self._running = False

    async def _shutdown(self) -> None:
        """Graceful shutdown: cancel all orders, close connections."""
        log.info("shutting_down")
        try:
            await self.order_manager.cancel_all()
        except Exception as e:
            log.error("shutdown_cancel_failed", error=str(e))

        if self.ws:
            await self.ws.close()
        await self.client.close()
        log.info("engine_stopped")

    # --- Market scanning ---

    async def _scan_markets(self) -> None:
        """Find active weather markets to trade."""
        new_markets: dict[str, Market] = {}
        today = date.today()

        for series in WEATHER_SERIES:
            try:
                markets = await self.client.get_markets(series_ticker=series, status="open")
                for m in markets:
                    # Only trade markets expiring in the next N days
                    if m.close_time:
                        days_out = (m.close_time.date() - today).days
                        if 0 <= days_out <= self.settings.weather_forecast_days:
                            new_markets[m.ticker] = m
            except Exception as e:
                log.warning("market_scan_failed", series=series, error=str(e))

        self._active_markets = new_markets
        log.info("markets_scanned", active=len(new_markets))

        # Fetch orderbooks for all active markets
        for ticker in new_markets:
            try:
                self._orderbooks[ticker] = await self.client.get_orderbook(ticker)
            except Exception as e:
                log.warning("orderbook_fetch_failed", ticker=ticker, error=str(e))

    # --- Trading loop ---

    async def _trading_loop(self) -> None:
        """Main loop: evaluate edges and place orders on each tick."""
        while self._running:
            try:
                await self._tick()
            except Exception as e:
                log.error("tick_error", error=str(e))

            await asyncio.sleep(self.settings.tick_interval_seconds)

    async def _tick(self) -> None:
        """Single trading tick: evaluate all events and manage orders."""
        if not self._active_markets:
            return

        # Group markets by event
        markets_list = sorted(self._active_markets.values(), key=attrgetter("event_ticker"))
        events = {
            event_ticker: list(event_markets)
            for event_ticker, event_markets in groupby(markets_list, key=attrgetter("event_ticker"))
        }

        for event_ticker, event_markets in events.items():
            # Get current positions for these markets
            positions = {
                m.ticker: self.portfolio.state.positions.get(m.ticker, 0)
                for m in event_markets
            }

            # Evaluate the event
            decision = await self.trader.evaluate_event(
                markets=event_markets,
                orderbooks=self._orderbooks,
                balance_cents=self.portfolio.state.balance_cents,
                current_positions=positions,
            )

            # Execute arbitrage orders first (risk-free)
            for order in decision.arb_orders:
                market = self._active_markets.get(order.ticker)
                risk_result = self.risk_manager.check_order(
                    order=order,
                    market=market,
                    current_position=positions.get(order.ticker, 0),
                    total_exposure_cents=self.portfolio.state.total_exposure_cents,
                    balance_cents=self.portfolio.state.balance_cents,
                    event_exposure_cents=self.portfolio.state.event_exposure_cents(event_ticker),
                    total_portfolio_cents=self.portfolio.state.balance_cents,
                )
                await self.order_manager.execute_order(order, risk_result)

            # Execute directional orders
            for order in decision.directional_orders:
                market = self._active_markets.get(order.ticker)
                risk_result = self.risk_manager.check_order(
                    order=order,
                    market=market,
                    current_position=positions.get(order.ticker, 0),
                    total_exposure_cents=self.portfolio.state.total_exposure_cents,
                    balance_cents=self.portfolio.state.balance_cents,
                    event_exposure_cents=self.portfolio.state.event_exposure_cents(event_ticker),
                    total_portfolio_cents=self.portfolio.state.balance_cents,
                )
                await self.order_manager.execute_order(order, risk_result)

    # --- Background tasks ---

    async def _market_scan_loop(self) -> None:
        """Rescan markets periodically."""
        while self._running:
            await asyncio.sleep(300)  # every 5 minutes
            try:
                await self._scan_markets()
            except Exception as e:
                log.error("market_scan_error", error=str(e))

    async def _portfolio_sync_loop(self) -> None:
        """Sync portfolio state periodically."""
        while self._running:
            await asyncio.sleep(60)
            try:
                await self.portfolio.sync()
                await self.order_manager.sync_orders()
            except Exception as e:
                log.error("portfolio_sync_error", error=str(e))

            # Check for new day → reset daily P&L
            now = datetime.now(timezone.utc)
            if now.hour == 0 and now.minute < 2:
                self.risk_manager.reset_daily()
