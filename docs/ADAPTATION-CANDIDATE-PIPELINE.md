---
summary: contrat court du pipeline planning par candidats
read_when:
  - modifier domain/planning/*
  - ajouter une adaptation planning
  - supprimer un fallback planning legacy
  - toucher a PlanPatch, candidates, evaluator ou policy
---

# Adaptation Candidate Pipeline

## Doctrine

```text
Le LLM comprend la demande.
Le backend construit les options.
Le moteur mesure les consequences.
La policy prend la responsabilite.
Le composer raconte la verite.
```

FitMAS ne commit jamais une adaptation parce qu'un LLM l'a formulee.

## Pipeline Cible

```text
RequestedPlanChange
-> ReferenceResolver
-> PlanCandidateBuilder
-> PlanCandidateEvaluator
-> SportPolicy
-> PlanningCommandService / PlanMutationService
-> PlanMutationEvent ou pending/block
-> DecisionOutcome
-> ReplyComposer
```

## Modules Actuels

```text
backend/src/fitmas/domain/planning/
  models.py
  reference_resolver.py
  reference_tokens.py
  candidate_builder.py
  evaluator.py
  policy.py
  decision_service.py
  mutation_service.py
  patch_summary.py
  session_actions.py
```

Compat encore surveillee :

- `legacy/conversation_canonical_planning_bridge.py`
- `legacy/conversation_planning_bridge.py`
- `legacy/planning_runtime_adapter.py`
- `legacy/planning_outcome_adapter.py`
- `legacy/plan_patch_reply_adapter.py`

## Verites

- `ScheduledSession` est la verite planning runtime.
- `Activity` et execution events sont la verite du reel.
- `PlanPatch` est un langage de changement backend, pas une verite finale.
- `WeekCoherenceScore` / findings aident la policy, mais ne parlent pas au user.

## Decisions Possibles

| Decision | Sens |
| --- | --- |
| commit | mutation appliquee et event committe |
| pending_confirmation | proposition unique a confirmer |
| pending_choice | choix entre options bornees |
| block | rien applique, raison explicite |
| no_change | aucun changement necessaire |

La reply ne peut claim qu'un commit prouve par event.

## Interdits

- Construire une candidate depuis regex/keyword sur texte utilisateur libre.
- Laisser le LLM produire le patch final applicable sans validation.
- Bypasser evaluator/policy pour une lane deja couverte.
- Creer une pending duplicate pour la meme intention.
- Faire parler un adapter planning directement au user.

## Prochain Chantier

10E doit reduire planning/pending legacy :

1. mesurer les callers reels ;
2. extraire l'actif vers `domain/planning/` ou `decision/` ;
3. supprimer les bridges vides ;
4. shrinker `conversation_pipeline.py`.

Critere :

```text
Une adaptation planning suit une seule route observable.
```
