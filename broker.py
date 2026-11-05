"""Client minimal pour l'API Alpaca (courtage + données de marché)."""
import os
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

PAPER_URL = "https://paper-api.alpaca.markets"
LIVE_URL = "https://api.alpaca.markets"
DATA_URL = "https://data.alpaca.markets"


class Alpaca:
    def __init__(self, live: bool = False, timeout: int = 30):
        key = os.environ.get("ALPACA_API_KEY")
        secret = os.environ.get("ALPACA_SECRET_KEY")
        if not key or not secret:
            raise RuntimeError("Secrets ALPACA_API_KEY et ALPACA_SECRET_KEY manquants.")
        self.base = LIVE_URL if live else PAPER_URL
        self.live = live
        self.timeout = timeout
        self.s = requests.Session()
        self.s.headers.update({"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret})

    def _req(self, method: str, url: str, **kw):
        r = self.s.request(method, url, timeout=self.timeout, **kw)
        if r.status_code >= 400:
            raise RuntimeError(f"Alpaca {method} {url} -> {r.status_code}: {r.text[:300]}")
        return r.json() if r.content else {}

    # --- Compte ---
    def account(self) -> dict:
        return self._req("GET", f"{self.base}/v2/account")

    def clock(self) -> dict:
        return self._req("GET", f"{self.base}/v2/clock")

    def positions(self) -> dict:
        return {p["symbol"]: p for p in self._req("GET", f"{self.base}/v2/positions")}

    def asset(self, symbol: str) -> dict:
        return self._req("GET", f"{self.base}/v2/assets/{symbol}")

    # --- Ordres ---
    def buy(self, symbol: str, notional: float | None = None, qty: int | None = None) -> dict:
        order = {"symbol": symbol, "side": "buy", "type": "market", "time_in_force": "day"}
        if notional is not None:
            order["notional"] = f"{notional:.2f}"
        else:
            order["qty"] = str(qty)
        return self._req("POST", f"{self.base}/v2/orders", json=order)

    def close_position(self, symbol: str) -> dict:
        return self._req("DELETE", f"{self.base}/v2/positions/{symbol}")

    # --- Données ---
    def daily_closes(self, symbol: str, days: int = 500) -> pd.Series:
        start = (datetime.now(timezone.utc) - timedelta(days=int(days * 1.5))).strftime("%Y-%m-%d")
        params = {"timeframe": "1Day", "start": start, "limit": 10000,
                  "adjustment": "all", "feed": "iex"}
        bars, token = [], None
        while True:
            if token:
                params["page_token"] = token
            data = self._req("GET", f"{DATA_URL}/v2/stocks/{symbol}/bars", params=params)
            bars += data.get("bars") or []
            token = data.get("next_page_token")
            if not token:
                break
        if not bars:
            return pd.Series(dtype=float)
        return pd.Series([b["c"] for b in bars], index=pd.to_datetime([b["t"] for b in bars]))

    def headlines(self, symbol: str, limit: int = 10) -> list[str]:
        try:
            data = self._req("GET", f"{DATA_URL}/v1beta1/news",
                             params={"symbols": symbol, "limit": limit, "sort": "desc"})
        except RuntimeError:
            return []
        return [n["headline"] for n in data.get("news", []) if n.get("headline")]
