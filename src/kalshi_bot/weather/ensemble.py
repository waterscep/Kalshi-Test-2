"""Fetch ensemble weather forecasts from Open-Meteo API."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import date

import httpx
import structlog

from kalshi_bot.weather.ticker_mapper import get_city_coords

log = structlog.get_logger()

OPEN_METEO_ENSEMBLE_URL = "https://ensemble-api.open-meteo.com/v1/ensemble"


@dataclass
class EnsembleForecast:
    """Ensemble forecast for a specific city, date, and metric."""
    city_code: str
    target_date: date
    metric: str                          # "high_temp", "low_temp", "precip", "snow"
    values_fahrenheit: list[float]       # one value per ensemble member
    fetched_at: float = 0.0             # unix timestamp

    @property
    def num_members(self) -> int:
        return len(self.values_fahrenheit)


# In-memory cache: (city_code, date, metric) → EnsembleForecast
_cache: dict[tuple[str, str, str], EnsembleForecast] = {}


def _c_to_f(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def _mm_to_inches(mm: float) -> float:
    return mm / 25.4


async def fetch_ensemble(
    city_code: str,
    target_date: date,
    metric: str,
    model: str = "gfs_seamless",
    cache_ttl_seconds: int = 1800,
) -> EnsembleForecast:
    """Fetch ensemble forecast from Open-Meteo.

    Returns an EnsembleForecast with one value per ensemble member, converted
    to Fahrenheit (temp) or inches (precip/snow).
    """
    cache_key = (city_code, target_date.isoformat(), metric)
    cached = _cache.get(cache_key)
    if cached and (time.time() - cached.fetched_at) < cache_ttl_seconds:
        return cached

    lat, lon = get_city_coords(city_code)
    date_str = target_date.isoformat()

    # Map metric to Open-Meteo variable
    if metric in ("high_temp", "low_temp"):
        hourly_var = "temperature_2m"
    elif metric == "precip":
        hourly_var = "precipitation"
    elif metric == "snow":
        hourly_var = "snowfall"
    else:
        raise ValueError(f"Unknown metric: {metric}")

    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": hourly_var,
        "start_date": date_str,
        "end_date": date_str,
        "models": model,
        "temperature_unit": "celsius",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(OPEN_METEO_ENSEMBLE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    hourly = data.get("hourly", {})

    # Open-Meteo returns ensemble members as separate keys:
    # "temperature_2m_member01", "temperature_2m_member02", etc.
    # Or as "temperature_2m" with nested arrays depending on the endpoint
    member_values: list[float] = []

    # Collect all member keys
    member_keys = sorted(
        k for k in hourly if k.startswith(hourly_var) and "member" in k
    )

    if not member_keys:
        # Fallback: might be a single array (non-ensemble endpoint)
        raw = hourly.get(hourly_var, [])
        if raw:
            member_keys = [hourly_var]

    for key in member_keys:
        raw_values = hourly[key]
        # Filter out None values
        valid = [v for v in raw_values if v is not None]
        if not valid:
            continue

        if metric == "high_temp":
            daily_value = max(valid)
        elif metric == "low_temp":
            daily_value = min(valid)
        else:
            daily_value = sum(valid)  # total precip/snow for the day

        # Convert units
        if metric in ("high_temp", "low_temp"):
            daily_value = _c_to_f(daily_value)
        elif metric in ("precip", "snow"):
            daily_value = _mm_to_inches(daily_value)

        member_values.append(daily_value)

    if not member_values:
        log.warning(
            "no_ensemble_data",
            city=city_code,
            date=date_str,
            metric=metric,
        )
        return EnsembleForecast(
            city_code=city_code,
            target_date=target_date,
            metric=metric,
            values_fahrenheit=[],
            fetched_at=time.time(),
        )

    forecast = EnsembleForecast(
        city_code=city_code,
        target_date=target_date,
        metric=metric,
        values_fahrenheit=member_values,
        fetched_at=time.time(),
    )

    _cache[cache_key] = forecast
    log.info(
        "ensemble_fetched",
        city=city_code,
        date=date_str,
        metric=metric,
        members=len(member_values),
        mean=f"{sum(member_values)/len(member_values):.1f}",
    )
    return forecast


def clear_cache() -> None:
    _cache.clear()
