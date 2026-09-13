"""Tradovate REST API client for order execution.

Handles authentication, market data, and bracket order placement
for the ORB strategy. Supports both demo and live environments.

Requires credentials in .env or config.yaml — see .env.example.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)


class TradovateClient:
    def __init__(self, config: dict):
        tv = config["tradovate"]
        self.username = tv["username"]
        self.password = tv["password"]
        self.app_id = tv["app_id"]
        self.app_version = tv.get("app_version", "1.0")
        self.cid = tv["cid"]
        self.sec = tv["sec"]
        self.demo = tv.get("demo", True)

        if self.demo:
            self.base_url = "https://demo.tradovateapi.com/v1"
        else:
            self.base_url = "https://live.tradovateapi.com/v1"

        self.access_token: str | None = None
        self.token_expiry: float = 0
        self._account_id: int | None = None

    def authenticate(self) -> None:
        url = f"{self.base_url}/auth/accesstokenrequest"
        payload = {
            "name": self.username,
            "password": self.password,
            "appId": self.app_id,
            "appVersion": self.app_version,
            "cid": self.cid,
            "sec": self.sec,
        }

        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json()

        self.access_token = data["accessToken"]
        self.token_expiry = time.time() + data.get("expirationTime", 7200)

        logger.info("Authenticated with Tradovate (%s)", "demo" if self.demo else "live")

    def _ensure_auth(self) -> None:
        if self.access_token is None or time.time() >= self.token_expiry - 60:
            self.authenticate()

    def _headers(self) -> dict:
        self._ensure_auth()
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _get(self, endpoint: str) -> dict:
        resp = requests.get(f"{self.base_url}{endpoint}", headers=self._headers(), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint: str, payload: dict) -> dict:
        resp = requests.post(
            f"{self.base_url}{endpoint}",
            headers=self._headers(),
            json=payload,
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()

    def get_account_id(self) -> int:
        if self._account_id is not None:
            return self._account_id
        accounts = self._get("/account/list")
        if not accounts:
            raise RuntimeError("No Tradovate accounts found")
        self._account_id = accounts[0]["id"]
        return self._account_id

    def get_contract_id(self, symbol: str = "ESZ4") -> int:
        result = self._get(f"/contract/find?name={symbol}")
        return result["id"]

    def place_market_order(self, symbol: str, quantity: int, side: str) -> dict:
        account_id = self.get_account_id()
        action = "Buy" if side.upper() == "BUY" else "Sell"

        payload = {
            "accountSpec": self.username,
            "accountId": account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": quantity,
            "orderType": "Market",
            "isAutomated": True,
        }

        result = self._post("/order/placeorder", payload)
        logger.info("Market order placed: %s %d %s — %s", action, quantity, symbol, result)
        return result

    def place_bracket_order(
        self,
        symbol: str,
        quantity: int,
        side: str,
        stop_loss: float,
        profit_target: float,
    ) -> dict:
        account_id = self.get_account_id()
        action = "Buy" if side.upper() == "BUY" else "Sell"
        exit_action = "Sell" if action == "Buy" else "Buy"

        payload = {
            "accountSpec": self.username,
            "accountId": account_id,
            "action": action,
            "symbol": symbol,
            "orderQty": quantity,
            "orderType": "Market",
            "isAutomated": True,
            "bracket1": {
                "action": exit_action,
                "orderType": "Limit",
                "price": profit_target,
            },
            "bracket2": {
                "action": exit_action,
                "orderType": "Stop",
                "stopPrice": stop_loss,
            },
        }

        result = self._post("/order/placeorder", payload)
        logger.info(
            "Bracket order placed: %s %d %s | SL: %.2f | TP: %.2f — %s",
            action, quantity, symbol, stop_loss, profit_target, result,
        )
        return result

    def cancel_all_orders(self) -> dict:
        account_id = self.get_account_id()
        return self._post("/order/cancelall", {"accountId": account_id})

    def flatten_position(self, symbol: str) -> dict:
        account_id = self.get_account_id()
        return self._post("/order/liquidateposition", {
            "accountId": account_id,
            "symbol": symbol,
        })

    def get_positions(self) -> list[dict]:
        return self._get("/position/list")
