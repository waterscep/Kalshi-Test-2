"""Entry point for the Kalshi weather trading bot."""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys

import logging

import structlog


def setup_logging(level: str = "INFO") -> None:
    """Configure structured logging."""
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer() if sys.stderr.isatty() else structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(),
    )


async def run(args: argparse.Namespace) -> None:
    from kalshi_bot.config.settings import Settings
    from kalshi_bot.core.engine import TradingEngine

    settings = Settings()
    if args.dry_run:
        settings.dry_run = True

    engine = TradingEngine(settings)

    # Handle graceful shutdown (not supported on Windows)
    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(engine.stop()))

    await engine.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Kalshi Weather Trading Bot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log trades without executing (paper trading mode)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    args = parser.parse_args()

    setup_logging(args.log_level)
    log = structlog.get_logger()
    log.info("starting", dry_run=args.dry_run)

    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        log.info("interrupted")


if __name__ == "__main__":
    main()
