---
summary: contrat court des tools runtime FitMAS et de leurs limites
read_when:
  - ajouter un tool runtime
  - modifier tools/registry.py ou tools/runtime.py
  - brancher le LLM sur une lecture metier
  - mesurer latence ou cout d'un tool call
---

# Runtime Tools

## Role

Les tools donnent au LLM une lecture bornee de la verite systeme.
Ils ne sont pas un second runtime.

Un tool peut :

- lire ;
- resoudre une reference deja structuree ;
- valider ;
- construire une candidate sans write.

Un tool ne doit pas :

- ecrire en DB ;
- livrer un message ;
- decider un commit ;
- parser le texte utilisateur libre ;
- remplacer la policy backend.

## Modules

```text
backend/src/fitmas/tools/
  contract.py
  registry.py
  runtime.py
  metrics.py
  routing.py
  replan_proposal.py
```

Les anciens wrappers root `tool_contract.py`, `tool_registry.py`,
`tool_runtime.py` et `tool_metrics.py` sont supprimes.
Ne pas les recreer.

## Categories

| Type | Exemple | Write |
| --- | --- | --- |
| read | `get_plan_window`, `get_recent_activities` | non |
| validation | `validate_plan_patch`, `validate_week_coherence` | non |
| candidate | draft/candidate replan | non |

Les writes viennent apres, via command/mutation services.

## Budget

Le runtime tool doit rester borne :

- nombre de rounds limite ;
- nombre de tools limite par capability ;
- dedup des appels identiques dans un meme tour ;
- resultat explicite pour chaque `tool_use_id` ;
- metrics par call.

Si un tour devient lent, reduire la surface exposee ou sortir la review longue
du chemin synchrone.

## LLM-First

Le code peut choisir une capability autorisee.
Il ne peut pas choisir cette capability par regex/keywords sur `user_text`.

Le LLM choisit les tools utiles dans la surface offerte.
Le backend valide les artefacts produits.

## Planning

Le prochain etat cible :

```text
RequestedPlanChange
-> backend candidates
-> evaluator
-> policy
-> mutation service
```

Les tools candidats ne doivent pas redevenir une route planning parallele.
Quand une lane est couverte par `domain/planning/`, supprimer le fallback tool
legacy correspondant.

## Heartbeat

Heartbeat utilise aussi les tools, mais comme source d'event proactif bornee.

Regle :

- read/validation/candidate autorises selon role ;
- pas de write direct ;
- pas de reply hors `skills/heartbeat/reply_composer.py` puis verifier/outcome.

## Observabilite

A tracer :

- tool name ;
- kind ;
- latency ;
- empty result ;
- error/block reason ;
- fallback census si route legacy utilisee.

Tests importants :

- `tests/test_tool_runtime.py`
- `tests/test_llm_understanding_service.py`
- tests d'isolation et de matrix Runtime V0 si le tool touche le nouveau noyau.
