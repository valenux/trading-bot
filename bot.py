"""Robot de trading hybride (règles + IA) pour Alpaca.

Lancement :  python bot.py            (une exécution ; GitHub Actions le lance chaque jour de bourse)
             python bot.py --dry-run  (analyse seulement, aucun ordre)
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

from ai_analyst import ai_score
from broker import Alpaca
from strategy import rule_signal

ROOT = Path(__file__).parent
JOURNAL = ROOT / "journal.csv"
FIELDS = ["time", "mode", "symbol", "action", "amount_usd", "price", "rule", "ai_score", "reason"]


def log(row: dict) -> None:
    new = not JOURNAL.exists()
    with JOURNAL.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def write_summary(lines: list[str]) -> None:
    body = "\n".join(lines)
    print(body)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write("## Robot de trading\n\n```\n" + body + "\n```\n")


def decide(sym: str, rule: dict, ai: dict, held: dict | None, cfg: dict,
           invested: float, n_positions: int) -> tuple[str, float, str]:
    """Retourne (action, montant_usd, raison). Fonction pure, testable."""
    price = rule.get("price") or 0.0
    reason = rule["reason"]

    if held:
        entry = float(held["avg_entry_price"])
        value = float(held["market_value"])
        if price and price <= entry * (1 - cfg["stop_loss_pct"]):
            return "SELL", value, f"stop-loss ({price} <= {entry:.2f} -{cfg['stop_loss_pct']:.0%})"
        if rule["signal"] == "SELL":
            return "SELL", value, reason
        if ai["score"] < cfg["ai"]["sell_if_score_below"]:
            return "SELL", value, f"veto IA : {ai['reason']}"
        return "HOLD", 0.0, reason

    if rule["signal"] != "BUY":
        return "HOLD", 0.0, reason
    if ai["score"] < cfg["ai"]["min_score_to_buy"]:
        return "HOLD", 0.0, f"achat bloqué par l'IA : {ai['reason']}"
    if n_positions >= cfg["max_positions"]:
        return "HOLD", 0.0, "nombre max de positions atteint"
    room = min(cfg["budget"] - invested, cfg["budget"] * cfg["max_position_pct"])
    if room < cfg["min_order_usd"]:
        return "HOLD", 0.0, "budget épuisé"
    return "BUY", round(room, 2), f"{reason} + IA {ai['score']:+.2f}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    dry = args.dry_run or cfg.get("dry_run", False)
    live = bool(cfg.get("allow_live_trading", False))
    mode = ("RÉEL" if live else "simulation") + (" / dry-run" if dry else "")
    report = [f"Exécution du {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC  [{mode}]"]

    try:
        api = Alpaca(live=live)

        if not api.clock().get("is_open") and not dry:
            report.append("Marché fermé (fin de semaine ou jour férié) : rien à faire.")
            return

        acct = api.account()
        equity, last_equity = float(acct["equity"]), float(acct["last_equity"])
        report.append(f"Compte {acct.get('account_number')} : valeur {equity:,.2f} $")
        if last_equity > 0 and (last_equity - equity) / last_equity >= cfg["max_daily_loss_pct"]:
            report.append("Coupe-circuit : perte journalière trop forte, aucune action.")
            return

        watch = [s.upper() for s in cfg["watchlist"]]
        positions = {s: p for s, p in api.positions().items() if s in watch}
        invested = sum(float(p["market_value"]) for p in positions.values())
        n_pos = len(positions)

        for sym in watch:
            try:
                close = api.daily_closes(sym)
                rule = rule_signal(close, cfg["rules"])
                held = positions.get(sym)

                ai = {"score": 0.0, "reason": ""}
                if rule["signal"] == "BUY" or held:
                    ai = ai_score(sym, rule, api.headlines(sym, cfg["ai"]["max_headlines"]), cfg["ai"])

                action, amount, reason = decide(sym, rule, ai, held, cfg, invested, n_pos)

                if action != "HOLD" and not dry:
                    if action == "BUY":
                        if api.asset(sym).get("fractionable"):
                            api.buy(sym, notional=amount)
                        else:
                            qty = int(amount // rule["price"])
                            if qty < 1:
                                action, reason = "HOLD", "titre non fractionnable, budget trop petit"
                            else:
                                api.buy(sym, qty=qty)
                                amount = qty * rule["price"]
                    else:
                        api.close_position(sym)

                if action == "BUY":
                    invested += amount
                    n_pos += 1
                elif action == "SELL":
                    invested -= amount
                    n_pos -= 1

                log({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "mode": mode, "symbol": sym, "action": action,
                     "amount_usd": round(amount, 2), "price": rule.get("price", ""),
                     "rule": rule["signal"], "ai_score": ai["score"], "reason": reason})
                report.append(f"{sym}: {action} {f'{amount:.2f} $' if amount else ''} "
                              f"@ {rule.get('price', '?')} – {reason}")
            except Exception as e:  # un titre en erreur ne bloque pas les autres
                report.append(f"{sym}: ERREUR – {e}")
    except Exception as e:
        report.append(f"ERREUR : {e}")
        failed = True
    else:
        failed = False
    finally:
        write_summary(report)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
