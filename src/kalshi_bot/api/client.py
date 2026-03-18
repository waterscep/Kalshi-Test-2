"""Async REST client for the Kalshi trading API."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx
import structlog

from kalshi_bot.api.auth import load_private_key, sign_request
from kalshi_bot.api.models import (
    Balance,
    Event,
    Market,
    Order,
    Orderbook,
    Position,
)
from kalshi_bot.config.settings import Settings

log = structlog.get_logger()

API_BASE_PATH = "/trade-api/v2"


class KalshiClient:
    """Async Kalshi REST API client with auth, retries, and rate limiting."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.kalshi_api_base.rstrip("/")
        self.api_key_id = settings.kalshi_api_key_id
        if settings.dry_run:
            self._private_key = None  # type: ignore[assignment]
        else:
            self._private_key = load_private_key(settings.kalshi_private_key_path)
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0),
        )
        self._last_request_time = 0.0
        self._min_interval = 0.1  # 10 req/s rate limit

    async def close(self) -> None:
        await self._client.aclose()

    # --- Private helpers ---

    def _auth_headers(self, method: str, path: str) -> dict[str, str]:
        headers = sign_request(self._private_key, method, path)
        headers["KALSHI-ACCESS-KEY"] = self.api_key_id
        return headers

    async def _rate_limit(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request_time
        if elapsed < self._min_interval:
            await asyncio.sleep(self._min_interval - elapsed)
        self._last_request_time = time.monotonic()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Make an authenticated API request with retries."""
        if self.settings.dry_run and self._private_key is None:
            log.debug("dry_run_skip_request", method=method, path=path)
            return {}
        full_path = f"{API_BASE_PATH}{path}"
        headers = self._auth_headers(method, full_path)

        for attempt in range(max_retries + 1):
            await self._rate_limit()
            try:
                resp = await self._client.request(
                    method,
                    full_path,
                    headers=headers,
                    params=params,
                    json=json,
                )
                if resp.status_code == 429 or resp.status_code >= 500:
                    if attempt < max_retries:
                        wait = 2 ** attempt
                        log.warning(
                            "retrying_request",
                            status=resp.status_code,
                            attempt=attempt + 1,
                            wait=wait,
                            path=path,
                        )
                        await asyncio.sleep(wait)
                        # Re-sign with fresh timestamp
                        headers = self._auth_headers(method, full_path)
                        continue
                    resp.raise_for_status()
                resp.raise_for_status()
                if resp.status_code == 204:
                    return {}
                return resp.json()
            except httpx.HTTPStatusError:
                raise
            except httpx.HTTPError as e:
                if attempt < max_retries:
                    wait = 2 ** attempt
                    log.warning("request_error", error=str(e), attempt=attempt + 1, wait=wait)
                    await asyncio.sleep(wait)
                    headers = self._auth_headers(method, full_path)
                    continue
                raise

        return {}  # unreachable

    # --- Market Data ---

    async def get_markets(
        self,
        *,
        series_ticker: str | None = None,
        event_ticker: str | None = None,
        status: str = "open",
        limit: int = 200,
        cursor: str | None = None,
    ) -> list[Market]:
        """List markets, optionally filtered by series/event."""
        params: dict[str, Any] = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if event_ticker:
            params["event_ticker"] = event_ticker
        if cursor:
            params["cursor"] = cursor

        data = await self._request("GET", "/markets", params=params)
        markets_raw = data.get("markets", [])
        return [Market.model_validate(m) for m in markets_raw]

    async def get_market(self, ticker: str) -> Market:
        data = await self._request("GET", f"/markets/{ticker}")
        return Market.model_validate(data.get("market", data))

    async def get_orderbook(self, ticker: str, depth: int = 10) -> Orderbook:
        data = await self._request(
            "GET", f"/markets/{ticker}/orderbook", params={"depth": depth}
        )
        ob = data.get("orderbook", data)
        ob["ticker"] = ticker
        return Orderbook.model_validate(ob)

    async def get_event(self, event_ticker: str) -> Event:
        data = await self._request("GET", f"/events/{event_ticker}")
        return Event.model_validate(data.get("event", data))

    # --- Trading ---

    async def place_order(
        self,
        ticker: str,
        action: str,
        side: str,
        order_type: str,
        count: int,
        yes_price: int | None = None,
        no_price: int | None = None,
    ) -> Order:
        """Place an order. Prices in cents (1-99)."""
        body: dict[str, Any] = {
            "ticker": ticker,
            "action": action,
            "side": side,
            "type": order_type,
            "count": count,
        }
        if yes_price is not None:
            body["yes_price"] = yes_price
        if no_price is not None:
            body["no_price"] = no_price

        if self.settings.dry_run:
            log.info("dry_run_order", **body)
            return Order(ticker=ticker, side=side, action=action, count=count,
                         yes_price=yes_price or 0, status="dry_run")

        data = await self._request("POST", "/portfolio/orders", json=body)
        return Order.model_validate(data.get("order", data))

    async def cancel_order(self, order_id: str) -> None:
        if self.settings.dry_run:
            log.info("dry_run_cancel", order_id=order_id)
            return
        await self._request("DELETE", f"/portfolio/orders/{order_id}")

    async def batch_cancel(self, *, ticker: str | None = None) -> None:
        """Cancel all resting orders, optionally filtered by ticker."""
        params: dict[str, Any] = {}
        if ticker:
            params["ticker"] = ticker
        if self.settings.dry_run:
            log.info("dry_run_batch_cancel", ticker=ticker)
            return
        await self._request("DELETE", "/portfolio/orders", params=params)

    # --- Portfolio ---

    async def get_positions(self) -> list[Position]:
        data = await self._request("GET", "/portfolio/positions")
        positions_raw = data.get("market_positions", [])
        return [Position.model_validate(p) for p in positions_raw]

    async def get_balance(self) -> Balance:
        data = await self._request("GET", "/portfolio/balance")
        return Balance.model_validate(data)

    async def get_orders(
        self, *, ticker: str | None = None, status: str = "resting"
    ) -> list[Order]:
        params: dict[str, Any] = {"status": status}
        if ticker:
            params["ticker"] = ticker
        data = await self._request("GET", "/portfolio/orders", params=params)
        return [Order.model_validate(o) for o in data.get("orders", [])]
