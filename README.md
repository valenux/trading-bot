# Robot de trading hybride (règles + IA) — Alpaca + GitHub Actions

> ⚠️ Outil expérimental. Aucun gain n'est garanti et tu peux perdre la totalité
> de l'argent investi. Le robot fonctionne en **simulation** (argent fictif) tant que
> `allow_live_trading` est à `false` dans `config.yaml`.

Le robot tourne tout seul sur GitHub chaque jour de bourse, vers 10 h 35 à Montréal.
Ton ordinateur n'a pas besoin d'être allumé.

## Comment il décide

1. **Règles** : il achète seulement si le prix est au-dessus de sa moyenne sur 50 jours,
   elle-même au-dessus de la moyenne sur 200 jours, et si le RSI est sous 70.
   Il vend quand la tendance devient baissière.
2. **IA (Claude)** : elle lit les nouvelles récentes du titre et donne un score de -1 à 1.
   Elle **confirme ou bloque** un achat, et peut forcer une vente si le signal est très négatif.
   Elle ne peut jamais acheter seule.
3. **Garde-fous** : budget de 100 $, max 50 % par titre, max 2 titres, stop-loss à 10 %,
   et aucune action si le compte a perdu 5 % depuis la veille.

Alpaca permet d'acheter des **fractions d'action** sans commission, donc 100 $ suffit.

Chaque décision est enregistrée dans `journal.csv` (mis à jour automatiquement dans le dépôt),
et le résumé de chaque exécution s'affiche dans l'onglet **Actions**.

## Mise en route (une seule fois, ~10 minutes)

### 1. Compte de simulation Alpaca
1. Crée un compte sur alpaca.markets (un courriel suffit pour la simulation).
2. Dans le tableau de bord, vérifie que tu es en mode **Paper**.
3. Recommandé : *Reset* du compte paper avec un solde de **100 $**, pour que la simulation
   ressemble à ton vrai test.
4. Menu **API Keys** → *Generate New Keys*. Copie la **Key** et le **Secret**
   (le secret ne s'affiche qu'une fois).

### 2. Clé IA (optionnelle mais recommandée)
console.anthropic.com → **API Keys** → *Create Key*. Ajoute quelques dollars de crédit.
Le coût est de quelques sous par jour. Sans cette clé, le robot fonctionne avec les règles seulement.

### 3. Ajouter les secrets dans GitHub
Dépôt → **Settings** → **Secrets and variables** → **Actions** → *New repository secret*.
Crée ces trois secrets :

| Nom | Valeur |
|---|---|
| `ALPACA_API_KEY` | la Key Alpaca |
| `ALPACA_SECRET_KEY` | le Secret Alpaca |
| `ANTHROPIC_API_KEY` | la clé Anthropic |

### 4. Premier test
Onglet **Actions** → *Robot de trading* → **Run workflow** (laisse *dry_run* coché) → Run.
Ouvre l'exécution pour lire le résumé. Si tout est vert, c'est prêt : il tournera seul
chaque jour de semaine.

## Passer à l'argent réel (ta décision, pas avant plusieurs semaines de simulation)

1. Compare `journal.csv` et la valeur du compte paper à un simple « acheter et garder » sur la même période.
2. Vérifie qu'Alpaca accepte un compte réel pour ta situation (résidence au Canada).
3. Remplace les secrets par les clés du compte **réel** et mets `allow_live_trading: true`
   dans `config.yaml`.

## Personnaliser

Tout se règle dans `config.yaml` : la liste de titres (simples exemples, pas des
recommandations), le budget, les limites et les seuils de l'IA.
Pour arrêter le robot : Actions → *Robot de trading* → « ⋯ » → **Disable workflow**.

## Tests (aucune clé nécessaire)

```bash
pip install -r requirements.txt numpy
python tests/test_bot.py
```
