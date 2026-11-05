"""Analyse IA : Claude lit les nouvelles récentes et donne un score de -1 à 1.

L'IA ne décide jamais seule : son score sert à confirmer ou bloquer
un signal de la stratégie à règles.
"""
import json
import os
import re

import requests

PROMPT = """Tu es un analyste prudent. Voici des titres de nouvelles récentes sur {symbol}.
Évalue l'impact probable à court terme (quelques semaines) sur le cours.
Réponds UNIQUEMENT en JSON : {{"score": nombre entre -1 et 1, "reason": "une phrase en français"}}.
-1 = très négatif, 0 = neutre ou incertain, 1 = très positif. En cas de doute, reste proche de 0.

Données techniques : {technicals}

Nouvelles :
{headlines}
"""


def parse_score(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0)) if m else {}
        score = max(-1.0, min(1.0, float(data.get("score", 0))))
        return {"score": score, "reason": str(data.get("reason", ""))[:300]}
    except Exception:
        return {"score": 0.0, "reason": "réponse IA illisible, ignorée"}


def ai_score(symbol: str, technicals: dict, headlines: list[str], cfg: dict) -> dict:
    if not cfg.get("enabled"):
        return {"score": 0.0, "reason": "IA désactivée"}
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        return {"score": 0.0, "reason": "secret ANTHROPIC_API_KEY absent, IA ignorée"}
    if not headlines:
        return {"score": 0.0, "reason": "aucune nouvelle trouvée"}

    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": cfg["model"], "max_tokens": 300,
                  "messages": [{"role": "user", "content": PROMPT.format(
                      symbol=symbol, technicals=json.dumps(technicals),
                      headlines="\n".join(f"- {h}" for h in headlines))}]},
            timeout=60,
        )
        r.raise_for_status()
        text = "".join(b.get("text", "") for b in r.json().get("content", []))
    except Exception as e:
        return {"score": 0.0, "reason": f"erreur IA ({type(e).__name__}), ignorée"}
    return parse_score(text)
