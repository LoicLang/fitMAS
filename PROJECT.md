# FitMAS

Coach IA multisport proactif qui ajuste l'entrainement selon la vraie vie.

## Statut — 21 mai 2026

Le chantier actif est le **Decision Runtime refactor**.

Phrase guide :

> Je ne veux pas un refactor plus complet. Je veux un runtime plus petit.

Le produit reste :

- Telegram = coach conversationnel.
- App = cockpit de lecture.
- `ScheduledSession + Activity + Events` = verite runtime.
- LLM-first pour comprendre le texte utilisateur.
- Determinism-first pour verite, validation, policy, writes et audit.

## Etat Technique Court

Deja en place :

- `decision/` : types centraux, outcomes, composer, verifier, command bus.
- `domain/planning/` : candidates, evaluator, policy, mutation service.
- `llm/` : gateway, prompts, compat legacy isolee, reply backends.
- `skills/heartbeat/` : heartbeat runtime, reply composer, tool loop.
- `app/api/` et `app/telegram/` : entrypoints en migration.

Encore a reduire :

- `conversation_pipeline.py` reste le mega-orchestrateur.
- `legacy/` contient encore `6` modules, dont `__init__.py`.
- Le prochain gros morceau est supprimer la compat `CoachDecision` restante :
  contrats, artifact, adapters et `llm/decision_legacy.py`.

Dernieres preuves locales :

- backend complet : `1423 passed, 11 skipped`.
- smoke core API : OK.
- fallback census core : `0`.

## Prochaine Tranche

Apres 10K : reste `CoachDecision` compat.

Objectif :

- convertir les derniers artifacts compat en outcomes directs ;
- supprimer `legacy/decision_contracts.py`, `legacy/coach_decision_artifact.py`
  et les adapters associes quand leurs callers sont vides ;
- isoler ou supprimer `llm/decision_legacy.py` ;
- reduire `conversation_pipeline.py`.

## Ordre De Lecture

1. `AGENTS.md`
2. `PROJECT.md`
3. `docs/README.md`
4. `docs/BUILD-ORDER.md`
5. `docs/DECISION-RUNTIME-REFACTOR.md`
6. `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
7. `docs/SYSTEM-MAP.md`
8. `docs/RUNBOOK.md`

## Commandes

```bash
./scripts/docs:list
./scripts/test-backend
```

Smoke core :

```bash
./scripts/smoke-a-plus-api --skip-generated-week \
  --scenario lookup_current_plan \
  --scenario create_easy_free_day \
  --fallback-census-json /tmp/fitmas-core-census.json \
  --timeout 420
```

## Principes

- Pas de regex/keywords sur texte utilisateur libre.
- Pas de write DB hors writer/command service.
- Pas de reply visible depuis un helper opportuniste.
- Pas de fallback local pour masquer une frontiere floue.
- Pas de prompt enorme qui leak des tests comme exemples.
- Ne pas ouvrir Phase B progression/prescription sans demande explicite.
