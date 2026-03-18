"""Configuration via environment variables and YAML defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings


def _load_yaml_defaults(path: str = "config/default.yaml") -> dict[str, Any]:
    p = Path(path)
    if p.exists():
        with open(p) as f:
            return yaml.safe_load(f) or {}
    return {}


_yaml = _load_yaml_defaults()
_strategy = _yaml.get("strategy", {})
_risk = _yaml.get("risk", {})
_weather = _yaml.get("weather", {})


class Settings(BaseSettings):
    # --- API credentials ---
    kalshi_api_key_id: str = ""
    kalshi_private_key_path: Path = Path("private_key.pem")
    kalshi_api_base: str = "https://api.elections.kalshi.com"
    dry_run: bool = False

    # --- Strategy ---
    min_edge_cents: int = _strategy.get("min_edge_cents", 3)
    kelly_fraction: float = _strategy.get("kelly_fraction", 0.25)
    max_markets: int = _strategy.get("max_markets", 10)
    forecast_refresh_minutes: int = _strategy.get("forecast_refresh_minutes", 30)
    tick_interval_seconds: float = _strategy.get("tick_interval_seconds", 5)
    flb_favorite_bonus: int = _strategy.get("flb_favorite_bonus", 1)
    flb_longshot_penalty: int = _strategy.get("flb_longshot_penalty", 1)

    # --- Risk ---
    max_position_per_market: int = _risk.get("max_position_per_market", 100)
    max_total_exposure: int = _risk.get("max_total_exposure", 5000)
    max_daily_loss: int = _risk.get("max_daily_loss", 500)
    max_event_concentration: float = _risk.get("max_event_concentration", 0.30)
    min_balance_reserve: int = _risk.get("min_balance_reserve", 200)
    min_hours_to_close: float = _risk.get("min_hours_to_close", 1)

    # --- Weather ---
    weather_cities: list[str] = Field(default_factory=lambda: _weather.get("cities", ["NYC", "CHI", "MIA", "AUS"]))
    weather_models: list[str] = Field(default_factory=lambda: _weather.get("models", ["gfs_seamless"]))
    weather_forecast_days: int = _weather.get("forecast_days", 7)
    weather_cache_ttl_minutes: int = _weather.get("cache_ttl_minutes", 30)

    model_config = {"env_file": ".env", "extra": "ignore"}
