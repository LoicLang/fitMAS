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

### Non-transactionnels (à réécrire)

Ordonné par sévérité d'impact utilisateur :

| # | Fonction | Fichier:ligne | Trigger | Exemple sortie | Wired | Sévérité |
|---|----------|---------------|---------|----------------|-------|----------|
| N1 | `extract_reply()` + `generate_reply()` | `nlp.py:18, 60` | Catch-all : tous les chemins non handlés | "Je peux ajuster, mais j'ai besoin d'un point de plus..." | `conversation_pipeline.py:843-844` | **CRITIQUE** : universal fallback, ignore le fil de conversation, regurgite des phrases hardcodées |
| N2 | `_maybe_low_signal_reply()` | `api_messages.py:285` | Pas de calibration need + ack/greeting/motivation normalisé | "Bien recu." / "Bien. On garde cette energie..." | `conversation_pipeline.py:154` | **HAUTE** : affirme phantom action ("on garde cette energie, rien à changer") sans arbitrage LLM |
| N3 | `_week_scope_reply()` | `api_messages.py:317` | `availability_constraint` + scope = WEEK + pas de matched_session_id | "OK. Je n'ai rien de sensible planifie sur this_week..." | `conversation_pipeline.py:577` | **HAUTE** : leak de token interne `this_week`, ferme la conversation |
| N4 | `_no_candidate_constraint_reply()` | `api_messages.py:368` | `availability_constraint` + scope SINGLE + pas de candidats | "OK. Je n'ai rien de sensible planifie sur ce créneau. Rien à bouger pour l'instant." | `conversation_pipeline.py:576` | **HAUTE** : ferme un planning complexe avec une réponse déterministe |
| N5 | `_execution_contestation_reply()` | `api_messages.py:500` | Non-completion claim + evidence pas confirmed_done | "Bien noté. Je ne compte pas [session] comme faite..." | `conversation_pipeline.py:605` | **MOYENNE** : rejette une contestation user sans laisser le LLM valider l'intent |

### Cas hybride : `_build_user_message` (replan_from_life_change.py)

Pas un court-circuit du pipeline mais un **template d'action affirmée** utilisé par `maybe_replan_from_life_change` et `maybe_replan_from_user_indication`.

- `replan_from_life_change.py:474-507 _build_user_message()` produit "OK. Je libere ce creneau et je garde la suite propre."
- Si la mutation downstream n'est PAS appliquée (mutation_type=no_change, ou session_id mauvaise, ou bloquée par validator), le user reçoit une affirmation d'action fantôme
- **Cible Chantier 1bis "Anti-mensonge dire = faire"** : la phrase ne doit jamais sortir si aucun `plan_mutation_event` n'a été émis

### Routing guards déjà en place

Deux gardes existent pour rerouter certains court-circuits vers le LLM quand le turn_plan le demande :

- `_should_route_availability_context_to_llm()` (`conversation_pipeline.py:1114`) → suppress `_week_scope_reply` / `_no_candidate_constraint_reply` quand `turn_plan.primary_intent in {plan_mutation, availability_constraint}`
- `_should_route_adaptation_context_to_llm()` (`conversation_pipeline.py:1130`) → idem pour les adaptations

Ces gardes sont la bonne forme : Chantier 1 doit les **généraliser** à tous les short-circuits non-transactionnels (au lieu de la logique actuelle "court-circuit par défaut, route au LLM seulement si turn_plan le force").

## 3. Cibles de réécriture par chantier

| Chantier | Cible code | Cible inventaire |
|----------|-----------|------------------|
| 1 | `conversation_pipeline.py:843-844` (fallback nlp), `:577` (week_scope), `:576` (no_candidate), `:605` (contestation), `:154` (low_signal) | N1, N2, N3, N4, N5 |
| 1bis | `replan_from_life_change.py:474-507` + garde "claim_without_mutation" sortie pipeline | template hybride |
| 2 | nouveaux tools `get_plan_window`, `get_activities_detailed`, `get_user_constraints`, `get_load_context` | (ajout, pas remplacement) |
| 2bis | `skills/heartbeat/roles.py:359-385 weekly_review` + `coach_reading_digest` branchement | weekly_review prompt |
| 3 | `llm_prompt_builder.py:10-96` (decide), `skills/heartbeat/roles.py:394-416` (signal_check) | postures "DÉCIDE" |
| 4 | `working_memory_entries` + nouveau champ `valid_until` | (data, pas prompt) |
| 5 | nouveau `validator.py` + skill `propose_replan` | (nouveau code) |
