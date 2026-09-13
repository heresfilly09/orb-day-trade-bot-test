#!/usr/bin/env python3
"""ORB Day Trading Bot — ES Futures Opening Range Breakout.

Usage:
    python main.py                  # Run with paper broker (simulated data)
    python main.py --live           # Run with Tradovate (requires .env credentials)
    python backtest_orb.py --data es_data.csv   # Backtest on historical data
"""

import logging
import sys
import time
from datetime import datetime

import pytz

from config import load_config
from orb_strategy import ORBStrategy, PriceBar, TradeStatus
from risk_manager import write_trade
from tradovate_client import TradovateClient

ET = pytz.timezone("US/Eastern")
logger = logging.getLogger(__name__)


class PaperBroker:
    def __init__(self):
        self._order_id = 0

    def place_bracket_order(self, symbol, qty, side, stop_loss, profit_target):
        self._order_id += 1
        logger.info(
            "[PAPER] Bracket #%d: %s %d %s | SL: %.2f | TP: %.2f",
            self._order_id, side, qty, symbol, stop_loss, profit_target,
        )
        return self._order_id

    def cancel_all_orders(self):
        logger.info("[PAPER] All orders cancelled")

    def flatten_position(self, symbol):
        logger.info("[PAPER] Position flattened: %s", symbol)


def run_bot(config: dict, live: bool = False) -> None:
    strategy = ORBStrategy(config)
    symbol = "ESZ4"
    journal_path = config["logging"]["trade_journal"]

    if live:
        broker = TradovateClient(config)
        broker.authenticate()
        logger.info("Connected to Tradovate (%s)", "demo" if config["tradovate"]["demo"] else "LIVE")
    else:
        broker = PaperBroker()
        logger.info("Running in PAPER mode — no real orders")

    today = datetime.now(ET).strftime("%Y-%m-%d")
    strategy.reset_day(today)

    logger.info("ORB bot started for %s on %s", symbol, today)
    logger.info("Waiting for market open (9:30 ET)...")

    while True:
        now = datetime.now(ET)

        if now.strftime("%Y-%m-%d") != today:
            today = now.strftime("%Y-%m-%d")
            strategy.reset_day(today)
            logger.info("New trading day: %s", today)

        # In a real setup, you'd get bars from a websocket/data feed here.
        # This loop is the skeleton — plug in your data source.
        if strategy.state.value == "DONE_FOR_DAY":
            logger.info("Done for the day. Final PnL: %.2f pts ($%.2f)",
                        strategy.daily_stats.total_pnl_points,
                        strategy.daily_stats.total_pnl_dollars)
            break

        time.sleep(1)


def main():
    live = "--live" in sys.argv
    config = load_config()

    log_cfg = config["logging"]
    logging.basicConfig(
        level=getattr(logging, log_cfg["level"].upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_cfg["log_file"]),
        ],
    )

    run_bot(config, live=live)


if __name__ == "__main__":
    main()
