from __future__ import annotations

from datetime import datetime, timezone
import time
from typing import List

import httpx

from .base import MarketSignal, ProviderHealth


class YFinanceAdapter:
    name = "yfinance"

    def snapshot(self, ticker: str) -> List[MarketSignal]:
        if not ticker:
            return []
        try:
            import yfinance as yf
        except ImportError as exc:
            raise RuntimeError("yfinance package is not installed") from exc
        history = yf.Ticker(ticker).history(period="5d", interval="1d", auto_adjust=False)
        if history is None or len(history.index) < 2:
            return []
        current = float(history.iloc[-1]["Close"])
        previous = float(history.iloc[-2]["Close"])
        change = 0.0 if previous == 0 else (current - previous) / previous * 100
        return [MarketSignal(self.name, ticker, datetime.now(timezone.utc).isoformat(timespec="seconds"), current, previous, change)]

    def healthcheck(self) -> ProviderHealth:
        try:
            import yfinance  # noqa: F401
            return ProviderHealth(self.name, True, "yfinance import available")
        except ImportError:
            return ProviderHealth(self.name, False, "yfinance package is not installed")


class AlphaVantageAdapter:
    name = "alpha_vantage"
    endpoint = "https://www.alphavantage.co/query"

    def __init__(self, api_key: str, timeout_seconds: int = 30) -> None:
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds

    def snapshot(self, ticker: str) -> List[MarketSignal]:
        if not self.api_key:
            raise RuntimeError("Alpha Vantage API key is not configured")
        response = httpx.get(self.endpoint, params={"function": "GLOBAL_QUOTE", "symbol": ticker, "apikey": self.api_key}, timeout=self.timeout_seconds)
        response.raise_for_status()
        quote = response.json().get("Global Quote") or {}
        price = float(quote.get("05. price") or 0)
        previous = float(quote.get("08. previous close") or 0)
        if not price or not previous:
            return []
        change = (price - previous) / previous * 100
        return [MarketSignal(self.name, ticker, datetime.now(timezone.utc).isoformat(timespec="seconds"), price, previous, change, quote)]

    def healthcheck(self) -> ProviderHealth:
        return ProviderHealth(self.name, bool(self.api_key), "configured" if self.api_key else "API key missing")
