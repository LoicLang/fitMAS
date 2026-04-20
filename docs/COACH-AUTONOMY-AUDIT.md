---
summary: inventaire des system prompts et des court-circuits du pipeline coach (chantier 0 du refactor autonomy)
read_when:
  - lancer un chantier du refactor coach autonomy
  - identifier ou supprimer un court-circuit déterministe
  - réécrire un system prompt heartbeat ou conversation
  - comprendre quelles f-strings court-circuitent le LLM principal
---

# FitMAS — Coach Autonomy Audit (Chantier 0)

État au 20 avril 2026. Inventaires produits avant de démarrer le refactor `COACH-AUTONOMY-REFACTOR.md`.

## 1. System prompts en jeu

### Pipeline conversation

| Fichier:lignes | LLM call | Posture | Données injectées |
|----------------|----------|---------|-------------------|
| `backend/src/fitmas/llm_prompt_builder.py:10-96` | `decide()` (coach principal) | "JSON valide uniquement", règles `move_session` / `swap_sessions` / `lighten_day` / `replace_session` | timeline_summary, execution_summary, activity_claim_summary, signal_summary, conversation_history, coach_context (déjà digérés) |
| `backend/src/fitmas/conversation_turn_planner.py:127-149` | `turn_planner` | "Aucun write DB. Aucun side-effect. Aucune réponse finale utilisateur" → JSON `primary_intent / secondary_intents / confidence` | temporal_summary, execution_summary, activity_claim_summary, signal_summary (pas de plan futur) |
| `backend/src/fitmas/user_indication_llm.py:17-22 + 91-132` | `indication_parser` | "Tu n'inventes rien. Tu classes seulement le message en signal exploitable" | clarification_date, clarification_sport_type, recent_agent_text, time_context |

### Pipeline heartbeat

| Fichier:lignes | LLM call | Posture | Données injectées |
|----------------|----------|---------|-------------------|
| `backend/src/fitmas/skills/heartbeat/roles.py:214-301` | `morning_briefing` | "Reconnais ce qui a été fait, y compris les sorties hors plan, avant tout autre point", max 4 phrases | plan, signals, facts, yesterday_status, calibration, **digest (lens) + recent_reality + sport_knowledge** ✅ |
| `backend/src/fitmas/skills/heartbeat/roles.py:313-342` | `pre_session_reminder` | "Rappelle la séance de demain et demande comment l'utilisateur se sent", max 2 phrases | plan, signals, facts, calibration (pas de réalité récente) |
| `backend/src/fitmas/skills/heartbeat/roles.py:359-385` | `weekly_review` | "Fais un bilan de la semaine et donne une perspective pour la suivante", max 5 phrases | plan, activities, completion_stats, facts, **week_text + actual/claimed counters AGRÉGÉS** ❌ |
| `backend/src/fitmas/skills/heartbeat/roles.py:394-416` | `signal_check` | "Si grosse séance: félicite + recup. Si manquée: check sans culpabiliser. Si silence: nouvelles. Si charge élevée: suggère d'alléger", max 3 phrases | signals, facts, adaptation |

### Pipeline calibration / adaptation

| Fichier:lignes | LLM call | Posture | Données injectées |
|----------------|----------|---------|-------------------|
| `backend/src/fitmas/calibration_llm.py:25-75` | `calibration:resolve` | "Si c'est ambigu, baisse la confiance ou demande un follow-up" | coach_context, time_context |
| `backend/src/fitmas/calibration_llm.py:78-107` | `calibration:ack` | "1-2 phrases max, jamais parler de calibration / schéma / mémoire" | coach_context, why_now |
| `backend/src/fitmas/coach_reading_digest.py:274-296 + 299-347` | `digest:lens` (pré-pass interne) | "ne dis jamais 'zéro réalisées' quand il y a des offplan" — produit JSON 3 champs (sens_du_jour, angle, ne_pas_faire), pas un message | real_entries (7d), plan counts, silence_days, exchanges, patterns, day_context |
| `backend/src/fitmas/adaptation.py:414-460` | `adaptation:health` | "Tes décisions doivent être conservatrices: mieux vaut adapter que casser" | health_facts, sessions (7d), per-session action |

### Postures à réécrire (Chantier 3)

- `decide()` prompt builder : pas de directive "DÉCIDE et défends ton choix" — actuellement le contrat oriente vers `mutation_type` mais ne pose pas la posture "tu es le coach, tu tranches"
- `turn_planner` : le rôle est sain (classifier-only, pas de réponse user) — ne pas toucher
- `weekly_review` : la posture est correcte mais les données sont agrégées (compteurs au lieu de détail) → cible Chantier 2bis
- `pre_session_reminder` : pas de réalité récente injectée → ce trigger ne pourra pas reconnaître un offplan
- `signal_check` : "suggère d'alléger" est passif, à durcir vers "décide d'alléger et présente comme ta décision"

## 2. Court-circuits du pipeline conversation

Total trouvé : **9**, dont **4 transactionnels** (à garder) et **5 non-transactionnels** (à réécrire en contexte de prompt).

### Transactionnels (à garder)

| # | Fonction | Fichier:ligne | Trigger | Wired | Type |
|---|----------|---------------|---------|-------|------|
| T1 | `build_confirmation_followup()` | `mutation_permissions.py:129` | Pending mutation + ack/greeting + pas de oui/non binaire | `conversation_pipeline.py:88` | Relance confirmation |
| T2 | `build_rejection_reply()` | `mutation_permissions.py:133` | Pending mutation + "non" explicite | `conversation_pipeline.py:102` | Rejet binaire |
| T3 | `build_confirmation_prompt()` | `mutation_permissions.py:118` | Mutation appliquée ou bloquée | `conversation_pipeline.py:134, 764` | Ack post-apply |
| T4 | `generate_calibration_ack()` | `calibration_llm.py:78` | Réponse calibration standalone | `conversation_pipeline.py:202` | Ack calibration (LLM 1-2 phrases) |

Justification "garder" : ce sont des transactions binaires (oui/non) ou des acks immédiats post-mutation. Pas d'arbitrage à faire.

### Non-transactionnels (réécrits — Chantier 1 fait au 20 avril 2026)

Tous routés vers `decide()` comme contexte de prompt. Statut individuel :

| # | Fonction | Statut Chantier 1 | Forme actuelle |
|---|----------|-------------------|----------------|
| N1 | `extract_reply()` + `generate_reply()` (nlp.py) | **supprimé** | Module `nlp.py` deleted ; le fallback restant n'est qu'une réponse "LLM indisponible, reessaie" qui ne ment pas |
| N2 | `_maybe_low_signal_reply()` | **réécrit** | Renommé `_maybe_low_signal_label()` → retourne "ack" / "greeting" / "motivation" ; injecté via `_low_signal_context_for_prompt()` dans le prompt decide() |
| N3 | `_week_scope_reply()` | **routé** | Toujours produit côté resolver, mais injecté en contexte via `_availability_context_for_prompt()` ; elif branch supprimée |
| N4 | `_no_candidate_constraint_reply()` | **routé** | Idem N3 : grounding deterministe → contexte de prompt |
| N5 | `_execution_contestation_reply()` | **réécrit** | Le downgrade non-completion s'applique en amont ; le wording final passe par decide() via `_execution_contestation_context_for_prompt()` |

### Cas hybride : `_build_user_message` (replan_from_life_change.py)

Pas un court-circuit du pipeline mais un **template d'action affirmée** utilisé par `maybe_replan_from_life_change` et `maybe_replan_from_user_indication`.

- `replan_from_life_change.py:474-507 _build_user_message()` produit "OK. Je libere ce creneau et je garde la suite propre."
- Si la mutation downstream n'est PAS appliquée (mutation_type=no_change, ou session_id mauvaise, ou bloquée par validator), le user reçoit une affirmation d'action fantôme
- **Couvert Chantier 1bis "Anti-mensonge dire = faire" (fait 2026-04-20)** : la phrase est désormais filtrée à la sortie pipeline. Le module `backend/src/fitmas/claim_guard.py` détecte les marqueurs d'action affirmée 1ère personne (`Je libere`, `Je deplace`, `Je remplace`, `Je supprime`, `Je decale`, `Je bascule`, `Je echange`, `Je retire`, `Je annule`, `J'ajoute`, `Je swappe`) sans négation ni marqueur de proposition. Si déclenché ET aucune mutation committee ce tour (`outcome.mutation_applied=False` ET `outcome.pending_confirmation=False`), la réponse est réécrite en demande de clarification explicite et un warning `conversation_pipeline.claim_without_mutation` est loggé. Wired dans `conversation_pipeline.py` juste avant `_reply_and_record_turn`

### Routing guards (Chantier 1 fait)

Les deux gardes ont été **généralisées** au 20 avril 2026 :

- `_should_route_availability_context_to_llm()` → True dès qu'un grounding (week_scope ou no_candidate) existe ; le turn_plan n'est plus une condition
- `_should_route_adaptation_context_to_llm()` → True dès qu'une adaptation candidate existe ; idem

Effet : `decide()` est appelé sur **100% des tours conversationnels** sauf le seul court-circuit transactionnel restant `calibration_only_reply`. Quand le LLM est indisponible (Anthropic client absent / rate limited) et qu'il n'y a pas d'adaptation à appliquer, on répond sobrement "Je ne peux pas te repondre tout de suite. Reessaie dans un instant." plutôt que de regurgiter une phrase rule-based qui pourrait mentir sur l'état du plan.

## 3. Cibles de réécriture par chantier

| Chantier | Cible code | Cible inventaire |
|----------|-----------|------------------|
| 1 | ✅ fait 2026-04-20 — voir commits `chantier 1: ...` | N1, N2, N3, N4, N5 |
| 1bis | ✅ fait 2026-04-20 — `claim_guard.py` + garde sortie pipeline `conversation_pipeline.py` | template hybride couvert au runtime |
| 2 | nouveaux tools `get_plan_window`, `get_activities_detailed`, `get_user_constraints`, `get_load_context` | (ajout, pas remplacement) |
| 2bis | `skills/heartbeat/roles.py:359-385 weekly_review` + `coach_reading_digest` branchement | weekly_review prompt |
| 3 | `llm_prompt_builder.py:10-96` (decide), `skills/heartbeat/roles.py:394-416` (signal_check) | postures "DÉCIDE" |
| 4 | `working_memory_entries` + nouveau champ `valid_until` | (data, pas prompt) |
| 5 | nouveau `validator.py` + skill `propose_replan` | (nouveau code) |
