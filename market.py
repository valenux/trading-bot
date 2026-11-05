"""Données de marché gratuites, sans clé.

Prix : bibliothèque yfinance (gère les protections de Yahoo), puis appel direct
à Yahoo, puis Stooq en dernier recours. Nouvelles : yfinance, puis flux RSS Yahoo.
"""
import io
import xml.etree.ElementTree as ET

import pandas as pd
import requests

UA = {"User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                     "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")}


def _yfinance(symbol: str) -> pd.Series:
    import yfinance as yf
    df = yf.Ticker(symbol).history(period="2y", interval="1d", auto_adjust=True)
    if df is None or df.empty:
        raise ValueError("aucune donnée renvoyée")
    s = df["Close"].dropna()
    s.index = pd.to_datetime(s.index).tz_convert("America/New_York")
    return s


def _yahoo(symbol: str) -> pd.Series:
    last = None
    for host in ("query1", "query2"):
        r = requests.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}",
                         params={"range": "2y", "interval": "1d"}, headers=UA, timeout=30)
        try:
            chart = r.json().get("chart") or {}
        except ValueError:
            last = f"HTTP {r.status_code} {r.text[:80]!r}"
            continue
        if not chart.get("result"):
            last = f"HTTP {r.status_code} {chart.get('error') or r.text[:80]!r}"
            continue
        res = chart["result"][0]
        closes = res["indicators"]["quote"][0]["close"]
        idx = pd.to_datetime(res["timestamp"], unit="s", utc=True).tz_convert("America/New_York")
        s = pd.Series(closes, index=idx, dtype=float).dropna()
        price = res.get("meta", {}).get("regularMarketPrice")
        if price and len(s):
            s.iloc[-1] = float(price)
        return s
    raise ValueError(last)


def _stooq(symbol: str) -> pd.Series:
    r = requests.get("https://stooq.com/q/d/l/", params={"s": f"{symbol.lower()}.us", "i": "d"},
                     headers=UA, timeout=30)
    if not r.text.startswith("Date"):
        raise ValueError(f"HTTP {r.status_code} {r.text[:80]!r}")
    df = pd.read_csv(io.StringIO(r.text))
    idx = pd.to_datetime(df["Date"]).dt.tz_localize("America/New_York")
    return pd.Series(df["Close"].values, index=idx, dtype=float).dropna().iloc[-520:]


SOURCES = (_yfinance, _yahoo, _stooq)


def daily_closes(symbol: str) -> pd.Series:
    errors = []
    for source in SOURCES:
        try:
            s = source(symbol)
            if len(s) >= 2:
                return s
            errors.append(f"{source.__name__[1:]}: série vide")
        except Exception as e:
            errors.append(f"{source.__name__[1:]}: {type(e).__name__} {str(e)[:120]}")
    raise RuntimeError(f"prix indisponibles pour {symbol} → " + " | ".join(errors))


def headlines(symbol: str, limit: int = 10) -> list[str]:
    try:
        import yfinance as yf
        out = []
        for it in (yf.Ticker(symbol).news or [])[:limit]:
            title = (it.get("content") or it).get("title")
            if title:
                out.append(title)
        if out:
            return out
    except Exception:
        pass
    try:
        r = requests.get("https://feeds.finance.yahoo.com/rss/2.0/headline",
                         params={"s": symbol, "region": "US", "lang": "en-US"},
                         headers=UA, timeout=20)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        return [t.text.strip() for t in root.iter("title") if t.text][1:limit + 1]
    except Exception:
        return []
