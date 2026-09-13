import logging
from datetime import datetime, time

import pytz

from .models import (
    DailyStats,
    Direction,
    ORBState,
    OpeningRange,
    PriceBar,
    Trade,
    TradeStatus,
)

logger = logging.getLogger(__name__)

ET = pytz.timezone("US/Eastern")


class ORBStrategy:
    """Opening Range Breakout strategy for ES futures.

    Tracks the first 30 minutes of the NYSE open (9:30-10:00 ET),
    then trades breakouts above the high or below the low of that range.
    """

    def __init__(self, config: dict):
        strat = config["strategy"]
        risk = config["risk"]
        trading = config["trading"]

        self.orb_start = self._parse_time(strat["orb_start"])
        self.orb_end = self._parse_time(strat["orb_end"])
        self.breakout_buffer = strat["breakout_buffer_ticks"] * trading["tick_size"]
        self.max_range_size = strat["max_range_size"]
        self.min_range_size = strat["min_range_size"]
        self.wait_for_retest = strat["wait_for_retest"]

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

    @staticmethod
    def _parse_time(t: str) -> time:
        parts = t.split(":")
        return time(int(parts[0]), int(parts[1]))

    def _get_et_time(self, dt: datetime) -> time:
        if dt.tzinfo is None:
            dt = ET.localize(dt)
        else:
            dt = dt.astimezone(ET)
        return dt.time()

    def reset_day(self, date_str: str = "") -> None:
        self.state = ORBState.WAITING_FOR_OPEN
        self.opening_range.reset()
        self.current_trade = None
        self.daily_stats = DailyStats(date=date_str)
        self._trailing_stop = None
        self._retest_pending = None
        logger.info("Day reset: %s", date_str)

    def on_bar(self, bar: PriceBar) -> Trade | None:
        """Process a new price bar. Returns a Trade if one was opened or closed."""
        et_time = self._get_et_time(bar.timestamp)

        if self.state == ORBState.DONE_FOR_DAY:
            return None

        if et_time >= self.session_end:
            return self._handle_session_end(bar)

        if self.state == ORBState.WAITING_FOR_OPEN:
            if et_time >= self.orb_start:
                self.state = ORBState.BUILDING_RANGE
                logger.info("Market open - building opening range")
                self.opening_range.update(bar)
            return None

        if self.state == ORBState.BUILDING_RANGE:
            self.opening_range.update(bar)
            if et_time >= self.orb_end:
                return self._finalize_range()
            return None

        if self.state == ORBState.RANGE_SET:
            return self._check_breakout(bar)

        if self.state == ORBState.IN_TRADE:
            return self._manage_trade(bar)

        return None

    def _finalize_range(self) -> None:
        self.opening_range.established = True
        size = self.opening_range.size

        if size > self.max_range_size:
            logger.warning(
                "Opening range too wide: %.2f pts (max %.2f). No trades today.",
                size,
                self.max_range_size,
            )
            self.state = ORBState.DONE_FOR_DAY
            return None

        if size < self.min_range_size:
            logger.warning(
                "Opening range too narrow: %.2f pts (min %.2f). No trades today.",
                size,
                self.min_range_size,
            )
            self.state = ORBState.DONE_FOR_DAY
            return None

        self.state = ORBState.RANGE_SET
        logger.info(
            "Opening range established — High: %.2f  Low: %.2f  Size: %.2f pts",
            self.opening_range.high,
            self.opening_range.low,
            size,
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

        if bar.close > breakout_high:
            if self.wait_for_retest:
                self._retest_pending = Direction.LONG
                logger.info("Breakout above %.2f — waiting for retest", breakout_high)
                return None
            return self._enter_trade(bar, Direction.LONG)

        if bar.close < breakout_low:
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
            direction.value,
            entry_price,
            stop_loss,
            profit_target,
            risk,
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
                logger.debug("Trailing stop updated to %.2f", new_trail)

    def _update_trailing_stop_short(self, bar: PriceBar, trade: Trade) -> None:
        risk = trade.stop_loss - trade.entry_price
        if bar.low <= trade.entry_price - risk:
            new_trail = bar.low + self.trailing_stop_distance
            if self._trailing_stop is None or new_trail < self._trailing_stop:
                self._trailing_stop = new_trail
                logger.debug("Trailing stop updated to %.2f", new_trail)

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
            trade.direction.value,
            exit_price,
            reason,
            trade.pnl_points,
            trade.pnl_dollars,
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
