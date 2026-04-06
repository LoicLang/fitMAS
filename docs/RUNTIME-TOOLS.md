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
- reduire le contexte injecte avant de multiplier les tools

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
- pas de skill system formel tant qu'on n'a pas assez de workflows repetes

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
- classifier l'intent utilisateur en 9 categories deterministes
- mapper chaque intent a un budget de tools borne
- eviter d'offrir tout le registry a chaque question

Architecture V2 (intent-based) :
- `classify_intent()` → `IntentCategory` (enum)
- `route_tools_for_query()` → `ToolRoutingDecision` avec intent + tool_names
- plus de matching regex fragile : classification par heuristiques layered

Categories d'intent :
| Intent | Tools offerts |
|--------|--------------|
| `casual_chat` | aucun |
| `execution_report` | today_context, recent_activities |
| `plan_negotiation` | today_context, plan_window, load_context, relevant_facts |
| `plan_lookup` | today_context, plan_window |
| `activity_review` | recent_activities |
| `activity_highlights` | activity_highlights, recent_activities |
| `load_review` | load_context, recent_reality_window |
| `fact_recall` | relevant_facts |
| `generic_question` | today_context, plan_window, recent_activities |

### `conversation_prompting.py`

Role :
- choisir une politique de prompt selon l'intent (preferred) ou le routing_reason (legacy)
- reduire le `context dump` pour les requetes de lecture outillees
- garder un comportement full-context pour les cas mutation / conversation libre

Etat actuel :
- chaque `IntentCategory` a une policy dediee (`_INTENT_POLICIES` map)
- `casual_chat` utilise un prompt minimal (pas de timeline, pas de signals)
- `plan_negotiation` utilise le prompt le plus riche (signals + facts + timeline + execution)
- le fallback legacy par `routing_reason` reste pour la compatibilite arriere
- la policy choisie remonte dans les traces tools via `context_policy`
- le chemin live `llm.decide()` utilise maintenant le builder layered plutot que l'ancien builder monobloc

### `prompt_layers.py`

Role :
- structurer le prompt en 5 couches explicites avec budgets token independants
- permettre le prompt caching Anthropic sur les couches stables (L0, L1)
- compacter automatiquement les couches qui depassent leur budget

Couches :
| Level | Nom | Budget | Cacheable | Frequence de changement |
|-------|-----|--------|-----------|------------------------|
| 0 | identity | 300 tok | oui | jamais |
| 1 | profile | 400 tok | oui | par session |
| 2 | plan | 800 tok | non | par semaine |
| 3 | immediate | 600 tok | non | par tour |
| 4 | memory | 500 tok | non | par tour |

### `mutation_hooks.py`

Role :
- valider les mutations avant application (pre-hooks)
- calculer l'impact apres application (post-hooks)
- declencher une recalibration si seuil franchi

Pre-hooks :
- `plausibility_check` : bloque les moves vers une date passee
- `fragile_day_check` : warn si collision avec une seance intense
- `load_coherence_check` : warn si depassement du max hard sessions/week

Post-hooks :
- `calculate_impact` : delta charge, duree, seances cle affectees, recovery perdu
- `build_mutation_log` : entree structuree pour audit
- `recalibration_trigger` : flag si impact significatif

### `api_ops.py`

Role :
- surface operateur separee du tool plane conversationnel
- endpoints `/ops/` pour debug, inspection et triggers manuels
- auth debug distincte

Endpoints :
- `GET /ops/signals` : signaux actifs
- `POST /ops/heartbeat/{kind}` : trigger manuel heartbeat
- `GET /ops/memory` : etat memoire complet
- `GET /ops/mutations/recent` : log mutations recentes
- `GET /ops/tool-stats` : stats d'usage tools
- `POST /ops/reset` : reset destructif

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
- le prompt du chat passe maintenant par `conversation_prompting.py` + `prompt_layers.py` sur le chemin live
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
1. prompt 2 zones + caching sur la partie stable
2. routing deterministe vers tres peu de tools offres
3. runtime tools read-only semantiques + metrics
4. tool use borne dans `decide()` pour quelques questions de lecture
5. transcript structure de session avant toute sophistication plus large

Notes de sequencing :

- `transcript structure > compaction` a ce stade
- les tools doivent rester etroits : plan, reel recent, charge, contraintes, contrat seance
- pas de write tools avant d'avoir des permission tiers propres sur les mutations

Pas de liberte large du modele avant d'avoir :
- mesure
- logs
- cas d'usage prouvés
