"""Live / paper trading runner for the ORB strategy.

This module provides the framework for running the strategy in real-time.
You must implement a data feed adapter for your broker/data provider.
The included PaperBroker simulates order execution for testing.
"""

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime

import pytz

from .journal import write_trade
from .models import PriceBar, TradeStatus
from .strategy import ORBStrategy

logger = logging.getLogger(__name__)

ET = pytz.timezone("US/Eastern")


class DataFeed(ABC):
    """Base class for market data feeds. Implement for your data provider."""

    @abstractmethod
    def get_latest_bar(self) -> PriceBar | None:
        """Return the latest completed price bar, or None if unavailable."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        ...


class Broker(ABC):
    """Base class for order execution. Implement for your broker."""

    @abstractmethod
    def submit_market_order(self, symbol: str, quantity: int, side: str) -> str:
        """Submit a market order. Returns order ID."""
        ...

    @abstractmethod
    def submit_bracket_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        stop_loss: float,
        profit_target: float,
    ) -> str:
        """Submit a bracket order with stop and target. Returns order ID."""
        ...

    @abstractmethod
    def cancel_all_orders(self, symbol: str) -> None:
        ...

    @abstractmethod
    def flatten_position(self, symbol: str) -> None:
        ...


class PaperBroker(Broker):
    """Simulated broker for paper trading."""

    def __init__(self):
        self.orders: list[dict] = []
        self._order_counter = 0

    def submit_market_order(self, symbol: str, quantity: int, side: str) -> str:
        self._order_counter += 1
        order_id = f"PAPER-{self._order_counter}"
        order = {
            "id": order_id,
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "type": "MARKET",
            "status": "FILLED",
        }
        self.orders.append(order)
        logger.info("[PAPER] Market order %s: %s %d %s", order_id, side, quantity, symbol)
        return order_id

    def submit_bracket_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        stop_loss: float,
        profit_target: float,
    ) -> str:
        self._order_counter += 1
        order_id = f"PAPER-{self._order_counter}"
        order = {
            "id": order_id,
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "type": "BRACKET",
            "stop_loss": stop_loss,
            "profit_target": profit_target,
            "status": "FILLED",
        }
        self.orders.append(order)
        logger.info(
            "[PAPER] Bracket order %s: %s %d %s | SL: %.2f | TP: %.2f",
            order_id, side, quantity, symbol, stop_loss, profit_target,
        )
        return order_id

    def cancel_all_orders(self, symbol: str) -> None:
        logger.info("[PAPER] All orders cancelled for %s", symbol)

    def flatten_position(self, symbol: str) -> None:
        logger.info("[PAPER] Position flattened for %s", symbol)


class LiveRunner:
    """Runs the ORB strategy against a live or simulated data feed."""

    def __init__(
        self,
        config: dict,
        data_feed: DataFeed,
        broker: Broker,
        symbol: str = "ES",
    ):
        self.config = config
        self.strategy = ORBStrategy(config)
        self.data_feed = data_feed
        self.broker = broker
        self.symbol = symbol
        self.journal_path = config["logging"]["trade_journal"]
        self.is_paper = config["trading"]["paper_trade"]
        self._running = False

    def run(self, poll_interval_sec: float = 5.0) -> None:
        self._running = True
        today = datetime.now(ET).strftime("%Y-%m-%d")
        self.strategy.reset_day(today)

        mode = "PAPER" if self.is_paper else "LIVE"
        logger.info("Starting %s trading session for %s on %s", mode, self.symbol, today)

        while self._running:
            if not self.data_feed.is_connected():
                logger.warning("Data feed disconnected, retrying in 5s...")
                time.sleep(5)
                continue

            bar = self.data_feed.get_latest_bar()
            if bar is None:
                time.sleep(poll_interval_sec)
                continue

            trade = self.strategy.on_bar(bar)
            if trade:
                self._handle_trade_signal(trade)

            if self.strategy.state.value == "DONE_FOR_DAY":
                logger.info("Trading session complete for the day.")
                break

            time.sleep(poll_interval_sec)

    def stop(self) -> None:
        self._running = False
        self.broker.cancel_all_orders(self.symbol)
        self.broker.flatten_position(self.symbol)
        logger.info("Runner stopped. All positions flattened.")

    def _handle_trade_signal(self, trade) -> None:
        if trade.status == TradeStatus.OPEN:
            side = "BUY" if trade.direction.value == "LONG" else "SELL"
            self.broker.submit_bracket_order(
                symbol=self.symbol,
                quantity=trade.size,
                side=side,
                stop_loss=trade.stop_loss,
                profit_target=trade.profit_target,
            )

        elif trade.status == TradeStatus.CLOSED:
            self.broker.cancel_all_orders(self.symbol)
            if trade.exit_reason == "session end":
                self.broker.flatten_position(self.symbol)
            write_trade(self.journal_path, trade)
            logger.info(
                "Trade logged: %s %.2f pts ($%.2f)",
                trade.exit_reason,
                trade.pnl_points,
                trade.pnl_dollars,
            )
