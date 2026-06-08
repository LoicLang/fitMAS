---
summary: design du chantier dogfood V0 — rendre la boucle semaine (plan + ajuste + voit) dogfoodable via un runner Telegram standalone sur le store v0_*, + availability typée (#2), + get_planned_week, + préparation repo public. Pas de suivi d'exécution (phase 2), pas de bridge DB legacy, pas de deploy.
read_when:
  - brancher un dogfood Telegram du runtime_v0
  - typer l'availability comme contrainte (fenêtre-jours) dans le moteur Meso
  - ajouter un read tool sur la semaine committée
  - préparer le repo pour le public
---

# Design — dogfood V0 (boucle semaine) + repo public

## Statut (8 juin 2026)

Pièces 1 (runner Telegram `scripts/dogfood_telegram.py`), 2 (`get_planned_week`), 3 (#2
availability `blocked_days`) livrées et prouvées couche 2 (blessure 5/5/5/5, indispo
5/5/5/5 — `probe_live_simulation`). 262 tests, cap 4440. Reste : README racine + flip
public (confirmation Loïc).

Contexte : `docs/RUNTIME-MIGRATION-PLAN.md` (Phase 3 interface dogfood), `docs/BUILD-ORDER.md`
(tranche #2 availability), `docs/PLANNING-V0.md` (réduction-sous-contrainte : indispo-fenêtre
= 3e cas, relâche l'anti-drop), `docs/V0-DOGFOOD-SCOPE.md`. Décisions brainstorm 8 juin :
v1 dogfood = **plan + ajuste + voit**, **sans suivi d'exécution** (phase 2). Doctrine dure :
le LLM comprend/déclare, le backend valide/commit/audite ; zéro regex sur texte user ;
`runtime_v0` reste isolé (le pont vit dans `adapters/` ou un script, jamais dans le noyau).

## Décisions (tranchées)

1. **Câblage = runner Telegram standalone** (pas de flag dans l'API legacy). Un script dédié
   poll Telegram → `handle_event` → reply, sur le store `v0_*`. Zéro modif du pipeline legacy,
   isolation totale. Le chemin "flag dans l'API" (plan migration W2) reste pour la prod plus tard.
2. **Tourne en local** (poll, pas de webhook) → aucun deploy Fly requis (« deploy pas encore »).
3. **Provider DeepSeek** (prouvé couche 2, profil Fly). Pas d'Anthropic côté V0.
4. **Store `v0_*` propre** (`FITMAS_V0_DB_PATH`, persistant) — pas de bridge DB legacy
   (la boucle plan+ajuste+voit n'en a pas besoin ; pas de matérialisation vers
   `v0_scheduled_sessions` — phase 2).
5. **#2 availability incluse** (décision Loïc) : la boucle semaine doit ajuster autour des
   jours bloqués. Même pattern que #1 (blessure) : le LLM **déclare** les jours bloqués
   (`blocked_days`), le moteur consomme, le vérificateur enforce.
6. **Allowlist = Loïc** (`FITMAS_V0_DOGFOOD_CHAT_IDS`). Token bot dédié
   (`FITMAS_V0_BOT_TOKEN`, fallback `TELEGRAM_BOT_TOKEN`) pour ne pas entrer en conflit avec
   le poller prod.

## Pièce 1 — Runner Telegram standalone (le câblage)

`scripts/dogfood_telegram.py` (script dogfood, hors noyau ; peut importer `scripts/v0_eval`
+ `runtime_v0`).

- Au démarrage : `init_db(FITMAS_V0_DB_PATH)` si absent ; construit les deps une fois
  (`build_provider_client("deepseek")` × {coach 1024, generation 4096, reply 4096}, mirror
  `_build_deps`) ; parse l'allowlist `FITMAS_V0_DOGFOOD_CHAT_IDS` ; token via
  `FITMAS_V0_BOT_TOKEN` || `TELEGRAM_BOT_TOKEN`.
- `python-telegram-bot` `Application` + `MessageHandler(filters.TEXT)`. Sur message :
  - si `chat_id` ∉ allowlist → reply court « accès dogfood non autorisé » (ou ignore) ;
  - sinon : `InputEvent(id=f"tg-{chat_id}-{message_id}", user_id=<map chat_id→int stable>,
    source="telegram", type="user_message", text=msg, payload={}, occurred_at=now)` →
    `handle_event(event, deps, turn_id=event.id)` → `context.bot.send_message(chat_id, result.reply)`.
  - `result.reply == ""` (no_send) → ne rien envoyer.
- Idempotence : `event.id` stable (message_id) → `handle_event` dé-duplique déjà.
- Pas de debounce (le dogfood solo n'en a pas besoin ; on garde simple).
- Logging : un log par tour (proposal_type, policy_action, guard ok, latence) pour observer.

Lancement : `set -a && . ./.env && set +a && .venv/bin/python scripts/dogfood_telegram.py`.

**Pas de test pytest** (intégration réseau Telegram) ; smoke = import OK + un dry-run
`handle_event` avec un FakeLLMClient (sanity du câblage, sans réseau). Preuve réelle = un
aller-retour Telegram live (Loïc).

## Pièce 2 — `get_planned_week` (voir sa semaine)

Read tool dans `tools_read.py` + schéma `tool_catalog.py`. Lit la dernière semaine committée
(`v0_planned_weeks`, la plus récente) et la rend lisible (dates, type, durée, intensité).
Permet « c'est quoi ma semaine ? » sur un tour ultérieur (sinon le coach ne peut pas la relire).
Le coach l'appelle quand l'utilisateur demande à voir/relire sa semaine planifiée. Read-only,
zéro write. Enseigné dans le prompt coach (une ligne).

## Pièce 3 — #2 Availability typée (ajuster autour des jours bloqués)

Même architecture que #1, étendue aux jours. Le LLM **déclare** les jours bloqués ce tour-ci
(il a compris « je pars mercredi-jeudi ») ; le moteur les consomme ; le vérificateur enforce.

- **`meso/model.py`** : `TypedConstraint` gagne `blocked_days: tuple[str, ...] = ()`
  (noms de jours `monday`..`sunday`). Indépendant de `restricts` (un pur indispo =
  `restricts=(), blocked_days=("wednesday","thursday")`).
- **`meso/verifier.py`** : nouveau check `_check_blocked_days` — rejette toute séance dont le
  weekday ∈ `blocked_days` ; et **relâche le plancher de charge** quand `blocked_days` non vide
  (réduction-sous-contrainte : moins de jours = moins de charge, légitime — réutilise le hook
  de relâche existant, comme `limits_intensity`).
- **`meso/runtime_tool.py`** : `propose_week(..., blocked_days: list[str] = ())` → si non vide,
  fusionne un `TypedConstraint(severity="moderate", restricts=(), blocked_days=tuple(...))`.
- **`prompts/week_generation.py`** : le générateur reçoit les jours bloqués et n'y place
  aucune séance.
- **`tool_catalog.py`** : param `blocked_days` (array d'enum weekday) sur `propose_week`.
- **`prompts/coach_system.py`** : la sous-règle **indisponibilité** passe de « note + tient »
  à « note (availability) + `propose_week(blocked_days=[...])` dans le MÊME tour », empathie,
  proposition à confirmer. (Symétrique de la blessure.)
- **`meso/context.py`** : `fact_to_constraint` pour `availability` reste **None** (pas de
  parsing du texte du fait). Les jours bloqués viennent du **param déclaré** (same-turn).
  **Persistance cross-tour différée** (stocker des jours typés sur le fait = schéma + ingestion
  typée = follow-up ; pas requis pour le dogfood v1).
- **Anti-gaming différé** (cohérent avec #1).

Preuve : couche 1 (verifier rejette séance sur jour bloqué + accepte semaine réduite ; runtime_tool
merge ; intégration same-turn comme `test_readapt_injury_same_turn`) + couche 2
(`probe_live_simulation --persona indispo` : oracle durci — re-propose une semaine **sans séance
les jours bloqués**, same-turn).

## Repo public (après dogfood prouvé)

- **Secrets** : déjà gated (`.gitignore` couvre `.env`, `*.db`, `exports/runtime-v0/` ; zéro
  secret committé — vérifié). Re-check final avant flip.
- **README.md racine** : README racine — pitch (coach IA fiable,
  LLM-first + vérificateur déterministe), la thèse evals/fiabilité, l'archi V0 (la boucle),
  les preuves (253 tests, couche 2), comment lire le repo (PROJECT/AGENTS/docs), quickstart,
  licence. Cible : lisible par un lecteur externe.
- **Flip visibilité** : `gh repo edit --visibility public` — **action sortante irréversible-ish,
  confirmation Loïc explicite avant de flipper.**

## Séquence (dé-risque le deadline)

1. Pièce 1 (runner) → **dogfoodable ce soir** sur la boucle prouvée (propose/confirm/blessure).
2. Pièce 2 (`get_planned_week`).
3. Pièce 3 (#2 availability).
4. Preuve Telegram live (Loïc).
5. README + flip public (confirmation Loïc).

Si l'horloge gagne : la ligne de coupe est après la pièce 1 (dogfoodable injury-loop ce soir,
#2 + public demain).

## Hors scope (ne pas ouvrir)

Suivi d'exécution (phase 2), matérialisation → `v0_scheduled_sessions`, bridge DB legacy,
flag dans l'API legacy (W2), deploy Fly, persistance cross-tour de l'availability, anti-gaming,
modify/préférence (#3), heartbeat.
