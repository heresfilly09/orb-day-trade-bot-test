import csv
import os
from pathlib import Path

from .models import Trade


JOURNAL_HEADERS = [
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
            writer.writerow(JOURNAL_HEADERS)
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
