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
  adaptation_decision.py
  candidate_builder.py
  candidates.py
  contract.py
  decision_service.py
  evaluator.py
  models.py
  mutation_decision.py
  mutation_service.py
  patch_mutation_service.py
  patch_summary.py
  plan_patch.py
  policy.py
  reference_resolver.py
  reference_tokens.py
  reviewer.py
  session_actions.py
  validator.py
  week_coherence.py
```

Planning/pending legacy est clos :

- les bridges `legacy/conversation_*planning*` sont supprimes ;
- `decision/turn_planning_route.py` porte la route conversationnelle ;
- `decision/planning_runtime.py` et `decision/planning_outcomes.py` portent
  l'adaptation runtime ;
- `decision/plan_patch_reply.py` porte les replies PlanPatch historiques.

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

## Etat Actuel

La route planning observable est unique pour les lanes couvertes.

Avant de modifier ce pipeline :

- verifier si le cas appartient au scope V0 dogfood ;
- lancer les scenarios Runtime V0 utiles ;
- classer les bugs par couche ;
- corriger dans l'owner responsable, sans fallback local.

Critere stable :

```text
Une adaptation planning suit une seule route observable.
```
