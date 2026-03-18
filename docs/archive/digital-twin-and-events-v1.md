---
summary: modele de donnees v1 du double numerique, evenements entrants et sorties decidees par l'orchestrateur
read_when:
  - modeliser la base de donnees
  - definir les objets metier
  - definir les webhooks et events
  - implementer l'orchestrateur
---

# Digital Twin And Events V1

## Principe

Le coeur du produit n'est pas seulement un plan.
Le coeur du produit est un `double numerique` vivant.

Pour qu'il reste fiable, il faut distinguer:

- ce qui est declare
- ce qui est observe
- ce qui est infere
- ce qui a ete decide

## Entites coeur V1

## 1. User

Identite produit minimale:

- id
- email / auth id
- timezone
- locale
- onboarding_status
- communication_preferences
- created_at
- updated_at

## 2. IntegrationAccount

Une ligne par integration connectee:

- user_id
- provider
- external_account_id
- scopes
- status
- last_sync_at
- error_state

Providers V1:

- apple_health
- strava
- whatsapp
- calendar

## 3. DigitalTwinProfile

Etat structure stable du double numerique.

Champs V1:

- user_id
- primary_goal
- secondary_goals
- target_event
- planning_constraints
- sport_preferences
- nutrition_preferences
- tastes
- non_negotiables
- motivation_style
- messaging_tone
- charge_tolerance
- current_level
- confidence_score
- version
- updated_at

## 4. DigitalTwinFacts

Faits verifies ou quasi verifies.

Exemples:

- fait souvent sa seance longue le dimanche
- dort mal apres les seances tardives
- prefere courir tot le matin
- refuse plus de 2 doubles seances par semaine

Chaque fait doit porter:

- source
- confidence
- first_seen_at
- last_confirmed_at

## 5. DigitalTwinHypotheses

Hypotheses encore fragiles.

Exemples:

- adhere mieux quand le message est direct
- suit mieux le plan si le lundi est leger

Chaque hypothese doit porter:

- evidence_count
- confidence
- status
- invalidated_reason

## 6. RawEvent

Journal brut des signaux entrants.

Champs:

- id
- user_id
- provider
- event_type
- occurred_at
- received_at
- payload
- dedupe_key

## 7. DerivedSignal

Signal interpretable par le moteur produit.

Exemples:

- workout_completed
- workout_missed
- sleep_low
- fatigue_high
- calendar_conflict_detected
- adherence_drop_risk
- nutrition_gap_detected

## 8. Plan

Representation du plan courant.

Sous-types:

- weekly_training_plan
- daily_training_plan
- weekly_nutrition_plan
- daily_nutrition_plan

Champs:

- user_id
- plan_type
- status
- effective_from
- effective_to
- content
- rationale
- parent_plan_id

## 9. Decision

Decision finale prise par le systeme.

Exemples:

- move_session
- reduce_volume
- hold_calories
- add_recovery_prompt
- ask_for_feedback

Champs:

- user_id
- decision_type
- reason_summary
- confidence
- requires_confirmation
- executed_at

## 10. CoachMessage

Messages entrants et sortants lies a l'experience.

Champs:

- user_id
- channel
- direction
- message_type
- content
- template_name si besoin
- sent_at
- delivered_at
- read_at

## Evenements entrants V1

## Onboarding

- onboarding_started
- onboarding_completed
- goal_updated
- preferences_updated
- non_negotiables_updated

## Apple Health

- healthkit_workout_seen
- healthkit_sleep_seen
- healthkit_resting_hr_seen
- healthkit_hrv_seen
- healthkit_steps_seen

Tous ces evenements doivent etre traites comme des signaux partiels:
absence de data ne veut pas dire absence de comportement.

## Strava

- strava_activity_created
- strava_activity_updated
- strava_activity_deleted
- strava_deauthorized

## Calendar

- calendar_event_added
- calendar_event_updated
- calendar_conflict_detected

## WhatsApp

- whatsapp_user_message_received
- whatsapp_delivery_status_updated
- whatsapp_template_reply_received

## Evenements internes

- nightly_planning_tick
- midday_heartbeat_tick
- weekly_review_tick
- cooldown_expired
- manual_replan_requested

## Derived signals recommandes

Plutot que de faire raisonner le LLM sur du raw data partout,
produire des signaux intermediaires.

Exemples:

- workout_load_above_baseline
- workout_load_below_target
- sleep_degraded_2d
- no_training_data_today
- missed_key_session
- user_engagement_low
- plan_conflict_for_tomorrow
- likely_needs_checkin

## Mise a jour du double numerique

Le double doit evoluer par couches:

1. facts declared
2. facts observed
3. hypotheses inferred
4. confirmations / infirmations user

Regle critique:

ne jamais ecraser une preference explicite utilisateur avec une simple inference.

## Sorties de l'orchestrateur

Le systeme doit produire 4 types de sorties:

1. plan updates
2. digital twin updates
3. user-facing messages
4. no-op explicite

Le no-op est important:
parfois la bonne decision est de ne rien changer et de ne rien dire.

## Regles de verite

Source de verite:

- base Postgres

Le LLM n'est pas source de verite.
Il ne fait que proposer, expliquer ou classer.

## Schema logique d'un cycle

1. un raw event arrive
2. il est dedupe
3. il est transforme en derived signals
4. le double numerique est relu
5. les agents sont appeles si besoin
6. l'orchestrateur decide
7. les decisions et plans sont persists
8. un message est eventuellement envoye
