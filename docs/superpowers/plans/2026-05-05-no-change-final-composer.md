---
summary: implementation plan for routing no-change conversation replies through the final reply composer
read_when:
  - extending final_reply.py to more conversation paths
  - modifying no_change handling in conversation_pipeline.py
  - debugging coach replies that sound constrained by CoachDecision.fitmas_message
---

# No-Change Final Composer

## Objectif

Faire passer les tours conversationnels `no_change` par la couche finale
`final_reply.py`, sans changer la decision machine ni les writers.

## Perimetre du slice

- `CoachDecision(response_type="no_change")`
- compat legacy `MutationDecision(mutation_type="no_change")`
- aucun changement planning autorise
- aucune confirmation pending creee
- les actions non-planning deja appliquees (`memory_actions`,
  `execution_actions`) sont transmises comme faits backend au composer

Hors scope :

- `plan_lookup`
- pending confirmations
- mutations appliquees ou bloquees
- refonte globale du prompt voix

## Flux cible

```text
LLM decide -> no_change / legacy no_change
  -> backend applique les actions memoire/execution deja structurees
  -> FinalReplyContext(no_change)
  -> final_reply composer
  -> user
```

Si le composer est desactive ou invalide, le pipeline garde le brouillon LLM
initial. Ce fallback reste LLM-first : il ne vient pas d'une template backend.

## Gates

- `no_change` compose une reponse finale distincte du brouillon quand le composer
  reussit.
- `response_mode=no_change_composed` trace le chemin.
- les facts d'execution appliquee sont transmis au composer pour eviter
  d'oublier une seance notee faite/non faite.
- aucun parsing du texte utilisateur libre.
