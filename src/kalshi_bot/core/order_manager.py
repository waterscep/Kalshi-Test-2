"""Order lifecycle management: place, cancel, track."""

from __future__ import annotations

import structlog

from kalshi_bot.api.client import KalshiClient
from kalshi_bot.api.models import Order, ProposedOrder
from kalshi_bot.risk.manager import RiskDecision, RiskManager, RiskResult

log = structlog.get_logger()


class OrderManager:
    """Manages order placement, cancellation, and tracking."""

    def __init__(self, client: KalshiClient, risk_manager: RiskManager) -> None:
        self.client = client
        self.risk_manager = risk_manager
        self.active_orders: dict[str, Order] = {}  # order_id → Order

    async def sync_orders(self) -> None:
        """Fetch all resting orders from API."""
        try:
            orders = await self.client.get_orders(status="resting")
            self.active_orders = {o.order_id: o for o in orders if o.order_id}
            log.info("orders_synced", count=len(self.active_orders))
        except Exception as e:
            log.error("order_sync_failed", error=str(e))

    async def cancel_all(self, ticker: str | None = None) -> None:
        """Cancel all resting orders, optionally for a specific ticker."""
        try:
            await self.client.batch_cancel(ticker=ticker)
            if ticker:
                self.active_orders = {
                    oid: o for oid, o in self.active_orders.items()
                    if o.ticker != ticker
                }
            else:
                self.active_orders.clear()
            log.info("orders_cancelled", ticker=ticker or "all")
        except Exception as e:
            log.error("cancel_failed", error=str(e), ticker=ticker)

    async def execute_order(
        self,
        proposed: ProposedOrder,
        risk_result: RiskResult,
    ) -> Order | None:
        """Place an order that has passed risk checks.

        If risk_result is REDUCE, adjusts count accordingly.
        If REJECT, returns None.
        """
        if risk_result.decision == RiskDecision.REJECT:
            log.warning(
                "order_rejected",
                ticker=proposed.ticker,
                reason=risk_result.reason,
            )
            return None

        count = proposed.count
        if risk_result.decision == RiskDecision.REDUCE and risk_result.adjusted_count:
            count = risk_result.adjusted_count
            log.info(
                "order_reduced",
                ticker=proposed.ticker,
                original=proposed.count,
                adjusted=count,
                reason=risk_result.reason,
            )

        if count <= 0:
            return None

        try:
            # Determine yes_price or no_price based on side
            yes_price = proposed.price_cents if proposed.side.value == "yes" else None
            no_price = proposed.price_cents if proposed.side.value == "no" else None

            order = await self.client.place_order(
                ticker=proposed.ticker,
                action=proposed.action.value,
                side=proposed.side.value,
                order_type="limit",
                count=count,
                yes_price=yes_price,
                no_price=no_price,
            )

            if order.order_id:
                self.active_orders[order.order_id] = order

            log.info(
                "order_placed",
                ticker=proposed.ticker,
                side=proposed.side.value,
                action=proposed.action.value,
                price=proposed.price_cents,
                count=count,
                reason=proposed.reason,
                order_id=order.order_id,
            )
            return order

        except Exception as e:
            log.error(
                "order_placement_failed",
                ticker=proposed.ticker,
                error=str(e),
            )
            return None

    def get_orders_for_ticker(self, ticker: str) -> list[Order]:
        """Get all active orders for a specific ticker."""
        return [o for o in self.active_orders.values() if o.ticker == ticker]
