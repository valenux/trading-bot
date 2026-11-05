"""Données de marché gratuites, sans clé : prix (Yahoo Finance, repli Stooq) et nouvelles (RSS Yahoo)."""
import io
import xml.etree.ElementTree as ET

import pandas as pd
import requests

UA = {"User-Agent": "Mozilla/5.0 (compatible; trading-bot/1.0)"}


def _yahoo(symbol: str) -> pd.Series:
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                     params={"range": "2y", "interval": "1d"}, headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    closes = res["indicators"]["quote"][0]["close"]
    idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("America/New_York")
    s = pd.Series(closes, index=idx, dtype=float).dropna()
    price = res.get("meta", {}).get("regularMarketPrice")
    if price and len(s):
        s.iloc[-1] = float(price)  # prix le plus récent de la séance
    return s


def _stooq(symbol: str) -> pd.Series:
    r = requests.get("https://stooq.com/q/d/l/", params={"s": f"{symbol.lower()}.us", "i": "d"},
                     headers=UA, timeout=30)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    idx = pd.to_datetime(df["Date"]).dt.tz_localize("America/New_York")
    return pd.Series(df["Close"].values, index=idx, dtype=float).dropna().iloc[-520:]


def daily_closes(symbol: str) -> pd.Series:
    errors = []
    for source in (_yahoo, _stooq):
        try:
            s = source(symbol)
            if len(s):
                return s
        except Exception as e:
            errors.append(f"{source.__name__[1:]}: {type(e).__name__}")
    raise RuntimeError(f"prix indisponibles ({', '.join(errors)})")


def headlines(symbol: str, limit: int = 10) -> list[str]:
    try:
        r = requests.get("https://feeds.finance.yahoo.com/rss/2.0/headline",
                         params={"s": symbol, "region": "US", "lang": "en-US"},
                         headers=UA, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        return [t.text.strip() for t in root.iter("title") if t.text][1:limit + 1]
    except Exception:
        return []
