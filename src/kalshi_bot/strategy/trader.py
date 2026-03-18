"""Main trading logic: ensemble forecast → edge detection → order generation."""

from __future__ import annotations

from dataclasses import dataclass

import structlog

from kalshi_bot.api.models import Market, Orderbook, ProposedOrder, OrderAction, OrderSide
from kalshi_bot.config.settings import Settings
from kalshi_bot.strategy.cross_strike_arb import ArbOpportunity, BracketQuote, find_arbitrage
from kalshi_bot.strategy.edge_calculator import EdgeSignal, find_edges
from kalshi_bot.strategy.sizing import kelly_contracts, kelly_contracts_sell
from kalshi_bot.weather.ensemble import EnsembleForecast, fetch_ensemble
from kalshi_bot.weather.probability import compute_all_bracket_probabilities
from kalshi_bot.weather.ticker_mapper import WeatherQuery, parse_ticker

log = structlog.get_logger()


@dataclass
class TradingDecision:
    """Collection of orders the strategy wants to place."""
    directional_orders: list[ProposedOrder]
    arb_orders: list[ProposedOrder]
    event_ticker: str


class WeatherTrader:
    """Stateless trading logic: given market state + forecasts, produce orders."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def evaluate_event(
        self,
        markets: list[Market],
        orderbooks: dict[str, Orderbook],
        balance_cents: int,
        current_positions: dict[str, int],
    ) -> TradingDecision:
        """Evaluate all brackets in a weather event and generate orders.

        Args:
            markets: All markets (brackets) in this event.
            orderbooks: Ticker → Orderbook for each market.
            balance_cents: Available balance in cents.
            current_positions: Ticker → net position (positive = long YES).

        Returns:
            TradingDecision with proposed orders.
        """
        if not markets:
            return TradingDecision([], [], "")

        event_ticker = markets[0].event_ticker

        # 1. Parse tickers to get weather queries
        queries: list[WeatherQuery] = []
        for m in markets:
            try:
                queries.append(parse_ticker(m.ticker))
            except ValueError as e:
                log.warning("ticker_parse_failed", ticker=m.ticker, error=str(e))
                continue

        if not queries:
            return TradingDecision([], [], event_ticker)

        # All brackets in an event share the same city/metric/date
        ref = queries[0]

        # 2. Fetch ensemble forecast
        try:
            forecast = await fetch_ensemble(
                city_code=ref.city_code,
                target_date=ref.target_date,
                metric=ref.metric,
                cache_ttl_seconds=self.settings.weather_cache_ttl_minutes * 60,
            )
        except Exception as e:
            log.error("ensemble_fetch_failed", error=str(e), event=event_ticker)
            return TradingDecision([], [], event_ticker)

        if not forecast.values_fahrenheit:
            log.warning("no_ensemble_data", event=event_ticker)
            return TradingDecision([], [], event_ticker)

        # 3. Compute bracket probabilities
        brackets = [(q.bracket_low, q.bracket_high) for q in queries]
        probs = compute_all_bracket_probabilities(forecast.values_fahrenheit, brackets)

        # 4. Get market prices
        tickers = [m.ticker for m in markets]
        market_prices = []
        for m in markets:
            ob = orderbooks.get(m.ticker)
            if ob and ob.best_yes_ask and ob.best_yes_bid:
                # Use midpoint as reference price
                mid = (ob.best_yes_bid + ob.best_yes_ask) // 2
                market_prices.append(mid)
            elif m.yes_bid > 0 and m.yes_ask > 0:
                market_prices.append((m.yes_bid + m.yes_ask) // 2)
            elif m.last_price > 0:
                market_prices.append(m.last_price)
            else:
                market_prices.append(50)  # no data, assume 50/50

        # 5. Check cross-strike arbitrage (risk-free, do first)
        arb_orders: list[ProposedOrder] = []
        bracket_quotes = []
        for m in markets:
            ob = orderbooks.get(m.ticker)
            if ob:
                bid = ob.best_yes_bid or m.yes_bid
                ask = ob.best_yes_ask or m.yes_ask
            else:
                bid = m.yes_bid
                ask = m.yes_ask
            bracket_quotes.append(BracketQuote(ticker=m.ticker, yes_bid=bid, yes_ask=ask))

        arb = find_arbitrage(bracket_quotes)
        if arb:
            arb_orders = self._arb_to_orders(arb)

        # 6. Find directional edges
        edges = find_edges(
            bracket_probs=probs,
            bracket_tickers=tickers,
            market_prices=market_prices,
            min_edge_cents=self.settings.min_edge_cents,
            favorite_bonus=self.settings.flb_favorite_bonus,
            longshot_penalty=self.settings.flb_longshot_penalty,
            ensemble_size=forecast.num_members,
        )

        # 7. Size and generate orders
        directional_orders: list[ProposedOrder] = []
        for edge in edges:
            pos = current_positions.get(edge.ticker, 0)

            # Skip if already at position limit on this side
            if edge.side == "buy_yes" and pos >= self.settings.max_position_per_market:
                continue
            if edge.side == "sell_yes" and pos <= -self.settings.max_position_per_market:
                continue

            # Compute size
            if edge.side == "buy_yes":
                count = kelly_contracts(
                    model_prob=edge.model_prob,
                    market_price_cents=edge.market_price_cents,
                    bankroll_cents=balance_cents,
                    fraction=self.settings.kelly_fraction,
                    max_contracts=self.settings.max_position_per_market - max(pos, 0),
                )
                if count > 0:
                    # Place limit buy at or below current ask
                    ob = orderbooks.get(edge.ticker)
                    buy_price = edge.market_price_cents
                    if ob and ob.best_yes_ask:
                        buy_price = ob.best_yes_ask  # hit the ask for immediate fill

                    directional_orders.append(ProposedOrder(
                        ticker=edge.ticker,
                        side=OrderSide.YES,
                        action=OrderAction.BUY,
                        price_cents=buy_price,
                        count=count,
                        reason=f"edge={edge.edge_cents:.1f}c model={edge.model_prob:.3f} mkt={edge.market_price_cents}c",
                    ))
            else:
                count = kelly_contracts_sell(
                    model_prob=edge.model_prob,
                    market_price_cents=edge.market_price_cents,
                    bankroll_cents=balance_cents,
                    fraction=self.settings.kelly_fraction,
                    max_contracts=self.settings.max_position_per_market - max(-pos, 0),
                )
                if count > 0:
                    ob = orderbooks.get(edge.ticker)
                    sell_price = edge.market_price_cents
                    if ob and ob.best_yes_bid:
                        sell_price = ob.best_yes_bid  # hit the bid

                    directional_orders.append(ProposedOrder(
                        ticker=edge.ticker,
                        side=OrderSide.YES,
                        action=OrderAction.SELL,
                        price_cents=sell_price,
                        count=count,
                        reason=f"edge={edge.edge_cents:.1f}c model={edge.model_prob:.3f} mkt={edge.market_price_cents}c",
                    ))

        log.info(
            "event_evaluated",
            event=event_ticker,
            brackets=len(markets),
            edges_found=len(edges),
            orders=len(directional_orders),
            arb=len(arb_orders) > 0,
        )

        return TradingDecision(
            directional_orders=directional_orders,
            arb_orders=arb_orders,
            event_ticker=event_ticker,
        )

    def _arb_to_orders(self, arb: ArbOpportunity) -> list[ProposedOrder]:
        """Convert arbitrage opportunity into ProposedOrders."""
        orders = []
        for trade in arb.trades:
            orders.append(ProposedOrder(
                ticker=trade.ticker,
                side=OrderSide.YES if trade.side == "yes" else OrderSide.NO,
                action=OrderAction.BUY if trade.action == "buy" else OrderAction.SELL,
                price_cents=trade.price,
                count=1,  # arb with 1 contract per bracket
                reason=f"arb:{arb.direction} profit={arb.profit_cents}c",
            ))
        return orders
