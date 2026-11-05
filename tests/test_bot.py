"""Tests hors ligne : aucune clé ni connexion réseau nécessaire.

Lancer :  python -m pytest -q   (ou  python tests/test_bot.py)
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ai_analyst import parse_score  # noqa: E402
from bot import decide  # noqa: E402
from strategy import rule_signal  # noqa: E402

CFG = yaml.safe_load((Path(__file__).resolve().parents[1] / "config.yaml").read_text(encoding="utf-8"))


def series(start, end, noise, seed=1):
    rng = np.random.default_rng(seed)
    return pd.Series(np.linspace(start, end, 300) + rng.normal(0, noise, 300))


def test_rules():
    assert rule_signal(series(50, 100, 2), CFG["rules"])["signal"] == "BUY"
    assert rule_signal(series(100, 50, 0), CFG["rules"])["signal"] == "SELL"
    assert rule_signal(series(50, 100, 2)[:100], CFG["rules"])["signal"] == "HOLD"


def test_buy_respects_budget_and_ai():
    buy = {"signal": "BUY", "reason": "r", "price": 70.0}
    ok = {"score": 0.3, "reason": "ok"}
    assert decide("X", buy, ok, None, CFG, 0, 0) == ("BUY", 50.0, "r + IA +0.30")
    assert decide("X", buy, ok, None, CFG, 80, 1)[:2] == ("BUY", 20.0)
    assert decide("X", buy, ok, None, CFG, 100, 1)[0] == "HOLD"           # budget épuisé
    assert decide("X", buy, ok, None, CFG, 0, 2)[0] == "HOLD"             # max positions
    assert decide("X", buy, {"score": -0.2, "reason": "n"}, None, CFG, 0, 0)[0] == "HOLD"  # veto IA


def test_sell_rules():
    held = {"avg_entry_price": "100", "market_value": "45"}
    hold = {"signal": "HOLD", "reason": "r", "price": 89.0}
    neutral = {"score": 0.0, "reason": ""}
    assert decide("X", hold, neutral, held, CFG, 45, 1)[0] == "SELL"      # stop-loss -11 %
    hold["price"] = 95.0
    assert decide("X", hold, neutral, held, CFG, 45, 1)[0] == "HOLD"
    assert decide("X", hold, {"score": -0.8, "reason": "x"}, held, CFG, 45, 1)[0] == "SELL"
    assert decide("X", {**hold, "signal": "SELL"}, neutral, held, CFG, 45, 1)[0] == "SELL"


def test_portfolio(tmp=Path("/tmp/claude-0/pf_test.json")):
    from portfolio import PaperPortfolio
    tmp.unlink(missing_ok=True)
    pf = PaperPortfolio(tmp, 100.0, 1.0)
    assert pf.buy("A", 50, 10.0) == 49.0            # 1 $ de frais
    assert abs(pf.positions["A"]["qty"] - 4.9) < 1e-9 and pf.cash == 50.0
    assert abs(pf.equity({"A": 20.0}) - 148.0) < 1e-9
    assert abs(pf.sell_all("A", 20.0, "2026-11-06") - 97.0) < 1e-9  # 98 - 1 $ de frais
    assert abs(pf.s["realized"][0]["pnl"] - 47.0) < 1e-9          # 97 reçus - 50 payés
    assert abs(pf.cash - 147.0) < 1e-9 and pf.s["fees_paid"] == 2.0
    pf.save()
    assert PaperPortfolio(tmp, 100.0, 1.0).cash == pf.cash
    tmp.unlink()


def test_parse_score():
    assert parse_score('bla {"score": 0.4, "reason": "ok"}')["score"] == 0.4
    assert parse_score('{"score": 5}')["score"] == 1.0
    assert parse_score("rien")["score"] == 0.0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
