"""Rapport visuel : graphique SVG + tableaux, insérés en haut du README.

Lancé automatiquement après chaque exécution du robot ; peut aussi se lancer seul :
    python report.py
"""
import csv
import json
import math

from html import escape
from pathlib import Path

ROOT = Path(__file__).parent
PORTFOLIO = ROOT / "portfolio.json"
JOURNAL = ROOT / "journal.csv"
README = ROOT / "README.md"
SVG = ROOT / "rapport" / "evolution.svg"
START, END = "<!-- RAPPORT:DEBUT -->", "<!-- RAPPORT:FIN -->"

W, H = 760, 320
ML, MR, MT, MB = 56, 130, 44, 36  # marges : la droite accueille les étiquettes de fin de ligne


def _fmt_day(d: str) -> str:
    y, m, dd = d.split("-")
    mois = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août",
            "sept.", "oct.", "nov.", "déc."][int(m) - 1]
    return f"{int(dd)} {mois}"


def build_svg(history: list[dict], bench_sym: str) -> str:
    style = """<style>
  .bg{fill:#fcfcfb}.t1{fill:#0b0b0b}.t2{fill:#52514e}.grid{stroke:#e4e3df}
  .s1{stroke:#2a78d6}.f1{fill:#2a78d6}.s2{stroke:#eb6834}.f2{fill:#eb6834}.ring{stroke:#fcfcfb}
  @media (prefers-color-scheme: dark){
    .bg{fill:#1a1a19}.t1{fill:#f0efec}.t2{fill:#c3c2b7}.grid{stroke:#353533}
    .s1{stroke:#3987e5}.f1{fill:#3987e5}.s2{stroke:#d95926}.f2{fill:#d95926}.ring{stroke:#1a1a19}}
  text{font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif}
</style>"""
    head = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
            f'role="img" aria-label="Évolution du portefeuille du robot comparée à acheter et garder">'
            f'{style}<rect class="bg" width="{W}" height="{H}" rx="8"/>'
            f'<text class="t1" x="{ML}" y="24" font-size="15" font-weight="600">'
            f'Valeur du portefeuille fictif (USD)</text>')

    if len(history) < 2:
        return (head + f'<text class="t2" x="{W/2}" y="{H/2}" font-size="14" text-anchor="middle">'
                "Le graphique apparaîtra après deux jours de bourse.</text></svg>")

    days = [h["day"] for h in history]
    robot = [h["equity"] for h in history]
    bench = [h["benchmark"] for h in history]
    lo, hi = min(robot + bench), max(robot + bench)
    pad = max((hi - lo) * 0.15, 1.0)
    lo, hi = lo - pad, hi + pad
    raw = (hi - lo) / 4  # graduations rondes : 1, 2, 5 × 10^k
    mag = 10 ** math.floor(math.log10(raw))
    step = next(m * mag for m in (1, 2, 5, 10) if m * mag >= raw)
    lo, hi = math.floor(lo / step) * step, math.ceil(hi / step) * step
    ticks = [lo + k * step for k in range(round((hi - lo) / step) + 1)]
    pw, ph = W - ML - MR, H - MT - MB
    n = len(history)

    def x(i): return ML + pw * i / (n - 1)
    def y(v): return MT + ph * (1 - (v - lo) / (hi - lo))

    parts = [head]
    # légende (2 séries)
    parts.append(f'<rect class="f1" x="{W - MR - 250}" y="15" width="12" height="3" rx="1.5"/>'
                 f'<text class="t2" x="{W - MR - 233}" y="20" font-size="12">Robot</text>'
                 f'<rect class="f2" x="{W - MR - 180}" y="15" width="12" height="3" rx="1.5"/>'
                 f'<text class="t2" x="{W - MR - 163}" y="20" font-size="12">Acheter et garder ({escape(bench_sym)})</text>')
    # grille et axe y (graduations rondes)
    for v in ticks:
        parts.append(f'<line class="grid" x1="{ML}" x2="{W - MR}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke-width="1"/>'
                     f'<text class="t2" x="{ML - 8}" y="{y(v) + 4:.1f}" font-size="11" text-anchor="end">{v:.0f} $</text>')
    # axe x : premier, milieu, dernier jour
    for i in sorted({0, n // 2, n - 1}):
        anchor = "start" if i == 0 else "end" if i == n - 1 else "middle"
        parts.append(f'<text class="t2" x="{x(i):.1f}" y="{H - 12}" font-size="11" text-anchor="{anchor}">{_fmt_day(days[i])}</text>')
    # lignes
    for vals, cls in ((bench, "2"), (robot, "1")):
        pts = " ".join(f"{x(i):.1f},{y(v):.1f}" for i, v in enumerate(vals))
        parts.append(f'<polyline class="s{cls}" points="{pts}" fill="none" stroke-width="2" '
                     f'stroke-linejoin="round" stroke-linecap="round"/>')
        parts.append(f'<circle class="f{cls} ring" cx="{x(n - 1):.1f}" cy="{y(vals[-1]):.1f}" r="4" stroke-width="2"/>')
    # étiquettes directes en fin de ligne, sans chevauchement
    ly = {"1": y(robot[-1]), "2": y(bench[-1])}
    if abs(ly["1"] - ly["2"]) < 30:
        mid = (ly["1"] + ly["2"]) / 2
        up, down = ("1", "2") if robot[-1] >= bench[-1] else ("2", "1")
        ly[up], ly[down] = mid - 15, mid + 15
    for cls, name, v in (("1", "Robot", robot[-1]), ("2", "Acheter et garder", bench[-1])):
        parts.append(f'<text class="t1" x="{W - MR + 10}" y="{ly[cls] - 2:.1f}" font-size="13" font-weight="600">{v:.2f} $</text>'
                     f'<text class="t2" x="{W - MR + 10}" y="{ly[cls] + 12:.1f}" font-size="11">{name}</text>')
    parts.append("</svg>")
    return "".join(parts)


def build_markdown(pf: dict | None, rows: list[dict]) -> str:
    if not pf:
        return (f"{START}\n## 📊 Rapport\n\n_Le rapport apparaîtra après la première exécution "
                f"du robot (chaque jour de bourse vers 10 h 35, heure de Montréal)._\n{END}")
    h = pf["history"][-1] if pf["history"] else {"day": "—", "equity": pf["cash"], "benchmark": pf["start_cash"]}
    start = pf["start_cash"]
    ecart = h["equity"] - h["benchmark"]
    b = pf.get("benchmark") or {}
    lines = [START, "## 📊 Rapport", "",
             f"_Mis à jour le {h['day']} · portefeuille fictif de départ : {start:.2f} $_", "",
             "![Évolution du portefeuille](rapport/evolution.svg)", "",
             "| | Valeur | Rendement |", "|---|---:|---:|",
             f"| **Robot** | {h['equity']:.2f} $ | {h['equity'] / start - 1:+.2%} |",
             f"| Acheter et garder ({b.get('symbol', '—')}) | {h['benchmark']:.2f} $ | {h['benchmark'] / start - 1:+.2%} |",
             f"| **Écart** | {ecart:+.2f} $ | |", "",
             f"Liquidités : {pf['cash']:.2f} $ · Frais simulés payés : {pf['fees_paid']:.2f} $", ""]
    if pf["positions"]:
        lines += ["**Titres détenus**", "", "| Titre | Quantité | Prix d'achat moyen |", "|---|---:|---:|"]
        lines += [f"| {s} | {p['qty']:.4f} | {p['avg_entry_price']:.2f} $ |" for s, p in pf["positions"].items()]
        lines.append("")
    trades = [r for r in rows if r["action"] in ("BUY", "SELL")][-10:]
    if trades:
        lines += ["**Dernières transactions**", "", "| Date | Titre | Action | Montant | Raison |",
                  "|---|---|---|---:|---|"]
        for r in reversed(trades):
            act = "Achat" if r["action"] == "BUY" else "Vente"
            reason = r["reason"].replace("|", "/")
            lines.append(f"| {r['time'][:10]} | {r['symbol']} | {act} | {float(r['amount_usd']):.2f} $ | {reason} |")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def update() -> None:
    pf = json.loads(PORTFOLIO.read_text(encoding="utf-8")) if PORTFOLIO.exists() else None
    rows = list(csv.DictReader(JOURNAL.open(encoding="utf-8"))) if JOURNAL.exists() else []
    SVG.parent.mkdir(exist_ok=True)
    bench_sym = ((pf or {}).get("benchmark") or {}).get("symbol", "")
    SVG.write_text(build_svg((pf or {}).get("history", []), bench_sym), encoding="utf-8")

    block = build_markdown(pf, rows)
    text = README.read_text(encoding="utf-8")
    if START in text and END in text:
        before, rest = text.split(START, 1)
        text = before + block + rest.split(END, 1)[1]
    else:  # insère après le titre principal
        first, _, rest = text.partition("\n")
        text = f"{first}\n\n{block}\n{rest}"
    README.write_text(text, encoding="utf-8")

    import dashboard
    dashboard.build(pf, rows)


if __name__ == "__main__":
    update()
