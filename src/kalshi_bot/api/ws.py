"""WebSocket client for real-time Kalshi orderbook updates."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Callable, Coroutine

import structlog
import websockets
from websockets.asyncio.client import ClientConnection

from kalshi_bot.api.auth import load_private_key, sign_request
from kalshi_bot.config.settings import Settings

log = structlog.get_logger()

WS_PATH = "/trade-api/ws/v2"


class KalshiWebSocket:
    """WebSocket client for real-time market data from Kalshi."""

    def __init__(
        self,
        settings: Settings,
        on_orderbook: Callable[[dict[str, Any]], Coroutine] | None = None,
        on_fill: Callable[[dict[str, Any]], Coroutine] | None = None,
        on_trade: Callable[[dict[str, Any]], Coroutine] | None = None,
    ) -> None:
        self.settings = settings
        self._on_orderbook = on_orderbook
        self._on_fill = on_fill
        self._on_trade = on_trade
        self._ws: ClientConnection | None = None
        self._running = False
        self._subscribed_tickers: set[str] = set()
        self._private_key = load_private_key(settings.kalshi_private_key_path)

    def _ws_url(self) -> str:
        base = self.settings.kalshi_api_base.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}{WS_PATH}"

    def _auth_headers(self) -> dict[str, str]:
        headers = sign_request(self._private_key, "GET", WS_PATH)
        headers["KALSHI-ACCESS-KEY"] = self.settings.kalshi_api_key_id
        return headers

    async def connect(self) -> None:
        """Connect to the WebSocket with authentication."""
        headers = self._auth_headers()
        uri = self._ws_url()
        self._ws = await websockets.connect(uri, additional_headers=headers)
        self._running = True
        log.info("ws_connected", url=uri)

    async def subscribe(self, tickers: list[str], channels: list[str] | None = None) -> None:
        """Subscribe to orderbook updates for given tickers."""
        if not self._ws:
            return

        if channels is None:
            channels = ["orderbook_delta"]

        for ticker in tickers:
            msg = {
                "id": int(time.time() * 1000),
                "cmd": "subscribe",
                "params": {
                    "channels": channels,
                    "market_tickers": [ticker],
                },
            }
            await self._ws.send(json.dumps(msg))
            self._subscribed_tickers.add(ticker)

        log.info("ws_subscribed", tickers=tickers, channels=channels)

    async def unsubscribe(self, tickers: list[str]) -> None:
        """Unsubscribe from tickers."""
        if not self._ws:
            return

        for ticker in tickers:
            msg = {
                "id": int(time.time() * 1000),
                "cmd": "unsubscribe",
                "params": {
                    "channels": ["orderbook_delta"],
                    "market_tickers": [ticker],
                },
            }
            await self._ws.send(json.dumps(msg))
            self._subscribed_tickers.discard(ticker)

    async def listen(self) -> None:
        """Main listen loop. Reconnects on disconnect."""
        backoff = 1
        while self._running:
            try:
                if not self._ws:
                    await self.connect()
                    # Re-subscribe after reconnect
                    if self._subscribed_tickers:
                        await self.subscribe(list(self._subscribed_tickers))

                async for raw_msg in self._ws:  # type: ignore[union-attr]
                    backoff = 1  # reset on successful message
                    try:
                        msg = json.loads(raw_msg)
                        await self._dispatch(msg)
                    except json.JSONDecodeError:
                        log.warning("ws_invalid_json", raw=str(raw_msg)[:200])

            except websockets.ConnectionClosed as e:
                log.warning("ws_disconnected", code=e.code, reason=e.reason)
                self._ws = None
            except Exception as e:
                log.error("ws_error", error=str(e))
                self._ws = None

            if self._running:
                log.info("ws_reconnecting", backoff=backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def _dispatch(self, msg: dict[str, Any]) -> None:
        """Route incoming messages to callbacks."""
        msg_type = msg.get("type", "")

        if msg_type in ("orderbook_snapshot", "orderbook_delta"):
            if self._on_orderbook:
                await self._on_orderbook(msg)
        elif msg_type == "fill":
            if self._on_fill:
                await self._on_fill(msg)
        elif msg_type == "trade":
            if self._on_trade:
                await self._on_trade(msg)
        elif msg_type == "error":
            log.error("ws_server_error", msg=msg)

    async def close(self) -> None:
        """Gracefully close the WebSocket."""
        self._running = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        log.info("ws_closed")
