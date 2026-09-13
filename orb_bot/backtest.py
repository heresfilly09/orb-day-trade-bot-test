"""Backtest engine for the ORB strategy using historical CSV data.

Expected CSV format: timestamp, open, high, low, close, volume
Timestamps should be in US/Eastern or UTC (specify via --tz flag).
Use 1-minute or 5-minute bars for best results.
"""

import csv
import logging
from datetime import datetime
from pathlib import Path

import pytz

from .journal import write_trade
from .models import PriceBar, TradeStatus
from .strategy import ORBStrategy

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


def run_backtest(
    config: dict,
    bars: list[PriceBar],
    journal_path: str | None = None,
) -> list[dict]:
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

        if trade and trade.status == TradeStatus.CLOSED and journal_path:
            write_trade(journal_path, trade)

    if current_date is not None:
        results.append({
            "date": str(current_date),
            "trades": len(strategy.daily_stats.trades),
            "pnl_points": strategy.daily_stats.total_pnl_points,
            "pnl_dollars": strategy.daily_stats.total_pnl_dollars,
            "winners": strategy.daily_stats.winners,
            "losers": strategy.daily_stats.losers,
        })

    return results


def print_backtest_summary(results: list[dict]) -> None:
    if not results:
        print("No results to display.")
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
    print(f"  Winning days:    {winning_days}/{trading_days}" if trading_days else "")
    print(f"  Total PnL:       {total_pnl:+.2f} pts (${total_dollars:+,.2f})")
    if trading_days > 0:
        print(f"  Avg PnL/day:     {total_pnl / trading_days:+.2f} pts")
    print("=" * 60)

    print("\n  Daily Breakdown:")
    print(f"  {'Date':<12} {'Trades':>6} {'PnL (pts)':>10} {'PnL ($)':>12} {'W':>3} {'L':>3}")
    print("  " + "-" * 50)
    for r in results:
        if r["trades"] > 0:
            print(
                f"  {r['date']:<12} {r['trades']:>6} {r['pnl_points']:>+10.2f}"
                f" {r['pnl_dollars']:>+12,.2f} {r['winners']:>3} {r['losers']:>3}"
            )
    print()
