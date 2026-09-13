import csv
import logging
import os
from dataclasses import dataclass
from pathlib import Path

from orb_strategy import Trade, DailyStats

logger = logging.getLogger(__name__)

TRADE_HEADERS = [
    "date",
    "entry_time",
    "exit_time",
    "direction",
    "entry_price",
    "exit_price",
    "stop_loss",
    "profit_target",
    "size",
    "pnl_points",
    "pnl_dollars",
    "exit_reason",
]


def write_trade(filepath: str, trade: Trade) -> None:
    file_exists = os.path.exists(filepath)
    with open(filepath, "a", newline="") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(TRADE_HEADERS)
        writer.writerow([
            trade.entry_time.strftime("%Y-%m-%d") if trade.entry_time else "",
            trade.entry_time.isoformat() if trade.entry_time else "",
            trade.exit_time.isoformat() if trade.exit_time else "",
            trade.direction.value if trade.direction else "",
            f"{trade.entry_price:.2f}",
            f"{trade.exit_price:.2f}",
            f"{trade.stop_loss:.2f}",
            f"{trade.profit_target:.2f}",
            trade.size,
            f"{trade.pnl_points:.2f}",
            f"{trade.pnl_dollars:.2f}",
            trade.exit_reason,
        ])


def read_journal(filepath: str) -> list[dict]:
    if not Path(filepath).exists():
        return []
    with open(filepath, newline="") as f:
        return list(csv.DictReader(f))


def write_summary(filepath: str, results: list[dict]) -> None:
    with open(filepath, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "trades", "winners", "losers", "pnl_points", "pnl_dollars"])
        for r in results:
            writer.writerow([
                r["date"],
                r["trades"],
                r["winners"],
                r["losers"],
                f"{r['pnl_points']:.2f}",
                f"{r['pnl_dollars']:.2f}",
            ])

    total_pnl = sum(r["pnl_points"] for r in results)
    total_dollars = sum(r["pnl_dollars"] for r in results)
    total_trades = sum(r["trades"] for r in results)
    total_winners = sum(r["winners"] for r in results)

    logger.info("Summary saved to %s — %d trades, PnL: %.2f pts ($%.2f)",
                filepath, total_trades, total_pnl, total_dollars)
