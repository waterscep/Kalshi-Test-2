"""Kelly criterion position sizing for binary contracts."""

from __future__ import annotations


def kelly_contracts(
    model_prob: float,
    market_price_cents: int,
    bankroll_cents: int,
    fraction: float = 0.25,
    max_contracts: int = 100,
) -> int:
    """Compute optimal position size using fractional Kelly criterion.

    For a binary contract priced at `market_price_cents`:
    - Buying YES costs `price` cents, pays 100 cents if YES wins
    - Kelly fraction f* = (p - price/100) / (1 - price/100)
      where p = model probability of YES

    We use fractional Kelly (default 1/4) for safety:
    - Full Kelly maximizes long-run growth but has high variance
    - Quarter Kelly gives ~75% of the growth with ~25% of the variance

    Args:
        model_prob: Our estimated probability of YES [0, 1].
        market_price_cents: Market price of YES contract (1-99).
        bankroll_cents: Available capital in cents.
        fraction: Kelly fraction (0.25 = quarter Kelly).
        max_contracts: Hard cap on contracts per market.

    Returns:
        Number of contracts to trade (0 if no edge).
    """
    if market_price_cents <= 0 or market_price_cents >= 100:
        return 0
    if bankroll_cents <= 0:
        return 0

    price = market_price_cents / 100.0
    edge = model_prob - price

    if edge <= 0:
        return 0

    # Kelly formula for binary outcome:
    # f* = (p * (1 - price) - (1 - p) * price) / (1 - price)
    #    = (p - price) / (1 - price)
    kelly_f = edge / (1.0 - price)

    # Apply fractional Kelly
    bet_fraction = fraction * kelly_f

    # Convert to number of contracts
    # Each YES contract costs `market_price_cents` cents
    dollar_bet = bankroll_cents * bet_fraction
    contracts = int(dollar_bet / market_price_cents)

    return max(0, min(contracts, max_contracts))


def kelly_contracts_sell(
    model_prob: float,
    market_price_cents: int,
    bankroll_cents: int,
    fraction: float = 0.25,
    max_contracts: int = 100,
) -> int:
    """Kelly sizing for selling YES (shorting, betting on NO).

    When selling YES at price P:
    - We receive P cents
    - We pay out (100 - P) cents if YES wins
    - Edge = price/100 - model_prob (we think YES is overpriced)
    - Kelly f* = (price/100 - model_prob) / (price/100)
    """
    if market_price_cents <= 0 or market_price_cents >= 100:
        return 0
    if bankroll_cents <= 0:
        return 0

    price = market_price_cents / 100.0
    edge = price - model_prob

    if edge <= 0:
        return 0

    # Kelly for selling YES:
    # Risk per contract = (100 - price) cents (max loss if YES wins)
    # Reward per contract = price cents (collected premium)
    # f* = (price - model_prob) / price  [simplified]
    kelly_f = edge / price

    bet_fraction = fraction * kelly_f

    # Cost basis for selling = margin required = (100 - price) cents
    margin_per_contract = 100 - market_price_cents
    if margin_per_contract <= 0:
        return 0

    dollar_bet = bankroll_cents * bet_fraction
    contracts = int(dollar_bet / margin_per_contract)

    return max(0, min(contracts, max_contracts))
