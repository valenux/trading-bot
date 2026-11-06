"""Robot de trading hybride (règles + IA) sur portefeuille fictif.

Lancement :  python bot.py            (une exécution ; GitHub Actions le lance chaque jour de bourse)
             python bot.py --dry-run  (analyse seulement : rien n'est acheté, vendu ni enregistré)
"""
import argparse
import csv
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

import market
import report as report_mod
from ai_analyst import ai_score
from portfolio import PaperPortfolio
from strategy import rule_signal

ROOT = Path(__file__).parent
JOURNAL = ROOT / "journal.csv"
PORTFOLIO = ROOT / "portfolio.json"
FIELDS = ["time", "symbol", "action", "amount_usd", "price", "rule", "ai_score", "reason"]
NY = ZoneInfo("America/New_York")


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


def run(cfg: dict, dry: bool, report: list[str]) -> None:
    today = datetime.now(NY).date().isoformat()
    pf = PaperPortfolio(PORTFOLIO, cfg["budget"], cfg["sim_fee_usd"])

    if pf.s["last_run_day"] == today and not dry:
        report.append("Déjà exécuté aujourd'hui : rien à faire.")
        return

    watch = [s.upper() for s in cfg["watchlist"]]
    bench_sym = cfg["benchmark"].upper()
    closes = {bench_sym: market.daily_closes(bench_sym)}  # la référence est indispensable
    for sym in watch:
        if sym in closes:
            continue
        try:
            closes[sym] = market.daily_closes(sym)
        except Exception as e:  # un symbole invalide ne bloque pas les autres
            report.append(f"{sym}: ignoré – {e}")
    watch = [s for s in watch if s in closes]

    last_day = closes[bench_sym].index[-1].date().isoformat()
    if last_day != today and not dry:
        report.append(f"Marché fermé aujourd'hui (dernière séance : {last_day}) : rien à faire.")
        return

    prices = {sym: float(s.iloc[-1]) for sym, s in closes.items()}
    equity = pf.equity(prices)
    last_eq = pf.s["last_equity"]
    if last_eq and (last_eq - equity) / last_eq >= cfg["max_daily_loss_pct"]:
        report.append(f"Coupe-circuit : valeur {equity:.2f} $ contre {last_eq:.2f} $ hier, "
                      "aucune action aujourd'hui.")
        if not dry:  # pause d'une journée seulement : la référence repart de la valeur actuelle
            pf.s["last_equity"], pf.s["last_run_day"] = equity, today
            pf.save()
        return

    invested = sum(p["qty"] * prices[s] for s, p in pf.positions.items())
    # Le budget suit la valeur du portefeuille : les gains sont réinvestis (cf. backtest)
    run_cfg = {**cfg, "budget": equity}
    n_pos = len(pf.positions)

    for sym in watch:
        try:
            rule = rule_signal(closes[sym], cfg["rules"])
            price = prices[sym]
            p = pf.positions.get(sym)
            held = {"avg_entry_price": p["avg_entry_price"], "market_value": p["qty"] * price} if p else None

            ai = {"score": 0.0, "reason": ""}
            if rule["signal"] == "BUY" or held:
                ai = ai_score(sym, rule, market.headlines(sym, cfg["ai"]["max_headlines"]), cfg["ai"])

            action, amount, reason = decide(sym, rule, ai, held, run_cfg, invested, n_pos)

            if not dry and action == "BUY":
                amount = round(pf.buy(sym, amount, price), 2)
                if amount <= 0:
                    action, reason = "HOLD", "liquidités insuffisantes"
                else:
                    invested += amount
                    n_pos += 1
            elif not dry and action == "SELL":
                amount = round(pf.sell_all(sym, price, today), 2)
                invested -= held["market_value"]
                n_pos -= 1

            if not dry:
                log({"time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                     "symbol": sym, "action": action, "amount_usd": amount, "price": round(price, 2),
                     "rule": rule["signal"], "ai_score": ai["score"], "reason": reason})
            report.append(f"{sym}: {action} {f'{amount:.2f} $ ' if amount else ''}@ {price:.2f} – {reason}")
        except Exception as e:  # un titre en erreur ne bloque pas les autres
            report.append(f"{sym}: ERREUR – {e}")

    # --- Bilan et comparaison avec « acheter et garder » ---
    equity = pf.equity(prices)
    if not pf.s["benchmark"]:
        pf.s["benchmark"] = {"symbol": bench_sym, "start_price": prices[bench_sym], "start_day": today}
    b = pf.s["benchmark"]
    bench_value = pf.s["start_cash"] * prices[b["symbol"]] / b["start_price"]
    start = pf.s["start_cash"]
    report += ["",
               f"Robot             : {equity:8.2f} $  ({equity / start - 1:+.2%})  "
               f"dont {pf.s['fees_paid']:.2f} $ de frais simulés",
               f"Acheter et garder : {bench_value:8.2f} $  ({bench_value / start - 1:+.2%})  "
               f"[{b['symbol']} depuis le {b['start_day']}]",
               f"Liquidités        : {pf.cash:8.2f} $"]

    if not dry:
        pf.s["last_equity"] = equity
        pf.s["last_run_day"] = today
        pf.s["last_prices"] = {s: round(v, 4) for s, v in prices.items()}
        pf.s["history"].append({"day": today, "equity": round(equity, 2), "benchmark": round(bench_value, 2)})
        pf.save()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    dry = args.dry_run or cfg.get("dry_run", False)
    report = [f"Exécution du {datetime.now(NY):%Y-%m-%d %H:%M} (New York)"
              f"  [portefeuille fictif{' / dry-run' if dry else ''}]", ""]
    failed = False
    try:
        run(cfg, dry, report)
    except Exception as e:
        report.append(f"ERREUR : {e}")
        failed = True
    if not dry:
        try:
            report_mod.update()
        except Exception as e:
            report.append(f"(rapport non mis à jour : {e})")
    write_summary(report)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
