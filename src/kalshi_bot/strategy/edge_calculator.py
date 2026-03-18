"""Compute trading edge: model probability vs market price."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EdgeSignal:
    """A detected trading opportunity."""
    ticker: str
    model_prob: float       # our model's probability [0, 1]
    market_price_cents: int # current market price (1-99)
    edge_cents: float       # positive = profitable
    side: str               # "buy_yes" or "sell_yes"
    confidence: float       # 0-1, based on ensemble size / model quality


def compute_edge(
    model_prob: float,
    market_price_cents: int,
) -> tuple[float, str]:
    """Compute edge in cents and recommended side.

    Returns (edge_cents, side) where edge_cents > 0 means opportunity.
    """
    market_prob = market_price_cents / 100.0

    buy_edge = (model_prob - market_prob) * 100   # buy YES when model > market
    sell_edge = (market_prob - model_prob) * 100   # sell YES when market > model

    if buy_edge >= sell_edge:
        return buy_edge, "buy_yes"
    else:
        return sell_edge, "sell_yes"


def apply_flb_adjustment(
    edge_cents: float,
    market_price_cents: int,
    favorite_bonus: int = 1,
    longshot_penalty: int = 1,
) -> float:
    """Adjust edge for the favorite-longshot bias.

    Research shows Kalshi contracts >80¢ win more than implied
    and contracts <20¢ win less than implied. We systematically
    adjust our edge estimate to capture this.
    """
    if market_price_cents >= 80:
        # Favorites are underpriced — add bonus for buying
        return edge_cents + favorite_bonus
    elif market_price_cents <= 20:
        # Longshots are overpriced — add bonus for selling
        return edge_cents + longshot_penalty
    return edge_cents


def find_edges(
    bracket_probs: list[float],
    bracket_tickers: list[str],
    market_prices: list[int],
    min_edge_cents: float = 3.0,
    favorite_bonus: int = 1,
    longshot_penalty: int = 1,
    ensemble_size: int = 31,
) -> list[EdgeSignal]:
    """Find all tradeable edges across brackets in an event.

    Args:
        bracket_probs: Model probability for each bracket (sums to 1).
        bracket_tickers: Kalshi ticker for each bracket.
        market_prices: Current YES price in cents for each bracket.
        min_edge_cents: Minimum edge to consider trading.
        ensemble_size: Number of ensemble members (affects confidence).

    Returns:
        List of EdgeSignal for all brackets with sufficient edge.
    """
    signals: list[EdgeSignal] = []
    confidence = min(ensemble_size / 31.0, 1.0)  # full confidence at 31+ members

    for prob, ticker, price in zip(bracket_probs, bracket_tickers, market_prices):
        if price <= 0 or price >= 100:
            continue

        edge, side = compute_edge(prob, price)
        edge = apply_flb_adjustment(edge, price, favorite_bonus, longshot_penalty)

        if edge >= min_edge_cents:
            signals.append(EdgeSignal(
                ticker=ticker,
                model_prob=prob,
                market_price_cents=price,
                edge_cents=edge,
                side=side,
                confidence=confidence,
            ))

    # Sort by edge descending — trade the best opportunities first
    signals.sort(key=lambda s: s.edge_cents, reverse=True)
    return signals
