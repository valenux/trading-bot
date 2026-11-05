"""Portefeuille fictif : le robot joue avec de l'argent virtuel, aux vrais prix du marché.

L'état est conservé dans portfolio.json (enregistré dans le dépôt après chaque exécution).
"""
import json
from pathlib import Path


class PaperPortfolio:
    def __init__(self, path: Path, start_cash: float, fee_usd: float):
        self.path = path
        self.fee = fee_usd
        if path.exists():
            self.s = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.s = {"start_cash": start_cash, "cash": start_cash, "positions": {},
                      "fees_paid": 0.0, "benchmark": None, "last_equity": None,
                      "last_run_day": None, "history": []}

    @property
    def cash(self) -> float:
        return self.s["cash"]

    @property
    def positions(self) -> dict:
        return self.s["positions"]

    def equity(self, prices: dict) -> float:
        return self.cash + sum(p["qty"] * prices.get(sym, p["avg_entry_price"])
                               for sym, p in self.positions.items())

    def buy(self, sym: str, amount: float, price: float) -> float:
        """Achète pour `amount` $ (frais inclus). Retourne le montant réellement investi."""
        amount = min(amount, self.cash)
        invest = amount - self.fee
        if invest <= 0:
            return 0.0
        qty = invest / price
        pos = self.positions.get(sym, {"qty": 0.0, "avg_entry_price": price})
        total = pos["qty"] + qty
        pos["avg_entry_price"] = (pos["qty"] * pos["avg_entry_price"] + qty * price) / total
        pos["qty"] = total
        self.positions[sym] = pos
        self.s["cash"] -= amount
        self.s["fees_paid"] += self.fee
        return invest

    def sell_all(self, sym: str, price: float) -> float:
        pos = self.positions.pop(sym)
        proceeds = pos["qty"] * price - self.fee
        self.s["cash"] += proceeds
        self.s["fees_paid"] += self.fee
        return proceeds

    def save(self) -> None:
        self.path.write_text(json.dumps(self.s, indent=2), encoding="utf-8")
