---
summary: reference courte du prototype Runtime V0 et de ses preuves actuelles
read_when:
  - modifier backend/src/fitmas/runtime_v0
  - lancer la matrix provider V0
  - comparer le prototype au scope dogfood
  - verifier les limites d'isolation du noyau V0
---

# Runtime V0

## Role

`backend/src/fitmas/runtime_v0/` est le noyau experimental qui a valide la
troisieme voie :

```text
LLM propose
backend valide
executor commit
audit prouve
guard protege la reply
```

Il reste un laboratoire stable tant que l'integration produit n'est pas prouvee.
Le scope produit vit dans `docs/V0-DOGFOOD-SCOPE.md`.
La migration vit dans `docs/RUNTIME-MIGRATION-PLAN.md`.

L'ancienne spec longue est archivee :

```text
docs/archive/runtime-v0-implementation-spec-2026-05-24.md
```

## Boucle

```text
InputEvent
-> WorldSnapshot
-> CoachAgent
-> ActionProposal
-> RuntimePolicy
-> CommandExecutor
-> RuntimeResult
-> ReplyComposer
-> OutputGuard
-> Audit
```

## Isolation

Le noyau V0 ne doit pas importer :

```text
fitmas.decision
fitmas.domain
fitmas.llm
fitmas.skills
fitmas.tools
fitmas.app
```

Adapters vers le produit existant doivent vivre a part.
Ils peuvent dependre de l'existant, mais le noyau doit rester testable offline.

## Scenarios Actuels

```text
current_plan
tomorrow
skipped_yesterday
execution_correction
followup_planning_turn1
key_session_pending
explicit_lighten
replace_by_easy_bike
hard_unsafe_block
partial_yesterday
undo_wrong_status
```

Commandes :

```bash
pytest tests/runtime_v0

python3 scripts/v0_eval/run_matrix.py \
  --provider fake \
  --repetitions 1 \
  --export-dir exports/runtime-v0/stability-fake-final

python3 scripts/v0_eval/run_matrix.py \
  --repetitions 5 \
  --export-dir exports/runtime-v0/stability-providers-5x
```

## Derniere Preuve Exportee

Source :

```text
exports/runtime-v0/stability-providers-5x/matrix-report-recomputed.md
```

Resultat :

```text
fake matrix: 11/11
provider matrix: 114/120
wrong_write: 0
old_plan_date: 0
wrong_correction_target: 0
reply_claim_without_event: 0
guard_repair_rate: 5.7%
sanitized_fallback_rate: 0%
```

Les echecs restants sont surtout des artifacts provider manquants ou replies
hors contrat, pas des writes dangereux.

## Budget

Budget runtime core, hors tests et scripts :

```text
objectif sain: <= 2500 LOC
zone acceptable: 2500-3200 LOC
> 3200 LOC: justification obligatoire
> 4000 LOC: alerte architecture lourde
```

## Sport Core V0

`backend/src/fitmas/runtime_v0/sport_rules.py` centralise les premiers
garde-fous :

- source `done` protegee ;
- hard proche d'un hard/long bloque ;
- fact `health` actif bloque une creation de hard ;
- multi-operation demande confirmation ;
- seance `key` demande confirmation.

## Prochaine Evolution Autorisee

Dans le noyau V0 :

- scenarios dogfood proches ;
- guards/retry si prouves par matrix ;
- pas d'API Telegram directe.

Hors noyau V0 :

- adapters DB actuelle ;
- adapters executor vers writers existants ;
- endpoint/Telegram sous flag.

## Regle De Decision

Ne pas optimiser le style du runtime tant que les gates produit ne passent pas.
Chaque changement doit servir un scenario, une safety metric ou un adapter de
dogfood.
