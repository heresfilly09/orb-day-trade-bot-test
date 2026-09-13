import logging
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from enum import Enum

import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("US/Eastern")


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


class ORBStrategy:
    """Opening Range Breakout strategy for ES futures.

    Builds the opening range from the first two 15-minute candles at NYSE open
    (9:30-10:00 ET), then trades breakouts above the high or below the low.
    Stop loss is placed at the opposite end of the range.
    """

    def __init__(self, config: dict):
        strat = config["strategy"]
        risk = config["risk"]
        trading = config["trading"]

        self.orb_start = self._parse_time(strat["orb_start"])
        self.orb_end = self._parse_time(strat["orb_end"])
        self.orb_candle_minutes = strat.get("orb_candle_minutes", 15)
        self.breakout_trigger = strat.get("breakout_trigger", "close")
        self.breakout_buffer = strat.get("breakout_buffer_ticks", 0) * trading["tick_size"]
        self.max_range_size = strat.get("max_range_size", 0)
        self.min_range_size = strat.get("min_range_size", 0)
        self.wait_for_retest = strat.get("wait_for_retest", False)

        self.stop_loss_buffer = risk["stop_loss_buffer"]
        self.profit_target_rr = risk["profit_target_rr"]
        self.fixed_profit_target = risk["fixed_profit_target"]
        self.max_daily_loss = risk["max_daily_loss"]
        self.position_size = risk["position_size"]
        self.max_trades_per_day = risk["max_trades_per_day"]
        self.use_trailing_stop = risk["use_trailing_stop"]
        self.trailing_stop_distance = risk["trailing_stop_distance"]

        self.session_end = self._parse_time(trading["session_end"])
        self.point_value = trading["point_value"]
        self.tick_size = trading["tick_size"]

        self.state = ORBState.WAITING_FOR_OPEN
        self.opening_range = OpeningRange()
        self.current_trade: Trade | None = None
        self.daily_stats = DailyStats()
        self._trailing_stop: float | None = None
        self._retest_pending: Direction | None = None

        self._orb_candles: list[PriceBar] = []
        self._current_candle: PriceBar | None = None
        self._candle_end: datetime | None = None

    @staticmethod
    def _parse_time(t: str) -> time:
        parts = t.split(":")
        return time(int(parts[0]), int(parts[1]))

    def _to_et(self, dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return ET.localize(dt)
        return dt.astimezone(ET)

    def _get_et_time(self, dt: datetime) -> time:
        return self._to_et(dt).time()

    def reset_day(self, date_str: str = "") -> None:
        self.state = ORBState.WAITING_FOR_OPEN
        self.opening_range.reset()
        self.current_trade = None
        self.daily_stats = DailyStats(date=date_str)
        self._trailing_stop = None
        self._retest_pending = None
        self._orb_candles = []
        self._current_candle = None
        self._candle_end = None
        logger.info("Day reset: %s", date_str)

    def on_bar(self, bar: PriceBar) -> Trade | None:
        et_time = self._get_et_time(bar.timestamp)

        if self.state == ORBState.DONE_FOR_DAY:
            return None

        if et_time >= self.session_end:
            return self._handle_session_end(bar)

        if self.state == ORBState.WAITING_FOR_OPEN:
            if et_time >= self.orb_start:
                self.state = ORBState.BUILDING_RANGE
                logger.info("Market open — building range from two %d-min candles", self.orb_candle_minutes)
                self._start_new_candle(bar)
            return None

        if self.state == ORBState.BUILDING_RANGE:
            return self._build_range(bar)

        if self.state == ORBState.RANGE_SET:
            return self._check_breakout(bar)

        if self.state == ORBState.IN_TRADE:
            return self._manage_trade(bar)

        return None

    def _start_new_candle(self, bar: PriceBar) -> None:
        self._current_candle = PriceBar(
            timestamp=bar.timestamp,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
        )
        et_dt = self._to_et(bar.timestamp)
        self._candle_end = et_dt + timedelta(minutes=self.orb_candle_minutes)

    def _update_current_candle(self, bar: PriceBar) -> None:
        candle = self._current_candle
        if bar.high > candle.high:
            candle.high = bar.high
        if bar.low < candle.low:
            candle.low = bar.low
        candle.close = bar.close
        candle.volume += bar.volume

    def _build_range(self, bar: PriceBar) -> None:
        et_dt = self._to_et(bar.timestamp)

        if self._current_candle is None:
            self._start_new_candle(bar)
            return None

        if et_dt >= self._candle_end:
            self._orb_candles.append(self._current_candle)
            logger.info(
                "ORB candle %d complete — O: %.2f H: %.2f L: %.2f C: %.2f",
                len(self._orb_candles),
                self._current_candle.open,
                self._current_candle.high,
                self._current_candle.low,
                self._current_candle.close,
            )

            if len(self._orb_candles) >= 2:
                return self._finalize_range()

            self._start_new_candle(bar)
        else:
            self._update_current_candle(bar)

        return None

    def _finalize_range(self) -> None:
        orb_high = max(c.high for c in self._orb_candles)
        orb_low = min(c.low for c in self._orb_candles)

        self.opening_range.high = orb_high
        self.opening_range.low = orb_low
        self.opening_range.established = True
        size = self.opening_range.size

        if self.max_range_size > 0 and size > self.max_range_size:
            logger.warning(
                "Opening range too wide: %.2f pts (max %.2f). No trades today.",
                size, self.max_range_size,
            )
            self.state = ORBState.DONE_FOR_DAY
            return None

        if self.min_range_size > 0 and size < self.min_range_size:
            logger.warning(
                "Opening range too narrow: %.2f pts (min %.2f). No trades today.",
                size, self.min_range_size,
            )
            self.state = ORBState.DONE_FOR_DAY
            return None

        self.state = ORBState.RANGE_SET
        logger.info(
            "Opening range set — High: %.2f  Low: %.2f  Size: %.2f pts",
            orb_high, orb_low, size,
        )
        return None

    def _check_breakout(self, bar: PriceBar) -> Trade | None:
        if self._is_daily_limit_hit():
            self.state = ORBState.DONE_FOR_DAY
            return None

        orb = self.opening_range
        breakout_high = orb.high + self.breakout_buffer
        breakout_low = orb.low - self.breakout_buffer

        if self.wait_for_retest and self._retest_pending:
            return self._check_retest(bar)

        is_break_above = (
            bar.close > breakout_high if self.breakout_trigger == "close"
            else bar.high > breakout_high
        )
        is_break_below = (
            bar.close < breakout_low if self.breakout_trigger == "close"
            else bar.low < breakout_low
        )

        if is_break_above:
            if self.wait_for_retest:
                self._retest_pending = Direction.LONG
                logger.info("Breakout above %.2f — waiting for retest", breakout_high)
                return None
            return self._enter_trade(bar, Direction.LONG)

        if is_break_below:
            if self.wait_for_retest:
                self._retest_pending = Direction.SHORT
                logger.info("Breakout below %.2f — waiting for retest", breakout_low)
                return None
            return self._enter_trade(bar, Direction.SHORT)

        return None

    def _check_retest(self, bar: PriceBar) -> Trade | None:
        orb = self.opening_range

        if self._retest_pending == Direction.LONG:
            if bar.low <= orb.high and bar.close > orb.high:
                self._retest_pending = None
                return self._enter_trade(bar, Direction.LONG)

        elif self._retest_pending == Direction.SHORT:
            if bar.high >= orb.low and bar.close < orb.low:
                self._retest_pending = None
                return self._enter_trade(bar, Direction.SHORT)

        return None

    def _enter_trade(self, bar: PriceBar, direction: Direction) -> Trade:
        orb = self.opening_range
        entry_price = bar.close

        if direction == Direction.LONG:
            stop_loss = orb.low - self.stop_loss_buffer
            risk = entry_price - stop_loss
            if self.fixed_profit_target > 0:
                profit_target = entry_price + self.fixed_profit_target
            else:
                profit_target = entry_price + (risk * self.profit_target_rr)
        else:
            stop_loss = orb.high + self.stop_loss_buffer
            risk = stop_loss - entry_price
            if self.fixed_profit_target > 0:
                profit_target = entry_price - self.fixed_profit_target
            else:
                profit_target = entry_price - (risk * self.profit_target_rr)

        trade = Trade(
            entry_time=bar.timestamp,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            profit_target=profit_target,
            size=self.position_size,
            status=TradeStatus.OPEN,
        )

        self.current_trade = trade
        self.state = ORBState.IN_TRADE
        self._trailing_stop = None

        logger.info(
            "ENTRY %s @ %.2f | SL: %.2f | TP: %.2f | Risk: %.2f pts",
            direction.value, entry_price, stop_loss, profit_target, risk,
        )
        return trade

    def _manage_trade(self, bar: PriceBar) -> Trade | None:
        trade = self.current_trade
        if trade is None:
            return None

        if trade.direction == Direction.LONG:
            return self._manage_long(bar, trade)
        else:
            return self._manage_short(bar, trade)

    def _manage_long(self, bar: PriceBar, trade: Trade) -> Trade | None:
        if self.use_trailing_stop:
            self._update_trailing_stop_long(bar, trade)

        effective_stop = trade.stop_loss
        if self._trailing_stop is not None:
            effective_stop = max(effective_stop, self._trailing_stop)

        if bar.low <= effective_stop:
            reason = "trailing stop" if self._trailing_stop and effective_stop == self._trailing_stop else "stop loss"
            return self._exit_trade(bar, effective_stop, reason)

        if bar.high >= trade.profit_target:
            return self._exit_trade(bar, trade.profit_target, "profit target")

        return None

    def _manage_short(self, bar: PriceBar, trade: Trade) -> Trade | None:
        if self.use_trailing_stop:
            self._update_trailing_stop_short(bar, trade)

        effective_stop = trade.stop_loss
        if self._trailing_stop is not None:
            effective_stop = min(effective_stop, self._trailing_stop)

        if bar.high >= effective_stop:
            reason = "trailing stop" if self._trailing_stop and effective_stop == self._trailing_stop else "stop loss"
            return self._exit_trade(bar, effective_stop, reason)

        if bar.low <= trade.profit_target:
            return self._exit_trade(bar, trade.profit_target, "profit target")

        return None

    def _update_trailing_stop_long(self, bar: PriceBar, trade: Trade) -> None:
        risk = trade.entry_price - trade.stop_loss
        if bar.high >= trade.entry_price + risk:
            new_trail = bar.high - self.trailing_stop_distance
            if self._trailing_stop is None or new_trail > self._trailing_stop:
                self._trailing_stop = new_trail

    def _update_trailing_stop_short(self, bar: PriceBar, trade: Trade) -> None:
        risk = trade.stop_loss - trade.entry_price
        if bar.low <= trade.entry_price - risk:
            new_trail = bar.low + self.trailing_stop_distance
            if self._trailing_stop is None or new_trail < self._trailing_stop:
                self._trailing_stop = new_trail

    def _exit_trade(self, bar: PriceBar, exit_price: float, reason: str) -> Trade:
        trade = self.current_trade
        trade.exit_time = bar.timestamp
        trade.exit_price = exit_price
        trade.exit_reason = reason
        trade.status = TradeStatus.CLOSED
        trade.calculate_pnl(self.point_value)
        self.daily_stats.update(trade)

        logger.info(
            "EXIT %s @ %.2f | Reason: %s | PnL: %.2f pts ($%.2f)",
            trade.direction.value, exit_price, reason,
            trade.pnl_points, trade.pnl_dollars,
        )

        self.current_trade = None
        self._trailing_stop = None
        self.state = ORBState.RANGE_SET
        return trade

    def _handle_session_end(self, bar: PriceBar) -> Trade | None:
        result = None
        if self.current_trade and self.current_trade.status == TradeStatus.OPEN:
            result = self._exit_trade(bar, bar.close, "session end")
        self.state = ORBState.DONE_FOR_DAY
        logger.info(
            "Session ended — PnL: %.2f pts ($%.2f) | W: %d L: %d",
            self.daily_stats.total_pnl_points,
            self.daily_stats.total_pnl_dollars,
            self.daily_stats.winners,
            self.daily_stats.losers,
        )
        return result

    def _is_daily_limit_hit(self) -> bool:
        if len(self.daily_stats.trades) >= self.max_trades_per_day:
            logger.info("Max trades per day reached (%d)", self.max_trades_per_day)
            return True
        if abs(self.daily_stats.total_pnl_points) >= self.max_daily_loss:
            logger.info(
                "Daily loss limit hit: %.2f pts", self.daily_stats.total_pnl_points
            )
            return True
        return False
