---
summary: source de verite courte sur l'etat actuel et le prochain chantier
read_when:
  - commencer un chantier
  - verifier la suite immediate
  - recadrer le refactor avant de coder
---

# Build Order

## Phrase Guide

Je ne veux pas un refactor plus complet.
Je veux un runtime plus petit.

## Etat Actuel — 21 mai 2026

FitMAS est en refactor Decision Runtime.

Le cap produit reste :

- Telegram = coach conversationnel et proactif.
- App = cockpit de lecture.
- `ScheduledSession + Activity + Events` = verite runtime.
- Le LLM comprend le langage utilisateur.
- Le backend arbitre, valide, commit et audite.
- Les replies visibles doivent venir d'un outcome/verdict, pas d'un helper qui improvise.

## Ce Qui Est Vraiment En Place

Le repo contient maintenant :

- `decision/` : types centraux, `DecisionOutcome`, `DecisionReplyComposer`, `OutputVerifier`, `CommandBus`.
- `domain/planning/` : reference resolver, candidates, evaluator, policy, mutation service canonique.
- `llm/` : gateway, prompts, compat legacy LLM isolee, reply backend LLM.
- `skills/heartbeat/` : heartbeat runtime, reply composer, tool loop et generation proactive.
- `app/api/` et `app/telegram/` : deplacement progressif des entrypoints.
- `legacy/` : bridges de migration encore actifs, a supprimer progressivement.

Les cuts physiques recents :

- root wrappers supprimes : `api_messages.py`, `telegram_scheduler.py`, `llm_gateway.py`, `tool_*`, `plan_patch_tools.py`, `state.py`.
- root `final_reply.py` supprime.
- `legacy/conversation_reply_adapter.py` supprime.
- `legacy/final_reply_backend.py` supprime.
- `legacy/heartbeat_runtime_adapter.py` supprime.
- `legacy/heartbeat_skill_bridge.py` supprime.
- `legacy/conversation_command_bridge.py` supprime.
- `legacy/conversation_command_bus.py` supprime.
- `legacy/conversation_canonical_readonly_bridge.py` supprime.
- `legacy/conversation_readonly_reply_bridge.py` supprime.
- `legacy/conversation_understanding_bridge.py` supprime.
- `legacy/conversation_decide_bridge.py` supprime.
- `legacy/coach_decision_provider.py` supprime : plus de provider
  `CoachDecision` callable depuis la conversation.
- `legacy/coach_command_adapter.py` reduit a un re-export compat.
- `docs/superpowers/plans/` supprime : l'historique d'execution reste dans git, pas dans la memoire active.

Etat chiffre au dernier check local :

- root modules : `113`.
- legacy modules : en baisse continue, avec bridges conversationnels mesures par
  census dedie.
- backend complet : `1423 passed, 11 skipped`.
- smoke core API : OK.
- fallback census core : `0`.

## Prochain Chantier

10K CoachDecision provider delete est maintenant applique.

Commande :

```bash
./scripts/decision-runtime-conversation-bridge-census \
  --json-out /tmp/fitmas-10j-conversation-bridge-census.json
```

Etat conversation bridge courant :

```text
runtime_active_count=0
legacy_internal_count=0
test_only_count=0
deleted_count=10
```

Tous les bridges conversationnels mesures ont ete supprimes physiquement :

```text
legacy/conversation_activity_highlight_bridge.py
legacy/conversation_canonical_clarification_bridge.py
legacy/conversation_canonical_readonly_bridge.py
legacy/conversation_coach_decision_reply_bridge.py
legacy/conversation_command_bridge.py
legacy/conversation_command_bus.py
legacy/conversation_decide_bridge.py
legacy/conversation_decision_bridge.py
legacy/conversation_readonly_reply_bridge.py
legacy/conversation_understanding_bridge.py
```

Commands vivent maintenant dans :

```text
decision/command_actions.py
decision/command_mapping.py
decision/command_application.py
```

Readonly/reply vit maintenant dans :

```text
decision/readonly_reply.py
```

Understanding runtime vit maintenant dans :

```text
decision/understanding_runtime.py
```

Trace de provider CoachDecision supprime vit maintenant dans :

```text
decision/coach_decision_runtime.py
```

Mais il ne lance plus aucun provider legacy :

```text
legacy_provider_skip_reason -> canonical_provider_clarification_outcome
```

Prochain chantier logique :

- il n'y a plus de bridge `legacy/conversation_*` runtime-active ;
- attaquer maintenant le reste de la dette `CoachDecision` :
  `legacy/decision_contracts.py`, `legacy/coach_decision_artifact.py`,
  `legacy/coach_understanding_adapter.py`, `legacy/understanding_shadow.py`
  et `llm/decision_legacy.py` ;
- shrinker `conversation_pipeline.py` autour de moins d'entrypoints ;
- garder la priorite runtime plus petit, pas refactor plus complet.

## Ordre De Lecture Pour Un Agent

1. `PROJECT.md`
2. `docs/README.md`
3. `docs/BUILD-ORDER.md`
4. `docs/DECISION-RUNTIME-REFACTOR.md`
5. `docs/DECISION-RUNTIME-LEGACY-KILL-LIST.md`
6. `docs/SYSTEM-MAP.md`
7. doc domaine pertinent

## Regles De Travail

- Ne pas ouvrir Phase B progression/prescription sans demande explicite.
- Ne pas ajouter de fallback local.
- Ne pas ajouter de prompt long pour compenser une frontiere floue.
- Ne pas parser le texte utilisateur libre par regex/keywords.
- Ne pas faire de write hors command/writer service.
- Ne pas faire parler un helper hors composer/reply layer.
- Tout nouveau module doit avoir un owner clair dans l'organisation cible.

## Verification Minimale

Pour un changement backend :

```bash
./scripts/test-backend
```

Pour un changement runtime conversation/planning :

```bash
./scripts/smoke-a-plus-api --skip-generated-week \
  --scenario lookup_current_plan \
  --scenario create_easy_free_day \
  --fallback-census-json /tmp/fitmas-core-census.json \
  --timeout 420

./scripts/decision-runtime-fallback-census-summary \
  /tmp/fitmas-core-census.json \
  --json-out /tmp/fitmas-core-summary.json
```
