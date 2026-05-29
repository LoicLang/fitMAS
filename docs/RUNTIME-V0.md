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

`followup_planning_turn2` existe aussi comme tour de continuation, hors matrix
par defaut (lancer via `--scenario followup_planning_turn2`).

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

## Derniere Preuve

Verifie offline le 29 mai 2026 :

```text
tests/runtime_v0 + docs   : 143 passed
fake matrix               : 11/11
wrong_write               : 0
old_plan_date             : 0
wrong_correction_target   : 0
reply_claim_without_event : 0
```

Provider matrix : le chiffre historique `114/120` vient d'une run a
6 scenarios (4 providers x 6 x 5 reps = 120). La matrix par defaut compte
aujourd'hui 11 scenarios x 3 providers cibles (165 runs en 5x). Gemini reste
disponible en opt-in manuel, mais n'est plus lance par defaut tant que le
credit API est absent. L'export
`exports/runtime-v0/stability-providers-5x/` n'est pas committe. A rejouer
pour un chiffre provider a jour :

```bash
python3 scripts/v0_eval/run_matrix.py --repetitions 5 \
  --export-dir exports/runtime-v0/stability-providers-5x
```

Les echecs provider restants observes etaient surtout des artifacts manquants
ou replies hors contrat, pas des writes dangereux.

Real-turn spike : `scripts/v0_eval/spike_real_turn.py` reconstruit maintenant
les sessions depuis les lignes de grounding capturees dans
`conversation_turns.context_json` quand elles existent. Cela evite de juger un
provider sur `scheduled_sessions` deja mute apres le tour. Les facts, sessions
et activites crees apres `as_of` sont exclus. Si aucun grounding capture n'est
disponible, le spike retombe sur `current_state` et ce resultat ne doit pas
servir a blamer un provider.

Cas #151 (`Echange aujourd'hui et demain`) : avec le contexte capture, DeepSeek,
Grok et Mistral produisent tous un `plan_patch`. L'ancien diagnostic
`planning_date_not_resolved` venait du banc de replay, pas des modeles. Le point
restant est une difference de policy : V0 auto-commit le swap simple, alors que
l'app legacy demandait confirmation.

## Evaluation

La matrix separe deux niveaux :

```text
correctness = proposal, policy, commands, dates finales et danger metrics
reply quality = wording visible attendu ou interdit
```

Le wording visible ne fait plus echouer la correctness.
Il alimente les compteurs `reply_quality_issue_count`,
`reply_missing_expected_text_count` et `reply_contains_forbidden_text_count`.
Les claims dangereux restent bloquants, par exemple une reply qui annonce une
mutation sans event committe.

## Budget

Budget runtime core, hors tests et scripts :

```text
objectif sain: <= 2500 LOC
zone acceptable: 2500-3200 LOC
> 3200 LOC: justification obligatoire
> 4000 LOC: alerte architecture lourde
```

Mesure 29 mai 2026 : 3053 LOC (zone acceptable, plus dans l'objectif sain).

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
