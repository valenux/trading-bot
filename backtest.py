"""Backtest : compare plusieurs stratégies sur l'historique réel, frais compris.

    python backtest.py            # télécharge les prix (yfinance) et écrit backtest/RESULTATS.md

Règles du test, pour qu'il soit honnête :
- capital de départ 100 $, 1 $ de frais par ordre, fractions d'action permises ;
- une décision prise à la clôture d'un jour est exécutée à la clôture du jour SUIVANT
  (pas de « triche » avec un prix qu'on ne pouvait pas encore connaître) ;
- prix ajustés des dividendes (dividendes réinvestis) ;
- la partie IA n'est pas testée : on ne peut pas savoir ce qu'elle aurait dit dans le passé
  sans qu'elle connaisse déjà la suite.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from strategy import rsi

ROOT = Path(__file__).parent
OUT = ROOT / "backtest"
SYMBOLS = ["SPYM", "SCHD", "QQQ"]   # QQQ remplace QQQM (lancé en 2020) : même indice Nasdaq-100
START_CASH, FEE = 100.0, 1.0
PERIODS = {"2013 → aujourd'hui": "2013-01-02", "5 dernières années": "2021-01-04"}


# ---------------------------------------------------------------- données
def load_prices() -> pd.DataFrame:
    import yfinance as yf
    cols = {}
    for s in SYMBOLS:
        df = yf.Ticker(s).history(period="max", interval="1d", auto_adjust=True)
        if df is None or df.empty:
            raise RuntimeError(f"aucune donnée pour {s}")
        c = df["Close"].dropna()
        c.index = pd.to_datetime(c.index).tz_localize(None).normalize()
        cols[s] = c
    return pd.DataFrame(cols).dropna()


# ---------------------------------------------------------------- moteur
class Sim:
    def __init__(self, px: pd.DataFrame, start: str):
        self.px = px
        self.i0 = int(px.index.searchsorted(pd.Timestamp(start)))
        self.cash, self.qty, self.entry, self.cost = START_CASH, {}, {}, {}
        self.trades, self.fees, self.pending = 0, 0.0, []
        self.curve = []

    def price(self, i, s):
        return float(self.px[s].iat[i])

    def equity(self, i):
        return self.cash + sum(q * self.price(i, s) for s, q in self.qty.items())

    def _exec(self, i):
        for o in [o for o in self.pending if o[0] == "sell"] + [o for o in self.pending if o[0] == "buy"]:
            if o[0] == "sell" and o[1] in self.qty:
                s = o[1]
                self.cash += self.qty.pop(s) * self.price(i, s) - FEE
                self.entry.pop(s), self.cost.pop(s)
                self.trades += 1
                self.fees += FEE
            elif o[0] == "buy":
                s, amount = o[1], min(o[2], self.cash)
                if amount - FEE < 1:
                    continue
                p = self.price(i, s)
                q = (amount - FEE) / p
                old = self.qty.get(s, 0.0)
                self.entry[s] = (old * self.entry.get(s, p) + q * p) / (old + q)
                self.cost[s] = self.cost.get(s, 0.0) + amount
                self.qty[s] = old + q
                self.cash -= amount
                self.trades += 1
                self.fees += FEE
        self.pending = []

    def run(self, decide):
        for i in range(self.i0, len(self.px)):
            self._exec(i)
            self.curve.append(self.equity(i))
            if i < len(self.px) - 1:
                self.pending = decide(self, i)
        return self


def month_end(px, i):
    return i + 1 < len(px) and px.index[i + 1].month != px.index[i].month


# ---------------------------------------------------------------- stratégies
def buy_hold(sym):
    def d(sim, i):
        return [("buy", sym, sim.cash)] if not sim.qty and i == sim.i0 else []
    return d


def robot(ind, fixed_budget: bool):
    """Les règles actuelles du robot (sans l'IA). fixed_budget=True reproduit la version
    en ligne : jamais plus de 100 $ investis, même si le portefeuille grossit."""
    def d(sim, i):
        orders, n = [], len(sim.qty)
        invested = sum(q * sim.price(i, s) for s, q in sim.qty.items())
        budget = START_CASH if fixed_budget else sim.equity(i)
        for s in SYMBOLS:
            p, f, sl, r = sim.price(i, s), ind[s]["f"][i], ind[s]["s"][i], ind[s]["r"][i]
            if np.isnan(sl):
                continue
            buy_sig = p > f > sl and r < 70
            sell_sig = p < sl or f < sl
            if s in sim.qty:
                if p <= sim.entry[s] * 0.90 or sell_sig:
                    orders.append(("sell", s))
                    invested -= sim.qty[s] * p
                    n -= 1
            elif buy_sig and n < 2:
                room = min(budget - invested, budget * 0.5)
                if room >= 10:
                    orders.append(("buy", s, room))
                    invested += room
                    n += 1
        return orders
    return d


def trend_sp500(ind):
    """Tout dans le S&P 500 quand il est au-dessus de sa moyenne 200 jours, sinon liquidités.
    Vérifié une fois par mois (dernier jour de bourse) pour limiter les frais."""
    def d(sim, i):
        if not month_end(sim.px, i) and i != sim.i0:
            return []
        up = sim.price(i, "SPYM") > ind["SPYM"]["s"][i]
        if up and not sim.qty:
            return [("buy", "SPYM", sim.equity(i))]
        if not up and sim.qty:
            return [("sell", "SPYM")]
        return []
    return d


def rotation(lookback=126):
    """Chaque mois, tout dans le FNB qui a le plus monté sur 6 mois ; liquidités si aucun ne monte."""
    def d(sim, i):
        if not month_end(sim.px, i) and i != sim.i0:
            return []
        rets = {s: sim.price(i, s) / sim.price(i - lookback, s) - 1 for s in SYMBOLS}
        best = max(rets, key=rets.get)
        held = next(iter(sim.qty), None)
        if rets[best] <= 0:
            return [("sell", held)] if held else []
        if held == best:
            return []
        eq = sim.equity(i)
        return ([("sell", held)] if held else []) + [("buy", best, eq - (FEE if held else 0))]
    return d


# ---------------------------------------------------------------- mesures
def metrics(sim: Sim) -> dict:
    c = pd.Series(sim.curve, index=sim.px.index[sim.i0:])
    years = (c.index[-1] - c.index[0]).days / 365.25
    dd = (c / c.cummax() - 1).min()
    yearly = c.groupby(c.index.year).last()
    prev = pd.concat([pd.Series([START_CASH]), yearly.iloc[:-1]]).values
    worst = float((yearly.values / prev - 1).min())
    return {"final": round(float(c.iloc[-1]), 2), "total": float(c.iloc[-1] / START_CASH - 1),
            "cagr": float((c.iloc[-1] / START_CASH) ** (1 / years) - 1), "max_dd": float(dd),
            "worst_year": worst, "trades": sim.trades, "fees": sim.fees,
            "curve": [[d.strftime("%Y-%m-%d"), round(v, 2)] for d, v in c.resample("ME").last().items()]}


STRATS = [
    ("Acheter et garder S&P 500 (SPYM)", "Un seul achat le premier jour, plus aucune action.",
     lambda ind: buy_hold("SPYM")),
    ("Acheter et garder Nasdaq-100 (QQQ)", "Un seul achat, mais sur un indice plus risqué (technologie).",
     lambda ind: buy_hold("QQQ")),
    ("Robot actuel (règles, budget fixe 100 $)", "Exactement les règles en ligne aujourd'hui, sans l'IA.",
     lambda ind: robot(ind, fixed_budget=True)),
    ("Robot actuel, gains réinvestis", "Mêmes règles, mais le budget suit la valeur du portefeuille.",
     lambda ind: robot(ind, fixed_budget=False)),
    ("Tendance S&P 500 (mensuel)", "100 % S&P 500 au-dessus de sa moyenne 200 jours, sinon liquidités.",
     lambda ind: trend_sp500(ind)),
    ("Rotation momentum (mensuel)", "Chaque mois, tout dans le FNB le plus fort sur 6 mois, sinon liquidités.",
     lambda ind: rotation()),
]


def pct(v):
    return f"{v:+.1%}".replace(".", ",")


def main():
    px = load_prices()
    ind = {s: {"f": px[s].rolling(50).mean().values, "s": px[s].rolling(200).mean().values,
               "r": rsi(px[s], 14).values} for s in SYMBOLS}
    results = {}
    for pname, start in PERIODS.items():
        results[pname] = []
        for name, desc, make in STRATS:
            m = metrics(Sim(px, start).run(make(ind)))
            results[pname].append({"name": name, "desc": desc, **m})

    OUT.mkdir(exist_ok=True)
    last = px.index[-1].strftime("%Y-%m-%d")
    lines = ["# Résultats du backtest", "",
             f"_Données jusqu'au {last} · départ 100 $ · 1 $ de frais par ordre · exécution au lendemain "
             "de la décision · dividendes réinvestis · partie IA non testée._", ""]
    for pname, rows in results.items():
        rows = sorted(rows, key=lambda r: -r["final"])
        lines += [f"## {pname}", "",
                  "| Stratégie | Valeur finale | Rendement annuel | Pire baisse | Pire année | Ordres | Frais |",
                  "|---|---:|---:|---:|---:|---:|---:|"]
        lines += [f"| {r['name']} | {r['final']:.2f} $ | {pct(r['cagr'])} | {pct(r['max_dd'])} | "
                  f"{pct(r['worst_year'])} | {r['trades']} | {r['fees']:.0f} $ |" for r in rows]
        lines.append("")
    lines += ["## Les stratégies", ""] + [f"- **{n}** : {d}" for n, d, _ in STRATS] + [
        "", "_« Pire baisse » : la plus grosse chute entre un sommet et un creux, en cours de route. "
        "Les résultats passés ne garantissent rien pour l'avenir._"]
    (OUT / "RESULTATS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (OUT / "resultats.json").write_text(json.dumps({"last_day": last, "results": results},
                                                   ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
