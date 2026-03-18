"""Map Kalshi weather tickers to structured weather queries."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class WeatherQuery:
    """Parsed representation of a Kalshi weather ticker."""
    city_code: str        # e.g. "NYC", "CHI"
    metric: str           # "high_temp", "low_temp", "precip", "snow"
    target_date: date
    bracket_low: float | None   # lower bound (°F or inches), None for below-range
    bracket_high: float | None  # upper bound, None for above-range
    event_ticker: str     # original event ticker
    market_ticker: str    # original market ticker


# Kalshi city codes → (latitude, longitude) for Open-Meteo
CITY_COORDS: dict[str, tuple[float, float]] = {
    "NYC": (40.7128, -74.0060),
    "NY":  (40.7128, -74.0060),
    "CHI": (41.8781, -87.6298),
    "MIA": (25.7617, -80.1918),
    "AUS": (30.2672, -97.7431),
    "LA":  (34.0522, -118.2437),
    "DEN": (39.7392, -104.9903),
    "ATL": (33.7490, -84.3880),
    "DAL": (32.7767, -96.7970),
    "PHX": (33.4484, -112.0740),
}

# Series ticker prefixes → metric type
SERIES_PREFIX_MAP: dict[str, str] = {
    "HIGH":  "high_temp",
    "KXHIGH": "high_temp",
    "LOW":   "low_temp",
    "KXLOW":  "low_temp",
    "RAIN":  "precip",
    "SNOW":  "snow",
}

# Date format in tickers: YYMMMDD (e.g., 26MAR20)
_DATE_RE = re.compile(r"(\d{2})([A-Z]{3})(\d{2})")
_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

# Bracket suffix: B{number} where number encodes the midpoint or edge
_BRACKET_RE = re.compile(r"B(\d+\.?\d*)")


def _parse_date(date_str: str) -> date:
    """Parse YYMMMDD format like '26MAR20' → date(2026, 3, 20)."""
    m = _DATE_RE.match(date_str)
    if not m:
        raise ValueError(f"Cannot parse date from '{date_str}'")
    year = 2000 + int(m.group(1))
    month = _MONTH_MAP[m.group(2)]
    day = int(m.group(3))
    return date(year, month, day)


def _parse_series_and_city(prefix: str) -> tuple[str, str]:
    """Extract metric type and city code from series prefix.

    Examples: 'HIGHNY' → ('high_temp', 'NYC'), 'LOWCHI' → ('low_temp', 'CHI')
    """
    # Try longest prefix first
    for series_prefix in sorted(SERIES_PREFIX_MAP, key=len, reverse=True):
        if prefix.startswith(series_prefix):
            city_suffix = prefix[len(series_prefix):]
            metric = SERIES_PREFIX_MAP[series_prefix]
            # Normalize city code
            for code in CITY_COORDS:
                if city_suffix.upper().startswith(code[:2]) or city_suffix.upper() == code:
                    return metric, code
            # Try the suffix directly as a city code
            city_upper = city_suffix.upper()
            if city_upper in CITY_COORDS:
                return metric, city_upper
            # Fallback: use raw suffix and try 2-3 letter match
            for code in CITY_COORDS:
                if code.startswith(city_upper) or city_upper.startswith(code[:2]):
                    return metric, code
            return metric, city_suffix.upper()
    raise ValueError(f"Unknown series prefix in '{prefix}'")


def parse_ticker(market_ticker: str) -> WeatherQuery:
    """Parse a Kalshi weather market ticker into a WeatherQuery.

    Ticker format examples:
      HIGHNY-26MAR20-B60.5   → NYC high temp, bracket around 60-62°F
      LOWCHI-26MAR20-B25.5   → Chicago low temp, bracket around 25-27°F
      HIGHNY-26MAR20-T55     → NYC high temp, above/below 55°F threshold
    """
    parts = market_ticker.split("-")
    if len(parts) < 2:
        raise ValueError(f"Invalid ticker format: '{market_ticker}'")

    series_part = parts[0]
    date_part = parts[1]
    bracket_part = parts[2] if len(parts) > 2 else ""

    metric, city_code = _parse_series_and_city(series_part)
    target_date = _parse_date(date_part)

    # Derive event ticker (series + date, no bracket)
    event_ticker = f"{series_part}-{date_part}"

    # Parse bracket
    bracket_low: float | None = None
    bracket_high: float | None = None

    if bracket_part:
        bm = _BRACKET_RE.search(bracket_part)
        if bm:
            midpoint = float(bm.group(1))
            # Standard Kalshi weather brackets are 2°F wide
            # The midpoint value is typically the center
            # e.g., B60.5 means the bracket [60, 62)
            bracket_low = midpoint - 0.5
            bracket_high = midpoint + 1.5
        elif bracket_part.startswith("T"):
            # Threshold format: above/below a specific value
            threshold = float(bracket_part[1:])
            bracket_low = threshold
            bracket_high = None  # "above threshold" contract

    return WeatherQuery(
        city_code=city_code,
        metric=metric,
        target_date=target_date,
        bracket_low=bracket_low,
        bracket_high=bracket_high,
        event_ticker=event_ticker,
        market_ticker=market_ticker,
    )


def get_city_coords(city_code: str) -> tuple[float, float]:
    """Get (latitude, longitude) for a city code."""
    normalized = city_code.upper()
    if normalized in CITY_COORDS:
        return CITY_COORDS[normalized]
    raise ValueError(f"Unknown city code: '{city_code}'")
