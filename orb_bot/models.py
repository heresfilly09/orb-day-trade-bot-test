from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Direction(Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class TradeStatus(Enum):
    PENDING = "PENDING"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ORBState(Enum):
    WAITING_FOR_OPEN = "WAITING_FOR_OPEN"
    BUILDING_RANGE = "BUILDING_RANGE"
    RANGE_SET = "RANGE_SET"
    IN_TRADE = "IN_TRADE"
    DONE_FOR_DAY = "DONE_FOR_DAY"


@dataclass
class PriceBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


@dataclass
class OpeningRange:
    high: float = 0.0
    low: float = float("inf")
    established: bool = False

    @property
    def size(self) -> float:
        if not self.established:
            return 0.0
        return self.high - self.low

    @property
    def midpoint(self) -> float:
        return (self.high + self.low) / 2.0

    def update(self, bar: PriceBar) -> None:
        if bar.high > self.high:
            self.high = bar.high
        if bar.low < self.low:
            self.low = bar.low

    def reset(self) -> None:
        self.high = 0.0
        self.low = float("inf")
        self.established = False


@dataclass
class Trade:
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    direction: Direction | None = None
    entry_price: float = 0.0
    exit_price: float = 0.0
    stop_loss: float = 0.0
    profit_target: float = 0.0
    size: int = 1
    status: TradeStatus = TradeStatus.PENDING
    pnl_points: float = 0.0
    pnl_dollars: float = 0.0
    exit_reason: str = ""

    def calculate_pnl(self, point_value: float) -> None:
        if self.direction == Direction.LONG:
            self.pnl_points = self.exit_price - self.entry_price
        else:
            self.pnl_points = self.entry_price - self.exit_price
        self.pnl_dollars = self.pnl_points * point_value * self.size


@dataclass
class DailyStats:
    date: str = ""
    trades: list[Trade] = field(default_factory=list)
    total_pnl_points: float = 0.0
    total_pnl_dollars: float = 0.0
    winners: int = 0
    losers: int = 0

    def update(self, trade: Trade) -> None:
        self.trades.append(trade)
        self.total_pnl_points += trade.pnl_points
        self.total_pnl_dollars += trade.pnl_dollars
        if trade.pnl_points > 0:
            self.winners += 1
        elif trade.pnl_points < 0:
            self.losers += 1
