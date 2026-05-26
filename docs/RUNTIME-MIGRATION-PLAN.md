---
summary: plan de migration du prototype Runtime V0 vers le produit FitMAS dogfood
read_when:
  - brancher Runtime V0 a Telegram ou API
  - creer des adapters entre DB actuelle et runtime_v0
  - decider quand promouvoir runtime_v0 vers runtime
  - isoler ou supprimer un ancien chemin conversationnel
---

# Runtime Migration Plan

## Decision

On ne repart pas de zero.

```text
repo actuel = enveloppe produit
runtime_v0 = noyau cible prouve
ancien pipeline = legacy a etrangler
```

Le bon chantier n'est plus un gros refactor.
Le bon chantier est un pont propre entre l'existant et le Runtime V0.

## Strategie

Garder `backend/src/fitmas/runtime_v0/` intact comme laboratoire valide.

Ajouter progressivement des adapters :

```text
DB actuelle -> WorldSnapshot
ActionProposal -> writes actuels audites
RuntimeResult -> Telegram/API
```

Aucune ecriture produit ne doit contourner :

```text
proposal -> policy -> executor -> audit/result
```

## Phases

### Phase 0 — Reference Stable

Etat attendu :

- `runtime_v0` reste isole ;
- matrix fake/provider reproductible ;
- exports sous `exports/runtime-v0/` conserves ;
- aucune dependance vers `decision/`, `domain/`, `llm/`, `skills/`, `tools/`,
  `app/` depuis le noyau V0.

Done quand :

```text
tests/runtime_v0 verts
fake matrix 11/11
provider matrix >= 90%
danger metrics = 0
```

### Phase 1 — Snapshot Adapter

Creer un adapter hors noyau V0 :

```text
backend/src/fitmas/runtime_v0/adapters/current_db_snapshot.py
```

Role :

- lire `ScheduledSession`, `Activity`, facts actifs, pending et events recents ;
- produire un `WorldSnapshot` V0 ;
- borner les fenetres ;
- ne jamais parser le texte user ;
- ne jamais write.

Done quand :

- les scenarios read-only passent sur une copie DB actuelle ;
- aucun vieux `WeeklyPlan` / `DayPlan` ne peut etre presente comme verite runtime ;
- l'audit stocke le snapshot utile au replay.

### Phase 2 — Executor Adapter

Creer un adapter d'ecriture borne :

```text
backend/src/fitmas/runtime_v0/adapters/current_db_executor.py
```

Role :

- convertir les commands V0 en services officiels existants ;
- ecrire seulement via writers/mutation services ;
- produire des events committe auditable ;
- rendre idempotent par `event.id` et command target.

Done quand :

- execution update/correction passe sur DB actuelle clonee ;
- move/lighten secondary passe ;
- key session cree une pending, sans appliquer le patch ;
- retry du meme `event.id` ne double pas les writes.

### Phase 3 — Interface Dogfood

Brancher sous flag :

```text
FITMAS_RUNTIME_MODE=legacy|v0
FITMAS_V0_DOGFOOD_USER_IDS=...
```

Chemin :

```text
Telegram/API
-> InputEvent
-> Runtime V0
-> RuntimeResult
-> delivery
```

Done quand :

- Loic seul peut utiliser le chemin V0 ;
- fallback legacy possible par config ;
- aucun debug endpoint actif par defaut en prod ;
- les replies visibles passent par guard.

### Phase 4 — Promotion

Quand le dogfood tient :

```text
backend/src/fitmas/runtime_v0/ -> backend/src/fitmas/runtime/
```

Promouvoir seulement apres preuve.
Ne pas renommer pour faire propre avant d'avoir stabilise l'integration.

## Frontieres Cibles

Court terme :

```text
runtime_v0/            noyau prouve
runtime_v0/adapters/   ponts vers DB actuelle
scripts/v0_eval/       matrix et reports
tests/runtime_v0/      oracles et regressions
```

Plus tard :

```text
runtime/
runtime/adapters/
runtime/eval/
domain/planning/sport_rules_v0.py
```

Ne pas creer `domains/*` par avance si la pression reelle n'existe pas.

## Risques

| Risque | Mitigation |
| --- | --- |
| Contaminer V0 avec l'ancien pipeline | adapters externes, import boundaries |
| Refaire une usine a gaz | scope dogfood strict, LOC surveillees |
| Provider flaky | matrix repetee, triage par tool trace |
| Reply sure mais mediocre | guard metrics separes de correctness |
| Double write retry Telegram | idempotence event-level + in-flight lock |
| Phase B qui aspire le chantier | `V0-DOGFOOD-SCOPE.md` gagne sur les envies de prescription |

## Ce Qu'on Ne Fait Pas Maintenant

- pas de suppression massive du pipeline actuel ;
- pas de nouveau repo ;
- pas de migration DB globale ;
- pas de Telegram complet avant adapters verifies ;
- pas de generator sportif avant snapshot/write adapters fiables ;
- pas de heartbeat autonome qui modifie le plan.

## Prochaine Tranche

1. Relancer la provider matrix ciblee sur les 11 scenarios.
2. Construire `current_db_snapshot` sur copie DB.
3. Construire `current_db_executor` sur clone DB.
4. Brancher Telegram V0 pour user allowlist.
