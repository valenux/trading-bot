"""Stratégie à règles : tendance (moyennes mobiles) + filtre RSI."""
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-12)
    return 100 - 100 / (1 + rs)


def rule_signal(close: pd.Series, cfg: dict) -> dict:
    """Retourne {'signal': 'BUY'|'SELL'|'HOLD', 'reason': str, ...}."""
    fast, slow = cfg["sma_fast"], cfg["sma_slow"]
    if len(close) < slow + 5:
        return {"signal": "HOLD", "reason": "historique insuffisant"}

    sma_f = close.rolling(fast).mean()
    sma_s = close.rolling(slow).mean()
    r = rsi(close, cfg["rsi_period"])
    price, f, s, rv = close.iloc[-1], sma_f.iloc[-1], sma_s.iloc[-1], r.iloc[-1]

    info = {"price": round(float(price), 2), "sma_fast": round(float(f), 2),
            "sma_slow": round(float(s), 2), "rsi": round(float(rv), 1)}

    uptrend = price > f > s
    downtrend = price < s or f < s

    if uptrend and rv < cfg["rsi_overbought"]:
        return {**info, "signal": "BUY", "reason": "tendance haussière, RSI non suracheté"}
    if downtrend:
        return {**info, "signal": "SELL", "reason": "tendance baissière (prix ou SMA rapide sous SMA lente)"}
    return {**info, "signal": "HOLD", "reason": "pas de signal clair"}
