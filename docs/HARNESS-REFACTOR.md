---
summary: plan de refactor harness FitMAS, ordre d'implementation, statut des phases et verification concrete
read_when:
  - lancer le refactor du harness conversationnel
  - suivre l'avancement des phases prompt cache transcript permissions
  - reprendre un chantier structurel sur api_messages.py llm.py heartbeat.py ou repository.py
---

# Harness Refactor

## But

Faire evoluer FitMAS sans casser le contrat produit.

Principe :

- refactor par petites phases
- comportement stable au debut
- tests a chaque phase
- doc d'avancement vivante

## Axes directeurs

1. `api_messages.py` devient un endpoint mince
2. le prompt conversationnel passe en 2 zones avec cache breakpoint
3. les mutations passent par une policy d'impact explicite
4. le transcript devient une vraie unite d'audit
5. `repository.py` se vide progressivement derriere une facade
6. `heartbeat.py` se split en evaluation / generation / delivery

## Phases

### Phase 0 — hygiene repo

Objectif :

- tests backend relancables sans friction locale
- artefacts de smoke ignores
- doc de chantier posee

Statut :

- [x] `.tmp-*` ignores dans git
- [x] bootstrap import tests backend via `tests/conftest.py`
- [x] wrapper `./scripts/test-backend`
- [x] ce document pose
- [x] runbook aligne

Verification :

- `./scripts/test-backend -q tests/test_conversation_prompting.py tests/test_tool_routing.py tests/test_llm_json.py tests/test_llm_tools.py`
- `cd frontend && npm test -- --run`

### Phase 1 — contrat de tour + pipeline conversation

Objectif :

- extraire l'orchestration hors de l'endpoint HTTP
- introduire un contrat de tour typé
- garder le comportement produit stable

Statut :

- [x] `ConversationTurnInput`, `ConversationTurnState`, `ConversationTurnOutcome`
- [x] pipeline conversation extrait dans `conversation_pipeline.py`
- [x] `api_messages.py` reduit a une facade HTTP + dependencies
- [x] compat monkeypatch tests preservee via injection de dependencies

Verification cible :

- subset conversation backend
- flows coeur message -> decision -> mutation

### Phase 2 — prompt 2 zones + cache breakpoint

Objectif :

- separer zone statique et zone dynamique
- brancher un vrai cache breakpoint Anthropic sur la zone statique
- sortir l'assemblage prompt du coeur de `llm.py`

Statut :

- [x] `llm_prompt_builder.py`
- [x] zone system statique cachee via bloc Anthropic ephemere
- [x] zone dynamique courte gardee dans le prompt utilisateur
- [x] `llm_gateway.py` accepte maintenant `system` structure

### Phase 3 — `profile_summary`

Objectif :

- injecter un profil compact et stable
- reduire la pile brute de facts au prompt

Statut :

- [x] `profile_summary.py`
- [x] resume deterministe injecte dans la conversation
- [x] facts volatils exclus du resume profil

### Phase 4 — permission tiers mutations

Objectif :

- low impact : appliquer puis confirmer
- high impact : proposer puis attendre validation

Statut :

- [x] policy `mutation_permissions.py`
- [x] `pending_mutation_confirmations` en base
- [x] oui/non sur mutations structurantes
- [x] remplacements cross-sport non triviaux gates
- [x] low impact garde l'auto-apply

### Phase 5 — transcript structure persistant

Objectif :

- enregistrer le tour de conversation comme unite d'audit
- preparer la consolidation memoire sans confondre transcript et memoire

Statut :

- [x] table `conversation_turns`
- [x] persistance `user_message / assistant_message / response_mode / decision / memory_writes`
- [x] lien vers confirmation pending quand present
- [x] transcript distinct de la memoire durable

### Phase 6 — split `repository.py` progressif

Objectif :

- extraire par bounded context sans big bang

Statut :

- [x] premier bounded context sorti dans `repo_conversation.py`
- [x] `repository.py` garde une facade compatible
- [ ] split memory / plan / activities a poursuivre plus tard

### Phase 7 — refactor heartbeat

Objectif :

- separer evaluation / generation / delivery

Statut :

- [x] moteur d'evaluation proactif extrait dans `heartbeat_evaluation.py`
- [x] `heartbeat.py` appelle maintenant une evaluation partagee
- [x] delivery deja restee hors module via `CoachDraft`
- [ ] generation des prompts heartbeat encore a scinder davantage si le module regrossit

### Phase 8 — tools V2

Objectif :

- enrichir le registry avec quelques tools semantiques de lecture

Statut :

- [x] `get_recent_reality_window`
- [x] `get_load_context`
- [x] routing conversation pour les questions de charge
- [x] couverture runtime + routing mise a jour

## Journal

### 2026-04-01

- phase 0 lancee
- support cache Anthropic verifie dans la lib locale
- suite frontend verte
- suite backend critique conversation/tools/memory verte avec bootstrap `.venv`
- phase 1 terminee
- extraction prudente du pipeline sans changer le comportement produit
- verification phase 1 :
  - `./scripts/test-backend -q tests/test_core_flows.py tests/test_conversation_context.py tests/test_execution_context.py tests/test_tool_runtime.py tests/test_user_indications.py tests/test_memory_routing.py tests/test_memory_patterns.py`
  - `./scripts/test-backend -q tests/test_app_endpoints.py tests/test_conversation_prompting.py tests/test_tool_routing.py tests/test_llm_json.py tests/test_llm_tools.py`
- phase 2 terminee
- prompt conversation en 2 zones via `llm_prompt_builder.py`
- cache Anthropic ephemere branche sur la zone system stable
- verification phase 2 :
  - `./scripts/test-backend -q tests/test_llm_prompt_builder.py tests/test_llm_json.py tests/test_llm_tools.py tests/test_conversation_prompting.py tests/test_tool_routing.py`
  - `./scripts/test-backend -q tests/test_core_flows.py tests/test_app_endpoints.py`
- phase 3 terminee
- `profile_summary` deterministe injecte dans le contexte coach
- verification phase 3 :
  - `./scripts/test-backend -q tests/test_profile_summary.py tests/test_llm_prompt_builder.py tests/test_llm_json.py tests/test_llm_tools.py`
  - `./scripts/test-backend -q tests/test_core_flows.py tests/test_conversation_context.py tests/test_memory_routing.py tests/test_memory_patterns.py tests/test_app_endpoints.py`
- phase 4 terminee
- permissions tiers posees sur les mutations structurantes avec confirmation explicite
- verification phase 4 :
  - `./scripts/test-backend -q tests/test_core_flows.py -k "high_impact or message_flow_can_lighten_targeted_session"`
  - `./scripts/test-backend -q tests/test_app_endpoints.py tests/test_conversation_prompting.py tests/test_llm_json.py tests/test_llm_tools.py tests/test_memory_routing.py tests/test_memory_patterns.py`
- phase 5 terminee
- transcript structure persistant pose avec `conversation_turns`
- verification phase 5 :
  - `./scripts/test-backend -q tests/test_core_flows.py -k "conversation_turn_records or high_impact or message_flow_can_lighten_targeted_session"`
  - `./scripts/test-backend -q tests/test_app_endpoints.py tests/test_conversation_context.py tests/test_memory_routing.py tests/test_memory_patterns.py tests/test_llm_json.py tests/test_llm_tools.py tests/test_conversation_prompting.py`
- phase 6 terminee pour le slice conversation
- `repo_conversation.py` extrait sans casser la facade `repository.py`
- verification phase 6 :
  - `./scripts/test-backend -q tests/test_core_flows.py tests/test_app_endpoints.py tests/test_memory_routing.py tests/test_memory_patterns.py`
- phase 7 terminee pour l'evaluation heartbeat
- evaluation proactive partagee sortie dans `heartbeat_evaluation.py`
- verification phase 7 :
  - `./scripts/test-backend -q tests/test_heartbeat_grounding.py`
  - `./scripts/test-backend -q tests/test_core_flows.py -k "conversation_turn_records or high_impact or message_flow_can_lighten_targeted_session"`
- phase 8 terminee
- tools V2 read-only ajoutes pour charge et fenetre de realite recente
- verification phase 8 :
  - `./scripts/test-backend -q tests/test_tool_runtime.py tests/test_tool_routing.py tests/test_llm_tools.py tests/test_conversation_prompting.py`
- verification finale sequentielle :
  - `./scripts/test-backend -q tests/test_core_flows.py tests/test_heartbeat_grounding.py tests/test_app_endpoints.py tests/test_memory_routing.py tests/test_memory_patterns.py tests/test_tool_runtime.py tests/test_tool_routing.py tests/test_llm_tools.py tests/test_conversation_prompting.py tests/test_llm_json.py tests/test_conversation_context.py`
  - `cd frontend && npm test -- --run`
- resultat final :
  - backend: `75 passed`
  - frontend: `10 passed`
