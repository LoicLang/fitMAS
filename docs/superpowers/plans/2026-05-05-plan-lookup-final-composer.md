---
summary: implementation plan for routing plan-lookup replies through the final reply composer with factual drift guards
read_when:
  - extending final_reply.py to factual read-only turns
  - modifying plan_lookup handling in conversation_pipeline.py
  - debugging a coach reply that changed a day, duration, date, zone, distance or status during final composition
---

# Plan-Lookup Final Composer

## Objectif

Faire passer les tours `plan_lookup` par `final_reply.py` sans relacher la
factualite.

`plan_lookup` est proche de `no_change` parce qu'aucune mutation planning ne
doit etre commit. Il est plus strict parce que le user demande une verite
systeme : plan actuel, seance du jour, seance de demain, historique, volume,
statut.

## Perimetre du slice

- `turn_plan.primary_intent="plan_lookup"`
- decision finale `CoachDecision(response_type="no_change")`
- compat legacy `MutationDecision(mutation_type="no_change")`
- composer final dedie `compose_plan_lookup_reply`
- fallback sur le brouillon LLM initial si le composer echoue ou derive

Hors scope :

- mutation planning ;
- pending confirmation ;
- verification exhaustive par DB diff ;
- parsing du texte utilisateur libre.

## Guard factualite

Le guard compare deux artefacts LLM :

- source : brouillon LLM initial ;
- sortie : reply finale composee.

Il extrait seulement des tokens factuels sensibles dans ces artefacts :

- nombres, durees, distances ;
- zones type `Z2` ;
- jours relatifs ou nommes ;
- statuts plan/execution courants.

La reply composee doit conserver exactement cet ensemble de tokens. Si elle
ajoute `40` quand le brouillon disait `36`, ou remplace `mercredi` par `jeudi`,
elle est rejetee et le pipeline garde le brouillon initial.

Ce n'est pas un parser utilisateur. Le texte user libre reste compris par le
LLM ; le code verifie uniquement une transformation post-LLM.

## Flux cible

```text
LLM turn planner -> primary_intent=plan_lookup
LLM decide/tools -> CoachDecision(no_change)
backend -> FinalReplyContext(plan_lookup)
composer -> reply candidate
fact-token guard -> allow | fallback original draft
```

## Gates

- `response_mode=plan_lookup_composed` quand le composer reussit.
- `final_reply_capability=plan_lookup` dans `context_json`.
- un changement de chiffre/jour/statut dans la reply candidate est refuse.
- les tests gardent `no_change_composed` intact.
