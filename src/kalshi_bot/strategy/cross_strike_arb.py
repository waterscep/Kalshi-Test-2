"""Cross-strike arbitrage: exploit bracket prices that don't sum to 100%."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

log = structlog.get_logger()


@dataclass
class BracketQuote:
    """Market quote for a single bracket in an event."""
    ticker: str
    yes_bid: int    # best price someone will pay for YES (cents)
    yes_ask: int    # cheapest price to buy YES (cents)


@dataclass
class ArbTrade:
    """A single leg of an arbitrage trade."""
    ticker: str
    action: str     # "buy" or "sell"
    side: str       # "yes" or "no"
    price: int      # cents


@dataclass
class ArbOpportunity:
    """A complete arbitrage opportunity across all brackets."""
    trades: list[ArbTrade]
    profit_cents: int       # guaranteed profit per contract set
    direction: str          # "buy_all_yes" or "sell_all_yes"


def find_arbitrage(brackets: list[BracketQuote]) -> ArbOpportunity | None:
    """Check if bracket prices violate the sum-to-100 constraint.

    For a complete set of brackets covering all outcomes:
    - If we can BUY YES on every bracket for < 100¢ total, we profit
      (guaranteed $1 payout, one bracket must win)
    - If we can SELL YES on every bracket for > 100¢ total, we profit
      (we collect > $1, pay out exactly $1 on the winning bracket)

    Returns an ArbOpportunity if found, None otherwise.
    """
    if len(brackets) < 2:
        return None

    # Filter out brackets with no valid quotes
    valid_for_buy = [b for b in brackets if 0 < b.yes_ask <= 99]
    valid_for_sell = [b for b in brackets if 0 < b.yes_bid <= 99]

    # --- Buy all YES ---
    # Total cost to buy YES on every bracket
    if len(valid_for_buy) == len(brackets):
        total_buy_cost = sum(b.yes_ask for b in brackets)
        if total_buy_cost < 98:  # 2¢ minimum profit to cover fees/slippage
            profit = 100 - total_buy_cost
            trades = [
                ArbTrade(
                    ticker=b.ticker,
                    action="buy",
                    side="yes",
                    price=b.yes_ask,
                )
                for b in brackets
            ]
            log.info(
                "arb_found",
                direction="buy_all_yes",
                total_cost=total_buy_cost,
                profit=profit,
                brackets=len(brackets),
            )
            return ArbOpportunity(
                trades=trades,
                profit_cents=profit,
                direction="buy_all_yes",
            )

    # --- Sell all YES ---
    # Total revenue from selling YES on every bracket
    if len(valid_for_sell) == len(brackets):
        total_sell_revenue = sum(b.yes_bid for b in brackets)
        if total_sell_revenue > 102:  # need > 100 + buffer
            profit = total_sell_revenue - 100
            trades = [
                ArbTrade(
                    ticker=b.ticker,
                    action="sell",
                    side="yes",
                    price=b.yes_bid,
                )
                for b in brackets
            ]
            log.info(
                "arb_found",
                direction="sell_all_yes",
                total_revenue=total_sell_revenue,
                profit=profit,
                brackets=len(brackets),
            )
            return ArbOpportunity(
                trades=trades,
                profit_cents=profit,
                direction="sell_all_yes",
            )

    return None
