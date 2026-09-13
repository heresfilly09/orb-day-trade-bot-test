import os
from dataclasses import dataclass

import yaml
from dotenv import load_dotenv


@dataclass
class StrategyConfig:
    orb_start: str = "09:30"
    orb_end: str = "10:00"
    orb_candle_minutes: int = 15
    breakout_trigger: str = "close"
    breakout_buffer_ticks: int = 0
    max_range_size: float = 0
    min_range_size: float = 0
    wait_for_retest: bool = False


@dataclass
class RiskConfig:
    stop_loss_buffer: float = 0.0
    profit_target_rr: float = 2.0
    fixed_profit_target: float = 0
    max_daily_loss: float = 20.0
    position_size: int = 1
    max_trades_per_day: int = 2
    use_trailing_stop: bool = False
    trailing_stop_distance: float = 3.0


@dataclass
class TradingConfig:
    session_end: str = "15:45"
    paper_trade: bool = True
    tick_size: float = 0.25
    tick_value: float = 12.50
    point_value: float = 50.0


@dataclass
class TradovateConfig:
    username: str = ""
    password: str = ""
    app_id: str = ""
    app_version: str = "1.0"
    cid: int = 0
    sec: str = ""
    demo: bool = True

    @property
    def base_url(self) -> str:
        if self.demo:
            return "https://demo.tradovateapi.com/v1"
        return "https://live.tradovateapi.com/v1"

    @property
    def ws_url(self) -> str:
        if self.demo:
            return "wss://demo.tradovateapi.com/v1/websocket"
        return "wss://live.tradovateapi.com/v1/websocket"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    trade_journal: str = "orb_trades.csv"
    log_file: str = "orb_bot.log"


def load_config(path: str = "config.yaml") -> dict:
    load_dotenv()

    with open(path) as f:
        cfg = yaml.safe_load(f)

    tv = cfg.get("tradovate", {})
    cfg["tradovate"] = {
        "username": os.getenv("TRADOVATE_USERNAME", tv.get("username", "")),
        "password": os.getenv("TRADOVATE_PASSWORD", tv.get("password", "")),
        "app_id": os.getenv("TRADOVATE_APP_ID", tv.get("app_id", "")),
        "app_version": tv.get("app_version", "1.0"),
        "cid": int(os.getenv("TRADOVATE_CID", tv.get("cid", 0))),
        "sec": os.getenv("TRADOVATE_SEC", tv.get("sec", "")),
        "demo": tv.get("demo", True),
    }

    return cfg
