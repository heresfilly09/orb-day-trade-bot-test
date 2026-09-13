"""Backtest the ORB strategy on historical CSV data.

Usage:
    python backtest_orb.py --data es_1min_data.csv [--tz US/Eastern]

Expected CSV columns: timestamp, open, high, low, close, volume
Outputs: orb_trades.csv (individual trades), orb_summary.csv (daily summary)
"""

import argparse
import csv
import logging
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytz

from config import load_config
from orb_strategy import ORBStrategy, PriceBar, TradeStatus
from risk_manager import write_trade, write_summary

logger = logging.getLogger(__name__)

ET = pytz.timezone("US/Eastern")


def load_bars_from_csv(filepath: str, tz_name: str = "US/Eastern") -> list[PriceBar]:
    tz = pytz.timezone(tz_name)
    bars = []

    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts_str = row.get("timestamp") or row.get("datetime") or row.get("date")
            if not ts_str:
                continue
            try:
                dt = datetime.fromisoformat(ts_str)
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d %H:%M"):
                    try:
                        dt = datetime.strptime(ts_str, fmt)
                        break
                    except ValueError:
                        continue
                else:
                    logger.warning("Skipping unparseable timestamp: %s", ts_str)
                    continue

            if dt.tzinfo is None:
                dt = tz.localize(dt)

            bars.append(PriceBar(
                timestamp=dt,
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=int(row.get("volume", 0)),
            ))

    bars.sort(key=lambda b: b.timestamp)
    return bars


def run_backtest(config: dict, bars: list[PriceBar], trades_path: str, summary_path: str) -> list[dict]:
    strategy = ORBStrategy(config)
    results = []
    current_date = None

    for bar in bars:
        bar_date = bar.timestamp.astimezone(ET).date()

        if bar_date != current_date:
            if current_date is not None:
                results.append({
                    "date": str(current_date),
                    "trades": len(strategy.daily_stats.trades),
                    "pnl_points": strategy.daily_stats.total_pnl_points,
                    "pnl_dollars": strategy.daily_stats.total_pnl_dollars,
                    "winners": strategy.daily_stats.winners,
                    "losers": strategy.daily_stats.losers,
                })
            current_date = bar_date
            strategy.reset_day(str(bar_date))

        trade = strategy.on_bar(bar)

        if trade and trade.status == TradeStatus.CLOSED:
            write_trade(trades_path, trade)

    if current_date is not None:
        results.append({
            "date": str(current_date),
            "trades": len(strategy.daily_stats.trades),
            "pnl_points": strategy.daily_stats.total_pnl_points,
            "pnl_dollars": strategy.daily_stats.total_pnl_dollars,
            "winners": strategy.daily_stats.winners,
            "losers": strategy.daily_stats.losers,
        })

    write_summary(summary_path, results)
    return results


def print_results(results: list[dict]) -> None:
    if not results:
        print("No results.")
        return

    total_pnl = sum(r["pnl_points"] for r in results)
    total_dollars = sum(r["pnl_dollars"] for r in results)
    total_trades = sum(r["trades"] for r in results)
    total_winners = sum(r["winners"] for r in results)
    total_losers = sum(r["losers"] for r in results)
    trading_days = len([r for r in results if r["trades"] > 0])
    winning_days = len([r for r in results if r["pnl_points"] > 0])

    print("\n" + "=" * 60)
    print("  ORB STRATEGY BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Total days:      {len(results)}")
    print(f"  Trading days:    {trading_days}")
    print(f"  Total trades:    {total_trades}")
    print(f"  Winners:         {total_winners}")
    print(f"  Losers:          {total_losers}")
    if total_trades > 0:
        print(f"  Win rate:        {total_winners / total_trades * 100:.1f}%")
    if trading_days:
        print(f"  Winning days:    {winning_days}/{trading_days}")
    print(f"  Total PnL:       {total_pnl:+.2f} pts (${total_dollars:+,.2f})")
    if trading_days > 0:
        print(f"  Avg PnL/day:     {total_pnl / trading_days:+.2f} pts")
    print("=" * 60)

    print(f"\n  {'Date':<12} {'Trades':>6} {'PnL (pts)':>10} {'PnL ($)':>12} {'W':>3} {'L':>3}")
    print("  " + "-" * 50)
    for r in results:
        if r["trades"] > 0:
            print(
                f"  {r['date']:<12} {r['trades']:>6} {r['pnl_points']:>+10.2f}"
                f" {r['pnl_dollars']:>+12,.2f} {r['winners']:>3} {r['losers']:>3}"
            )
    print()


def generate_sample_data(filepath: str, days: int = 10) -> None:
    base_price = 5500.0
    tick = 0.25

    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "open", "high", "low", "close", "volume"])

        for day_offset in range(days):
            date = datetime(2025, 1, 6 + day_offset)
            if date.weekday() >= 5:
                continue

            price = base_price + random.uniform(-20, 20)

            for minute in range(390):
                dt = ET.localize(date.replace(hour=9, minute=30) + timedelta(minutes=minute))

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
    parser = argparse.ArgumentParser(description="ORB Strategy Backtester")
    parser.add_argument("--data", help="Path to CSV data file")
    parser.add_argument("--tz", default="US/Eastern", help="Timezone of data")
    parser.add_argument("--config", default="config.yaml", help="Config file")
    parser.add_argument("--generate", action="store_true", help="Generate sample data")
    parser.add_argument("--days", type=int, default=10, help="Days of sample data")
    args = parser.parse_args()

    config = load_config(args.config)

    logging.basicConfig(
        level=getattr(logging, config["logging"]["level"].upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config["logging"]["log_file"]),
        ],
    )

    if args.generate:
        generate_sample_data("es_sample_data.csv", days=args.days)
        return

    if not args.data:
        print("Error: --data required (or use --generate to create sample data)")
        sys.exit(1)

    if not Path(args.data).exists():
        print(f"Error: {args.data} not found")
        sys.exit(1)

    bars = load_bars_from_csv(args.data, tz_name=args.tz)
    print(f"Loaded {len(bars)} bars from {args.data}")

    trades_path = config["logging"]["trade_journal"]
    summary_path = trades_path.replace("trades", "summary").replace(".csv", ".csv")
    if summary_path == trades_path:
        summary_path = "orb_summary.csv"

    results = run_backtest(config, bars, trades_path, summary_path)
    print_results(results)
    print(f"Trades saved to: {trades_path}")
    print(f"Summary saved to: {summary_path}")


if __name__ == "__main__":
    main()
