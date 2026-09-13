#!/usr/bin/env python3
"""ORB Day Trading Bot - ES Futures Opening Range Breakout Strategy.

Usage:
    python main.py backtest --data data/es_1min.csv [--tz US/Eastern]
    python main.py paper
    python main.py generate-sample-data
"""

import argparse
import csv
import logging
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz
import yaml

from orb_bot.backtest import load_bars_from_csv, print_backtest_summary, run_backtest
from orb_bot.live import LiveRunner, PaperBroker, DataFeed
from orb_bot.models import PriceBar

ET = pytz.timezone("US/Eastern")


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def setup_logging(config: dict) -> None:
    log_cfg = config["logging"]
    level = getattr(logging, log_cfg["level"].upper(), logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)

    file_handler = logging.FileHandler(log_cfg["log_file"])
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(console)
    root.addHandler(file_handler)


def cmd_backtest(args, config: dict) -> None:
    if not Path(args.data).exists():
        print(f"Error: Data file not found: {args.data}")
        print("Run 'python main.py generate-sample-data' to create sample data.")
        sys.exit(1)

    bars = load_bars_from_csv(args.data, tz_name=args.tz)
    print(f"Loaded {len(bars)} bars from {args.data}")

    journal_path = config["logging"]["trade_journal"]
    results = run_backtest(config, bars, journal_path=journal_path)
    print_backtest_summary(results)
    print(f"Trade journal saved to: {journal_path}")


class SimulatedFeed(DataFeed):
    """Replays historical bars for paper trading demonstration."""

    def __init__(self, bars: list[PriceBar]):
        self._bars = bars
        self._index = 0

    def get_latest_bar(self) -> PriceBar | None:
        if self._index >= len(self._bars):
            return None
        bar = self._bars[self._index]
        self._index += 1
        return bar

    def is_connected(self) -> bool:
        return self._index < len(self._bars)


def cmd_paper(args, config: dict) -> None:
    data_path = getattr(args, "data", None) or "data/es_sample.csv"
    if not Path(data_path).exists():
        print(f"No data file found at {data_path}")
        print("Run 'python main.py generate-sample-data' first.")
        sys.exit(1)

    from orb_bot.backtest import load_bars_from_csv
    bars = load_bars_from_csv(data_path)

    feed = SimulatedFeed(bars)
    broker = PaperBroker()
    config["trading"]["paper_trade"] = True

    runner = LiveRunner(config, feed, broker, symbol="ES")
    try:
        runner.run(poll_interval_sec=0.01)
    except KeyboardInterrupt:
        runner.stop()


def cmd_generate_sample(args, config: dict) -> None:
    """Generate synthetic ES futures 1-minute data for testing."""
    Path("data").mkdir(exist_ok=True)
    filepath = "data/es_sample.csv"

    days = getattr(args, "days", 5)
    base_price = 5500.0
    tick = 0.25

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])

        for day_offset in range(days):
            date = datetime(2025, 1, 6 + day_offset)  # Start on a Monday
            if date.weekday() >= 5:
                continue

            price = base_price + random.uniform(-20, 20)

            for minute in range(390):  # 9:30 to 16:00 = 390 minutes
                dt = ET.localize(
                    date.replace(hour=9, minute=30) + timedelta(minutes=minute)
                )

                # More volatility in first 30 min and last 30 min
                if minute < 30 or minute > 360:
                    volatility = random.uniform(1.0, 3.0)
                else:
                    volatility = random.uniform(0.5, 1.5)

                open_price = round(price / tick) * tick
                move = random.gauss(0, volatility)
                close_price = round((price + move) / tick) * tick

                high_price = max(open_price, close_price) + random.uniform(0, volatility) * tick * 4
                high_price = round(high_price / tick) * tick
                low_price = min(open_price, close_price) - random.uniform(0, volatility) * tick * 4
                low_price = round(low_price / tick) * tick

                volume = int(random.uniform(500, 5000))
                if minute < 30:
                    volume *= 3

                writer.writerow([
                    dt.isoformat(),
                    f"{open_price:.2f}",
                    f"{high_price:.2f}",
                    f"{low_price:.2f}",
                    f"{close_price:.2f}",
                    volume,
                ])

                price = close_price

    print(f"Generated {days} days of sample ES 1-min data: {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="ORB Day Trading Bot - ES Futures Opening Range Breakout"
    )
    parser.add_argument("--config", default="config.yaml", help="Config file path")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    bt = subparsers.add_parser("backtest", help="Run backtest on historical data")
    bt.add_argument("--data", required=True, help="Path to CSV data file")
    bt.add_argument("--tz", default="US/Eastern", help="Timezone of data timestamps")

    paper = subparsers.add_parser("paper", help="Run paper trading simulation")
    paper.add_argument("--data", default="data/es_sample.csv", help="Data file for simulation")

    gen = subparsers.add_parser("generate-sample-data", help="Generate sample ES data")
    gen.add_argument("--days", type=int, default=5, help="Number of trading days")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    config = load_config(args.config)
    setup_logging(config)

    commands = {
        "backtest": cmd_backtest,
        "paper": cmd_paper,
        "generate-sample-data": cmd_generate_sample,
    }

    commands[args.command](args, config)


if __name__ == "__main__":
    main()
