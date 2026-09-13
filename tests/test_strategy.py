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
            "breakout_buffer_ticks": 2,
            "max_range_size": 15.0,
            "min_range_size": 2.0,
            "wait_for_retest": False,
        },
        "risk": {
            "stop_loss_buffer": 1.0,
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


class TestOpeningRange:
    def test_range_builds_during_first_30_min(self):
        strategy = ORBStrategy(make_config())
        strategy.reset_day("2025-01-06")

        strategy.on_bar(bar(9, 30, 5500, 5505, 5498, 5502))
        assert strategy.state == ORBState.BUILDING_RANGE

        strategy.on_bar(bar(9, 45, 5502, 5510, 5497, 5508))
        assert strategy.state == ORBState.BUILDING_RANGE
        assert strategy.opening_range.high == 5510
        assert strategy.opening_range.low == 5497

    def test_range_finalizes_at_10am(self):
        strategy = ORBStrategy(make_config())
        strategy.reset_day("2025-01-06")

        strategy.on_bar(bar(9, 30, 5500, 5505, 5498, 5502))
        strategy.on_bar(bar(9, 45, 5502, 5510, 5497, 5508))
        strategy.on_bar(bar(10, 0, 5508, 5509, 5500, 5505))

        assert strategy.state == ORBState.RANGE_SET
        assert strategy.opening_range.established
        assert strategy.opening_range.high == 5510
        assert strategy.opening_range.low == 5497

    def test_range_too_wide_skips_day(self):
        config = make_config(**{"strategy.max_range_size": 5.0})
        strategy = ORBStrategy(config)
        strategy.reset_day("2025-01-06")

        strategy.on_bar(bar(9, 30, 5500, 5510, 5498, 5502))
        strategy.on_bar(bar(10, 0, 5502, 5510, 5498, 5505))

        assert strategy.state == ORBState.DONE_FOR_DAY

    def test_range_too_narrow_skips_day(self):
        config = make_config(**{"strategy.min_range_size": 5.0})
        strategy = ORBStrategy(config)
        strategy.reset_day("2025-01-06")

        strategy.on_bar(bar(9, 30, 5500, 5501, 5499, 5500))
        strategy.on_bar(bar(10, 0, 5500, 5501, 5499, 5500))

        assert strategy.state == ORBState.DONE_FOR_DAY


class TestBreakout:
    def _build_range(self, strategy, high=5510, low=5497):
        strategy.reset_day("2025-01-06")
        strategy.on_bar(bar(9, 30, 5500, high, low, 5502))
        strategy.on_bar(bar(10, 0, 5502, high, low, 5505))

    def test_long_breakout(self):
        strategy = ORBStrategy(make_config())
        self._build_range(strategy)

        # Buffer = 2 ticks * 0.25 = 0.50, so need close > 5510.50
        trade = strategy.on_bar(bar(10, 5, 5509, 5512, 5508, 5511))
        assert trade is not None
        assert trade.direction == Direction.LONG
        assert trade.status == TradeStatus.OPEN
        assert trade.entry_price == 5511
        assert trade.stop_loss == 5497 - 1.0  # low - buffer

    def test_short_breakout(self):
        strategy = ORBStrategy(make_config())
        self._build_range(strategy)

        # Need close < 5496.50
        trade = strategy.on_bar(bar(10, 5, 5498, 5499, 5495, 5496))
        assert trade is not None
        assert trade.direction == Direction.SHORT
        assert trade.status == TradeStatus.OPEN
        assert trade.stop_loss == 5510 + 1.0  # high + buffer

    def test_no_breakout_stays_in_range(self):
        strategy = ORBStrategy(make_config())
        self._build_range(strategy)

        trade = strategy.on_bar(bar(10, 5, 5500, 5508, 5499, 5505))
        assert trade is None
        assert strategy.state == ORBState.RANGE_SET


class TestTradeManagement:
    def _enter_long(self, strategy):
        strategy.reset_day("2025-01-06")
        strategy.on_bar(bar(9, 30, 5500, 5510, 5497, 5502))
        strategy.on_bar(bar(10, 0, 5502, 5510, 5497, 5505))
        strategy.on_bar(bar(10, 5, 5509, 5512, 5508, 5511))

    def test_stop_loss_hit(self):
        strategy = ORBStrategy(make_config())
        self._enter_long(strategy)

        stop = strategy.current_trade.stop_loss
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
        strategy.reset_day("2025-01-06")

        strategy.on_bar(bar(9, 30, 5500, 5510, 5497, 5502))
        strategy.on_bar(bar(10, 0, 5502, 5510, 5497, 5505))
        strategy.on_bar(bar(10, 5, 5509, 5512, 5508, 5511))

        # Close the trade via stop
        stop = strategy.current_trade.stop_loss
        strategy.on_bar(bar(10, 10, 5505, 5506, stop - 1, 5498))

        # Attempt second breakout
        trade = strategy.on_bar(bar(10, 15, 5509, 5512, 5508, 5511))
        assert trade is None
        assert strategy.state == ORBState.DONE_FOR_DAY


class TestPnLCalculation:
    def test_long_winner_pnl(self):
        strategy = ORBStrategy(make_config())
        strategy.reset_day("2025-01-06")

        strategy.on_bar(bar(9, 30, 5500, 5510, 5497, 5502))
        strategy.on_bar(bar(10, 0, 5502, 5510, 5497, 5505))
        strategy.on_bar(bar(10, 5, 5509, 5512, 5508, 5511))

        target = strategy.current_trade.profit_target
        trade = strategy.on_bar(bar(10, 10, 5515, target + 2, 5514, target))
        assert trade.pnl_points == pytest.approx(target - 5511, abs=0.01)
        assert trade.pnl_dollars == pytest.approx(trade.pnl_points * 50.0, abs=0.01)

    def test_short_loser_pnl(self):
        strategy = ORBStrategy(make_config())
        strategy.reset_day("2025-01-06")

        strategy.on_bar(bar(9, 30, 5500, 5510, 5497, 5502))
        strategy.on_bar(bar(10, 0, 5502, 5510, 5497, 5505))
        # Short entry
        strategy.on_bar(bar(10, 5, 5498, 5499, 5495, 5496))

        stop = strategy.current_trade.stop_loss
        trade = strategy.on_bar(bar(10, 10, 5500, stop + 1, 5499, 5512))
        assert trade.pnl_points < 0
        assert trade.exit_reason == "stop loss"
