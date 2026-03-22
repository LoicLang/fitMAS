---
summary: contrat des tools runtime FitMAS, limites, registry V1 read-only et métriques associées
read_when:
  - ajouter un tool runtime
  - brancher le LLM sur des tools
  - mesurer la latence ou le coût des tool calls
  - modifier tool_runtime.py ou tool_registry.py
---

# Runtime Tools

## But

Donner au coach FitMAS quelques tools runtime cibles sans passer a un systeme agentique libre.

Objectifs :
- lire une verite metier ponctuelle quand le prompt statique ne suffit pas
- garder un seul orchestrateur LLM
- rester auditables
- mesurer l'impact reel avant d'augmenter la liberte du modele

## Ce qu'on fait

- tools `read-only`
- whitelist par pipeline
- 1 registre explicite
- 1 executor borne
- metriques systematiques a chaque appel tool

## Ce qu'on ne fait pas

- pas de multi-agent
- pas d'acces DB brut donne au modele
- pas de write tool
- pas de boucle infinie de tool calls
- pas de `multi_mutate` pour l'instant

## Modules

### `tool_contract.py`

Contrat minimal :
- `ToolCall`
- `ToolResult`
- `ToolContext`
- `ToolSpec`

### `tool_registry.py`

Registry V1 :
- `get_today_context`
- `get_plan_window`
- `get_recent_activities`
- `get_activity_highlights`
- `get_relevant_facts`

Tous ces tools lisent des objets deja charges par l'orchestrateur.

### `tool_runtime.py`

Role :
- valider le tool demande
- verifier qu'il est autorise pour le pipeline
- executer
- produire une trace metrique

### `tool_metrics.py`

Trace minimale :
- `tool_requested`
- `tool_called`
- `tool_name`
- `tool_latency_ms`
- `tool_success`
- `tool_error`
- `fallback_used`
- `llm_round_trips`
- `prompt_tokens_estimate`
- `response_tokens_estimate`
- `total_duration_ms`

V1 :
- logs structures uniquement
- pas de table SQL dediee pour l'instant

## Pipelines

### Conversation

Premiere cible.

Le chat reste sur son pipeline actuel :
- context assembly
- decide
- mutation / reponse

Les tools sont une extension future, pas un remplacement.

### Heartbeat

Pas encore branche sur le runtime tools.
Le heartbeat reste surtout deterministic + contexte preassemble.

### Planning

Pas encore branche sur le runtime tools.
Le planner V2 doit d'abord passer par `planning_state.py` et `PlanningDecision`.

## Decision CTO

Le bon ordre :
1. signaux filtres dans le chat
2. runtime tools read-only + metrics
3. eventuel tool use dans `decide()`
4. reduction du context dump guidee par les metriques

Pas de liberte large du modele avant d'avoir :
- mesure
- logs
- cas d'usage prouvés
