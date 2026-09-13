import pytest
import pytz
from datetime import datetime

from orb_bot.models import PriceBar, Direction, TradeStatus, ORBState
from orb_bot.strategy import ORBStrategy

ET = pytz.timezone("US/Eastern")


def make_config(**overrides):
    config = {
        "strategy": {
            "orb_start": "09:30",
            "orb_end": "10:00",
            "orb_candle_minutes": 15,
            "breakout_trigger": "close",
            "breakout_buffer_ticks": 0,
            "max_range_size": 0,
            "min_range_size": 0,
            "wait_for_retest": False,
        },
        "risk": {
            "stop_loss_buffer": 0.0,
            "profit_target_rr": 2.0,
            "fixed_profit_target": 0,
            "max_daily_loss": 20.0,
            "position_size": 1,
            "max_trades_per_day": 2,
            "use_trailing_stop": False,
            "trailing_stop_distance": 3.0,
        },
        "trading": {
            "session_end": "15:45",
            "paper_trade": True,
            "tick_size": 0.25,
            "tick_value": 12.50,
            "point_value": 50.0,
        },
    }
    for key, val in overrides.items():
        section, param = key.split(".")
        config[section][param] = val
    return config


def bar(hour, minute, o, h, l, c, day=6):
    dt = ET.localize(datetime(2025, 1, day, hour, minute))
    return PriceBar(timestamp=dt, open=o, high=h, low=l, close=c)


def build_range(strategy, candle1_high=5510, candle1_low=5497,
                candle2_high=5508, candle2_low=5499):
    """Feed bars to build the two 15-min candles that form the opening range.

    Feeds 1-min bars at 9:30 and 9:44 for candle 1, then 9:45 and 9:59 for
    candle 2, then a bar at 10:00 to trigger finalization.
    The resulting range high = max(candle1_high, candle2_high),
    range low = min(candle1_low, candle2_low).
    """
    strategy.reset_day("2025-01-06")

    # Candle 1: 9:30 - 9:44
    strategy.on_bar(bar(9, 30, 5500, candle1_high, candle1_low, 5502))
    strategy.on_bar(bar(9, 44, 5502, candle1_high, candle1_low, 5505))

    # Candle 2: 9:45 - 9:59
    strategy.on_bar(bar(9, 45, 5505, candle2_high, candle2_low, 5504))
    strategy.on_bar(bar(9, 59, 5504, candle2_high, candle2_low, 5503))

    # 10:00 bar triggers finalization of candle 2 and range
    strategy.on_bar(bar(10, 0, 5503, 5504, 5502, 5503))


class TestOpeningRange:
    def test_range_builds_from_two_15min_candles(self):
        strategy = ORBStrategy(make_config())
        strategy.reset_day("2025-01-06")

        # First bar starts candle building
        strategy.on_bar(bar(9, 30, 5500, 5505, 5498, 5502))
        assert strategy.state == ORBState.BUILDING_RANGE

        # Still in first 15-min candle
        strategy.on_bar(bar(9, 44, 5502, 5510, 5497, 5508))
        assert strategy.state == ORBState.BUILDING_RANGE

    def test_range_finalizes_after_two_candles(self):
        strategy = ORBStrategy(make_config())
        build_range(strategy, candle1_high=5510, candle1_low=5497,
                    candle2_high=5508, candle2_low=5499)

        assert strategy.state == ORBState.RANGE_SET
        assert strategy.opening_range.established
        assert strategy.opening_range.high == 5510  # max of both candles
        assert strategy.opening_range.low == 5497    # min of both candles

    def test_range_uses_highest_high_lowest_low(self):
        strategy = ORBStrategy(make_config())
        # Candle 2 has the highest high, candle 1 has the lowest low
        build_range(strategy, candle1_high=5505, candle1_low=5490,
                    candle2_high=5515, candle2_low=5495)

        assert strategy.opening_range.high == 5515
        assert strategy.opening_range.low == 5490

    def test_range_too_wide_skips_day(self):
        config = make_config(**{"strategy.max_range_size": 5.0})
        strategy = ORBStrategy(config)
        build_range(strategy, candle1_high=5510, candle1_low=5497)

        assert strategy.state == ORBState.DONE_FOR_DAY

    def test_range_too_narrow_skips_day(self):
        config = make_config(**{"strategy.min_range_size": 20.0})
        strategy = ORBStrategy(config)
        build_range(strategy, candle1_high=5505, candle1_low=5500,
                    candle2_high=5504, candle2_low=5501)

        assert strategy.state == ORBState.DONE_FOR_DAY

    def test_no_range_filter_when_zero(self):
        """max/min of 0 means no filter applied."""
        config = make_config(**{"strategy.max_range_size": 0, "strategy.min_range_size": 0})
        strategy = ORBStrategy(config)
        build_range(strategy, candle1_high=5550, candle1_low=5450)

        assert strategy.state == ORBState.RANGE_SET


class TestBreakout:
    def test_long_breakout_on_close(self):
        strategy = ORBStrategy(make_config())
        build_range(strategy, candle1_high=5510, candle1_low=5497)
        # Range high is 5510, close above it triggers long
        trade = strategy.on_bar(bar(10, 5, 5509, 5512, 5508, 5511))
        assert trade is not None
        assert trade.direction == Direction.LONG
        assert trade.status == TradeStatus.OPEN
        assert trade.entry_price == 5511
        assert trade.stop_loss == 5497  # opposite end, no buffer

    def test_short_breakout_on_close(self):
        strategy = ORBStrategy(make_config())
        build_range(strategy, candle1_high=5510, candle1_low=5497)
        # Range low is 5497, close below it triggers short
        trade = strategy.on_bar(bar(10, 5, 5498, 5499, 5495, 5496))
        assert trade is not None
        assert trade.direction == Direction.SHORT
        assert trade.status == TradeStatus.OPEN
        assert trade.stop_loss == 5510  # opposite end, no buffer

    def test_breakout_with_buffer(self):
        config = make_config(**{"strategy.breakout_buffer_ticks": 2})
        strategy = ORBStrategy(config)
        build_range(strategy, candle1_high=5510, candle1_low=5497)

        # Close at 5510.25 is NOT above 5510 + 0.50 buffer
        trade = strategy.on_bar(bar(10, 5, 5509, 5511, 5508, 5510.25))
        assert trade is None

        # Close at 5510.75 IS above 5510.50
        trade = strategy.on_bar(bar(10, 6, 5510, 5512, 5509, 5510.75))
        assert trade is not None
        assert trade.direction == Direction.LONG

    def test_no_breakout_stays_in_range(self):
        strategy = ORBStrategy(make_config())
        build_range(strategy, candle1_high=5510, candle1_low=5497)

        trade = strategy.on_bar(bar(10, 5, 5500, 5508, 5499, 5505))
        assert trade is None
        assert strategy.state == ORBState.RANGE_SET

    def test_wick_breakout_trigger(self):
        config = make_config(**{"strategy.breakout_trigger": "wick"})
        strategy = ORBStrategy(config)
        build_range(strategy, candle1_high=5510, candle1_low=5497)

        # High > 5510 triggers even though close is below
        trade = strategy.on_bar(bar(10, 5, 5508, 5511, 5507, 5509))
        assert trade is not None
        assert trade.direction == Direction.LONG


class TestStopLoss:
    def test_long_stop_at_range_low(self):
        strategy = ORBStrategy(make_config())
        build_range(strategy, candle1_high=5510, candle1_low=5497)
        strategy.on_bar(bar(10, 5, 5509, 5512, 5508, 5511))

        assert strategy.current_trade.stop_loss == 5497

    def test_short_stop_at_range_high(self):
        strategy = ORBStrategy(make_config())
        build_range(strategy, candle1_high=5510, candle1_low=5497)
        strategy.on_bar(bar(10, 5, 5498, 5499, 5495, 5496))

        assert strategy.current_trade.stop_loss == 5510

    def test_stop_loss_with_buffer(self):
        config = make_config(**{"risk.stop_loss_buffer": 1.0})
        strategy = ORBStrategy(config)
        build_range(strategy, candle1_high=5510, candle1_low=5497)
        strategy.on_bar(bar(10, 5, 5509, 5512, 5508, 5511))

        assert strategy.current_trade.stop_loss == 5496  # 5497 - 1.0


class TestTradeManagement:
    def _enter_long(self, strategy):
        build_range(strategy, candle1_high=5510, candle1_low=5497)
        strategy.on_bar(bar(10, 5, 5509, 5512, 5508, 5511))

    def test_stop_loss_hit(self):
        strategy = ORBStrategy(make_config())
        self._enter_long(strategy)

        stop = strategy.current_trade.stop_loss  # 5497
        trade = strategy.on_bar(bar(10, 10, 5505, 5506, stop - 1, 5498))
        assert trade is not None
        assert trade.status == TradeStatus.CLOSED
        assert trade.exit_reason == "stop loss"
        assert trade.pnl_points < 0

    def test_profit_target_hit(self):
        strategy = ORBStrategy(make_config())
        self._enter_long(strategy)

        target = strategy.current_trade.profit_target
        trade = strategy.on_bar(bar(10, 10, 5515, target + 2, 5514, 5520))
        assert trade is not None
        assert trade.status == TradeStatus.CLOSED
        assert trade.exit_reason == "profit target"
        assert trade.pnl_points > 0

    def test_session_end_flattens(self):
        strategy = ORBStrategy(make_config())
        self._enter_long(strategy)

        trade = strategy.on_bar(bar(15, 45, 5515, 5516, 5514, 5515))
        assert trade is not None
        assert trade.status == TradeStatus.CLOSED
        assert trade.exit_reason == "session end"
        assert strategy.state == ORBState.DONE_FOR_DAY

    def test_max_trades_per_day(self):
        config = make_config(**{"risk.max_trades_per_day": 1})
        strategy = ORBStrategy(config)
        build_range(strategy, candle1_high=5510, candle1_low=5497)
        strategy.on_bar(bar(10, 5, 5509, 5512, 5508, 5511))

        # Close the trade via stop
        stop = strategy.current_trade.stop_loss
        strategy.on_bar(bar(10, 10, 5505, 5506, stop - 1, 5498))

        # Attempt second breakout — should be blocked
        trade = strategy.on_bar(bar(10, 15, 5509, 5512, 5508, 5511))
        assert trade is None
        assert strategy.state == ORBState.DONE_FOR_DAY


class TestPnLCalculation:
    def test_long_winner_pnl(self):
        strategy = ORBStrategy(make_config())
        build_range(strategy, candle1_high=5510, candle1_low=5497)
        strategy.on_bar(bar(10, 5, 5509, 5512, 5508, 5511))

        target = strategy.current_trade.profit_target
        trade = strategy.on_bar(bar(10, 10, 5515, target + 2, 5514, target))
        assert trade.pnl_points == pytest.approx(target - 5511, abs=0.01)
        assert trade.pnl_dollars == pytest.approx(trade.pnl_points * 50.0, abs=0.01)

    def test_short_loser_pnl(self):
        strategy = ORBStrategy(make_config())
        build_range(strategy, candle1_high=5510, candle1_low=5497)
        # Short entry
        strategy.on_bar(bar(10, 5, 5498, 5499, 5495, 5496))

        stop = strategy.current_trade.stop_loss  # 5510
        trade = strategy.on_bar(bar(10, 10, 5500, stop + 1, 5499, 5512))
        assert trade.pnl_points < 0
        assert trade.exit_reason == "stop loss"
