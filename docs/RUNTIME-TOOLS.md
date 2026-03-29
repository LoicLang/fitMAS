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
- `resolve_planning_window`
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

### `tool_routing.py`

Role :
- router de facon deterministe une requete utilisateur vers un petit sous-ensemble de tools
- eviter d'offrir tout le registry a chaque question
- garder l'ordre metier des tools presentes au modele

Etat actuel :
- actif pour le pipeline `conversation`
- categories V1 :
  - rappel planning
  - highlights activite
  - activites recentes
  - rappel memoire/facts
- nouveaux usages cibles :
  - grounding d'une contrainte future sur une vraie fenetre planning
- si le message est simple (`ok`, retour libre, adaptation simple), aucun tool n'est offert

### `conversation_prompting.py`

Role :
- choisir une politique de prompt selon le type de requete
- reduire le `context dump` pour les requetes de lecture outillees
- garder un comportement full-context pour les cas mutation / conversation libre

Etat actuel :
- `activity_highlights` et `recent_activities` utilisent un prompt compact
- `plan_lookup` garde l'ancrage planning mais coupe les blocs inutiles comme les signaux
- `fact_recall` garde surtout le temps local + la memoire utile
- la policy choisie remonte maintenant dans les traces tools via `context_policy`

### `tool_metrics.py`

Trace minimale :
- `tool_offered`
- `context_policy`
- `tool_requested`
- `tool_called`
- `tool_count_offered`
- `history_messages_used`
- `prompt_char_count`
- `tool_name`
- `tool_latency_ms`
- `tool_success`
- `tool_error`
- `fallback_used`
- `llm_round_trips`
- `prompt_tokens_estimate`
- `response_tokens_estimate`
- `total_duration_ms`
- `response_stop_reason`

V1 :
- logs structures uniquement
- pas de table SQL dediee pour l'instant
- `tool_runtime.py` logge toujours l'execution d'un tool concret
- `llm.py` logge maintenant aussi la session tool-use du chat :
  - tools offerts mais non utilises
  - boucle tool complete
  - fallback JSON apres tool loop casse
  - erreur de premier ou second round-trip

## Pipelines

### Conversation

Premiere cible.

Le chat reste sur son pipeline actuel :
- context assembly
- decide
- mutation / reponse

Les tools sont une extension future, pas un remplacement.

Etat actuel :
- le chat peut maintenant faire **1 tool call max** sur certaines requetes de lecture evidentes
- activation bornee par `tool_routing.py`
- le prompt du chat commence aussi a se compacter via `conversation_prompting.py`
- puis reponse finale JSON comme avant
- chaque tour outille produit maintenant une trace session-level exploitable pour mesurer :
  - si les tools ont ete seulement offres
  - si le modele les a effectivement demandes
  - si le 2e round-trip a abouti
  - combien de tokens ont ete consommes sur la boucle

Cas typiques :
- "c'etait quoi ma plus longue sortie ?"
- "il me reste quoi cette semaine ?"
- "qu'est-ce que tu sais de mes contraintes ?"

Cas futur prepare :
- `je ne suis pas dispo demain soir`
- le LLM n'a pas a deviner la seance cible
- il peut s'appuyer sur `resolve_planning_window`

Ce que le chat ne fait pas encore :
- pas de tool call pour les mutations simples
- pas de tool call en boucle
- pas de write tool

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
3. tool use borne dans `decide()` pour quelques questions de lecture
4. reduction du context dump guidee par les metriques

Pas de liberte large du modele avant d'avoir :
- mesure
- logs
- cas d'usage prouvés
