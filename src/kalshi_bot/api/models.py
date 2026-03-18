"""Pydantic models for Kalshi API objects."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# --- Enums ---

class MarketStatus(str, Enum):
    OPEN = "open"
    CLOSED = "closed"
    SETTLED = "settled"


class OrderSide(str, Enum):
    YES = "yes"
    NO = "no"


class OrderAction(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    LIMIT = "limit"
    MARKET = "market"


class OrderStatus(str, Enum):
    RESTING = "resting"
    CANCELED = "canceled"
    EXECUTED = "executed"
    PENDING = "pending"


# --- API Response Models ---

class Market(BaseModel):
    ticker: str
    event_ticker: str = ""
    series_ticker: str = ""
    title: str = ""
    status: str = ""
    yes_bid: int = 0          # best yes bid in cents (1-99)
    yes_ask: int = 0          # best yes ask in cents (1-99)
    last_price: int = 0
    volume: int = 0
    open_time: datetime | None = None
    close_time: datetime | None = None
    result: str = ""          # "yes", "no", or "" if unsettled
    subtitle: str = ""

    model_config = {"extra": "ignore"}


class OrderbookLevel(BaseModel):
    price: int                # cents (1-99)
    quantity: int = Field(alias="quantity", default=0)

    model_config = {"extra": "ignore", "populate_by_name": True}


class Orderbook(BaseModel):
    ticker: str = ""
    yes: list[list[int]] = Field(default_factory=list)   # [[price, qty], ...]
    no: list[list[int]] = Field(default_factory=list)

    model_config = {"extra": "ignore"}

    @property
    def best_yes_bid(self) -> int | None:
        """Highest price someone will pay for YES."""
        if self.yes:
            return max(level[0] for level in self.yes)
        return None

    @property
    def best_yes_ask(self) -> int | None:
        """Lowest price to buy YES (= 100 - best NO bid)."""
        if self.no:
            best_no_bid = max(level[0] for level in self.no)
            return 100 - best_no_bid
        return None

    @property
    def spread(self) -> int | None:
        bid = self.best_yes_bid
        ask = self.best_yes_ask
        if bid is not None and ask is not None:
            return ask - bid
        return None


class Order(BaseModel):
    order_id: str = ""
    ticker: str = ""
    side: str = ""            # "yes" or "no"
    action: str = ""          # "buy" or "sell"
    type: str = "limit"
    yes_price: int = 0        # cents
    no_price: int = 0
    count: int = 0            # number of contracts
    remaining_count: int = 0
    status: str = ""
    created_time: datetime | None = None

    model_config = {"extra": "ignore"}


class Position(BaseModel):
    ticker: str = ""
    market_exposure: int = 0       # cents at risk
    resting_orders_count: int = 0
    total_traded: int = 0

    # Derived fields — depend on API version
    yes_count: int = 0             # net YES contracts held
    no_count: int = 0

    model_config = {"extra": "ignore"}

    @property
    def net_position(self) -> int:
        """Positive = net long YES, negative = net long NO."""
        return self.yes_count - self.no_count


class Fill(BaseModel):
    trade_id: str = ""
    ticker: str = ""
    side: str = ""
    action: str = ""
    yes_price: int = 0
    no_price: int = 0
    count: int = 0
    created_time: datetime | None = None

    model_config = {"extra": "ignore"}


class Balance(BaseModel):
    balance: int = 0          # cents

    model_config = {"extra": "ignore"}

    @property
    def dollars(self) -> float:
        return self.balance / 100


class Event(BaseModel):
    event_ticker: str = ""
    series_ticker: str = ""
    title: str = ""
    category: str = ""
    markets: list[Market] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


# --- Internal Models ---

class ProposedOrder(BaseModel):
    """An order the strategy wants to place, before risk checks."""
    ticker: str
    side: OrderSide
    action: OrderAction
    price_cents: int
    count: int
    reason: str = ""          # human-readable reason for logging
