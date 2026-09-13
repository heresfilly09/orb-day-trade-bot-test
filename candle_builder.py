import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("US/Eastern")


@dataclass
class Candle:
    timestamp: datetime | None = None
    open: float = 0.0
    high: float = 0.0
    low: float = float("inf")
    close: float = 0.0
    volume: int = 0
    complete: bool = False

    def update(self, price: float, volume: int = 0) -> None:
        if self.open == 0.0:
            self.open = price
        if price > self.high:
            self.high = price
        if price < self.low:
            self.low = price
        self.close = price
        self.volume += volume


class CandleBuilder:
    """Builds fixed-interval candles from tick or sub-minute data."""

    def __init__(self, interval_minutes: int = 15):
        self.interval = timedelta(minutes=interval_minutes)
        self.current: Candle | None = None
        self._candle_end: datetime | None = None
        self.completed: list[Candle] = []

    def _get_candle_start(self, dt: datetime) -> datetime:
        et_dt = dt.astimezone(ET) if dt.tzinfo else ET.localize(dt)
        minutes_since_midnight = et_dt.hour * 60 + et_dt.minute
        interval_min = int(self.interval.total_seconds() // 60)
        candle_start_min = (minutes_since_midnight // interval_min) * interval_min
        return et_dt.replace(
            hour=candle_start_min // 60,
            minute=candle_start_min % 60,
            second=0,
            microsecond=0,
        )

    def on_tick(self, timestamp: datetime, price: float, volume: int = 0) -> Candle | None:
        candle_start = self._get_candle_start(timestamp)
        candle_end = candle_start + self.interval

        if self.current is None or candle_start != self._get_candle_start(self.current.timestamp):
            if self.current is not None:
                self.current.complete = True
                self.completed.append(self.current)
                completed = self.current
            else:
                completed = None

            self.current = Candle(timestamp=candle_start)
            self._candle_end = candle_end
            self.current.update(price, volume)
            return completed

        self.current.update(price, volume)
        return None

    def flush(self) -> Candle | None:
        if self.current is not None and self.current.open != 0.0:
            self.current.complete = True
            self.completed.append(self.current)
            result = self.current
            self.current = None
            return result
        return None

    def reset(self) -> None:
        self.current = None
        self._candle_end = None
        self.completed = []
