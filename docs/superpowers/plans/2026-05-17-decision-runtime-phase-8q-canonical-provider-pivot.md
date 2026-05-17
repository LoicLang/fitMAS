---
summary: implementation plan for Decision Runtime Phase 8Q canonical provider pivot
read_when:
  - implementing Decision Runtime Phase 8Q
  - skipping legacy CoachDecision for canonical non-planning lanes
  - changing conversation_pipeline.py decide ordering
  - debugging FITMAS_CANONICAL_PROVIDER_NON_PLANNING
---

# Decision Runtime Phase 8Q — Canonical Provider Pivot

## Objectif

Faire de `CoachUnderstanding` la source provider canonique pour les lanes
non-planning deja consommables, sans ouvrir le planning par defaut.

Le runtime doit :

```text
run canonical Understanding
-> if non-planning and actionable, skip legacy decide()
-> build a compatibility LegacyCoachDecisionArtifact
-> let existing command/pending/reply bridges consume canonical data
-> otherwise fallback to legacy CoachDecision
```

## Contraintes

- Pas de parsing deterministe du texte utilisateur libre.
- Pas de `PlanPatch` produit par Understanding.
- Pas de write direct.
- Pas de nouveau reply path visible.
- Planning toujours fallback legacy / cutover opt-in.
- `LegacyCoachDecisionArtifact` reste compat, pas nouvelle autorite produit.

## Implementation

1. Ajouter `FITMAS_CANONICAL_PROVIDER_NON_PLANNING`, default-on avec opt-out.
2. Ajouter le gate
   `should_use_canonical_understanding_without_legacy(...)`.
3. Refuser explicitement :
   `intent=plan_change`, `requested_change`, Understanding absent, pending non
   actif, commandes absentes.
4. Ajouter `coach_decision_artifact_from_understanding(...)` :
   `source="coach_understanding"`, pas de patch, pas d'actions legacy.
5. Reordonner `conversation_pipeline.py` :
   Understanding avant `run_legacy_coach_decision(...)`.
6. Si le gate passe, sauter `decide()` et tracer
   `legacy_decide.legacy_skipped=True`.
7. Si le gate echoue, conserver strictement le fallback legacy existant.

## Tests

- `tests/test_conversation_understanding_bridge.py`
  - default-on provider pivot pour commandes canoniques ;
  - default-on provider pivot pour pending canonique ;
  - planning conserve legacy ;
  - artifact compat est non-mutant et user-safe.
- `tests/test_phase8q_canonical_provider_pivot_architecture.py`
  - bridge expose le nouveau flag et le gate ;
  - pipeline lance Understanding avant legacy decide ;
  - wrapper smoke deterministe uniquement.
- `scripts/smoke-decision-runtime-canonical-provider-pivot`
  - tests 8Q + command/pending bridges ;
  - wrapper 8P imbrique.

## Critere d'acceptation

```text
Canonical non-planning actionable turns no longer need legacy decide().
Planning and non-actionable turns still have an explicit legacy fallback.
No new write, prompt, regex parser, or visible reply path is introduced.
```
