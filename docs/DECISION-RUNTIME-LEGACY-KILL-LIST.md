---
summary: kill list courte des surfaces legacy restantes du Decision Runtime
read_when:
  - supprimer du legacy
  - choisir le prochain slice de shrink
  - verifier qu'une route legacy ne revient pas
---

# Decision Runtime Legacy Kill List

## Etat Court

Le dossier `legacy/` contient encore des modules de compat, mais le bloc P0
planning/pending n'y vit plus.

Les wrappers deja supprimes :

- `legacy/conversation_reply_adapter.py`
- `legacy/final_reply_backend.py`
- `legacy/heartbeat_runtime_adapter.py`
- `legacy/heartbeat_skill_bridge.py`
- `legacy/tools_compat.py`
- `legacy/weekly_plan_compat.py`
- `legacy/conversation_activity_highlight_bridge.py`
- `legacy/conversation_canonical_clarification_bridge.py`
- `legacy/conversation_coach_decision_reply_bridge.py`
- `legacy/conversation_command_bridge.py`
- `legacy/conversation_command_bus.py`
- `legacy/conversation_decision_bridge.py`
- `legacy/conversation_canonical_readonly_bridge.py`
- `legacy/conversation_readonly_reply_bridge.py`
- `legacy/conversation_understanding_bridge.py`
- `legacy/conversation_decide_bridge.py`
- `legacy/coach_decision_provider.py`

Le gros residu actif n'est plus planning/pending ni le provider
`CoachDecision`. Le prochain risque est la compat `CoachDecision` restante :
contrats, artifact et provider LLM historique.

## Priorite De Suppression

### P0 — Planning / Pending — clos en 10E

Fichiers supprimes :

- `legacy/conversation_canonical_planning_bridge.py`
- `legacy/conversation_pending_bridge.py`
- `legacy/conversation_planning_bridge.py`
- `legacy/planning_runtime_adapter.py`
- `legacy/planning_outcome_adapter.py`
- `legacy/plan_patch_reply_adapter.py`
- `legacy/pending_reply_adapter.py`

Nouveaux owners :

- `decision/planning_runtime.py`
- `decision/planning_outcomes.py`
- `decision/pending_resolution.py`
- `decision/pending_reply.py`

Census final :

```text
runtime_active_count=0
legacy_internal_count=0
test_only_count=0
deleted_count=7
```

Etat :

- l'actif planning/pending est sorti de `legacy/`;
- les wrappers vides sont supprimes ;
- le reste du travail est dans `conversation_pipeline.py`, pas dans ces fichiers.

### P1 — CoachDecision / Understanding Legacy

Fichiers :

- `legacy/decision_contracts.py`
- `legacy/coach_decision_artifact.py`
- `legacy/coach_understanding_adapter.py`
- `legacy/understanding_shadow.py`
- `llm/decision_legacy.py`

Probleme :

- `CoachDecision` reste l'ancien contrat de compat ;
- l'understanding canonique vit maintenant dans `decision/understanding_runtime.py`,
  mais il produit encore un artifact `CoachDecision` compat pour certaines lanes.
- le provider callable `legacy/coach_decision_provider.py` est supprime ;
  `conversation_pipeline.py` ne construit plus de request legacy et ne peut plus
  appeler `run_legacy_coach_decision`.

Sortie attendue :

- artifact compat transforme en outcome direct ;
- `legacy/decision_contracts.py`, `legacy/coach_decision_artifact.py` et
  `llm/decision_legacy.py` supprimes ou confines hors runtime conversation.

### P2 — Commands / Memory / Execution Bridges — clos en 10G

Fichiers supprimes :

- `legacy/conversation_command_bridge.py`
- `legacy/conversation_command_bus.py`

Nouveaux owners :

- `decision/command_actions.py`
- `decision/command_mapping.py`
- `decision/command_application.py`

Etat :

- `legacy/coach_command_adapter.py` reste seulement un re-export compat ;
- les writes memoire/execution conversationnels passent par
  `decision/command_application.py` ;
- les action contracts ne sont plus definis dans `legacy/decision_contracts.py`.

### P3 — Readonly / Activity / Clarification Bridges — clos en 10H

Fichiers supprimes :

- `legacy/conversation_activity_highlight_bridge.py`
- `legacy/conversation_canonical_clarification_bridge.py`
- `legacy/conversation_canonical_readonly_bridge.py`
- `legacy/conversation_coach_decision_reply_bridge.py`
- `legacy/conversation_decision_bridge.py`
- `legacy/conversation_readonly_reply_bridge.py`

Nouveaux owners :

- `decision/activity_highlight.py`
- `decision/clarification_reply.py`
- `decision/readonly_reply.py`
- `legacy/coach_decision_artifact.py`

Etat :

- read-only, activity highlight et clarification ne vivent plus dans des
  wrappers `legacy/conversation_*`;
- les helpers de reply CoachDecision restants sont absorbes par
  `decision/readonly_reply.py`;
- le dernier risque actif est provider/understanding.

### P4 — Conversation Bridge Census — clos en 10J / 10K

Commande :

```bash
./scripts/decision-runtime-conversation-bridge-census \
  --json-out /tmp/fitmas-10j-conversation-bridge-census.json
```

Resultat courant apres 10J :

```text
runtime_active_count=0
legacy_internal_count=0
test_only_count=0
deleted_count=10
```

Encore runtime-active :

- aucun bridge `legacy/conversation_*` mesure.
- aucun provider `legacy/coach_decision_provider.py`.

## Gates A Garder

- Aucun import de legacy depuis `decision/`.
- Aucun import de deleted wrapper.
- Aucun fallback legacy sur lane couverte par smoke.
- Aucun `PlanPatch` produit par Understanding.
- Aucun `MutationDecision` dans le chemin runtime canonique.
- Aucun texte visible hors reply layer.

## Prochain Slice

Apres 10K : attaquer l'artifact et les contrats `CoachDecision` restants sans
recreer de fallback local.

Commande :

```bash
./scripts/decision-runtime-conversation-bridge-census \
  --json-out /tmp/fitmas-10j-conversation-bridge-census.json
```

Resultat 10J :

- census conversationnel ajoute ;
- activity highlight et clarification vivent dans `decision/`;
- helpers de forme `CoachDecision` vivent dans `legacy/coach_decision_artifact.py`;
- readonly/reply vit dans `decision/readonly_reply.py`;
- understanding runtime vit dans `decision/understanding_runtime.py`;
- le provider CoachDecision callable est supprime ;
- `decision/coach_decision_runtime.py` ne garde que la trace
  `coach_decision_provider_removed` et la clarification canonique ;
- command mapping/application vit dans `decision/`;
- dix bridges conversationnels sont supprimes ;
- aucun bridge `legacy/conversation_*` ne reste actif.
