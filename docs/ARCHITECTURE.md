---
summary: architecture technique, stack, modèle de données, flux et décisions tranchées
read_when:
  - choisir la stack
  - implémenter le backend
  - modéliser la base de données
  - ajouter une intégration
  - comprendre les flux techniques
---

# FitMAS Architecture

## Principe directeur

Déterminisme avant LLM. Le LLM propose, formule et adapte le ton.
Les garde-fous, la planification, les permissions, les cooldowns et la persistance sont déterministes.

## Contrat d'architecture produit

- **Telegram = interface coach** : messages, adaptations, relation, proactivité
- **App = interface performance** : calendrier, charge, exécution, progression
- Le domaine entraînement doit rester pur autant que possible
- Les effets de bord vivent dans les orchestrateurs : API, bot, scheduler
- Les futures briques de sophistication doivent s'appuyer sur une vérité planning stable

## État réel du code — 22 mars 2026

**Déployé sur Fly.io : https://the deployed app/**

### Ce qui existe et tourne

- API FastAPI + bot splittés par domaine (34 modules, ~5200 lignes Python)
- Webapp HTML/CSS/JS mobile-first (single-file, ~1800 lignes)
- Bot Telegram avec onboarding conversationnel + commandes + crons
- Planner hebdo multisport déterministe
- Mutation loop : message → LLM → decision → update plan → réponse
- Mémoire utile via UserFact (extraction + upsert + sélection pour prompt)
- Activités manuelles + Strava OAuth + import + synchro automatique
- Heartbeat proactif : briefing matin 7h30, rappel pré-séance 18h, revue dimanche 20h, nouvelle semaine lundi 6h
- Distinction `CoachMessage.proactive` : cooldown appliqué seulement aux messages proactifs
- Heartbeat découplé : génération de draft, livraison, puis persistance après succès
- Cooldowns : 6h entre messages proactifs, skip si échange récent (<2h), max 2 messages/jour
- Verrou scheduler local + guard mémoire pour réduire les doublons en mono-process
- Revue hebdomadaire sans écrasement de la semaine en cours, puis régénération automatique le lundi matin
- Seed intelligent si pas d'utilisateur (profil multisport complet)

- Signaux proactifs : `signals.py` détecte séance manquée, silence, charge haute, grosse séance, streak
- Les signaux enrichissent surtout le briefing matin et le rappel pré-séance
- Données Strava enrichies : avg_hr, max_hr, avg_speed, calories, suffer_score
- Fondation charge : `tss` sur les activités + calculs `CTL/ATL/TSB`
- Calendrier persistant partiel : `ScheduledSession` datées + timeline lecture + lien activité↔séance
- `Today` et les CTA app passent désormais par des APIs datées déterministes
- La boucle coach reçoit aussi la timeline datée et peut cibler une séance précise
- `swap_sessions` sait aussi passer par des ids de séances concrètes
- Router stats performance : `training-load`, `volume`, `records`
- Onglet webapp `Performance` branché sur Chart.js
- `Today` enrichi : contexte de forme + dernière activité comparable même sport
- Début du split frontend : assets JS servis via `/app-static`
- Strava callback redirige vers webapp (plus de JSON brut)
- `/help` Telegram

### Ce qui n'existe pas encore

- Verrou robuste anti-doublon multi-instance
- Dashboard performance avancé dans `Today` + split frontend modulaire
- Périodisation explicite
- Webhook Strava (actuellement polling toutes les 2h)
- Lineage de plans explicite
- Decision log explicite
- Couverture tests encore légère
- Apple Health / wearable data
- WhatsApp

## Stack

| Composant | Choix | Pourquoi |
|-----------|-------|----------|
| Backend API | Python 3.13 + FastAPI | Cohérent, itération rapide, bon fit IA |
| Base de données | SQLite (Fly.io volume persistant) | Suffit pour single-user. Postgres quand multi-users. |
| ORM | SQLAlchemy 2.0 + Pydantic | Types stricts, structured outputs LLM |
| Front | Webapp mobile-first HTML/CSS/JS | Aller vite. Single-file. Pas de framework. |
| Cron | APScheduler (in-process) | Pas de Temporal en V0. Suffisant pour 1 user. |
| Messagerie | Telegram bot (python-telegram-bot 21) | Gratuit, instantané, proactivité validée |
| IA | Anthropic Claude (Haiku quotidien, Sonnet plans) | Structured outputs + bonne qualité français |
| Déploiement | Fly.io CDG + Docker + volume SQLite | Simple, pas cher, Paris |

### Décisions tranchées

**Pas de Temporal.** APScheduler in-process fait le travail pour 1 user.

**Pas d'app native.** Webapp mobile-first permet d'itérer sans App Store review.

**Pas de multi-agent pour l'instant.** Un seul appel LLM bien structuré > pipeline multi-agent tant que le domaine n'est pas stabilisé.

**Telegram avant WhatsApp.** WhatsApp Business API = vérification Meta + templates + coût/msg. Telegram est instantané et gratuit.

**Heuristiques d'entraînement en dur.** Le plan sort d'un moteur déterministe. Le LLM personnalise et formule autour du squelette.

**SQLite, pas Postgres.** Single-user, un seul process, volume Fly.io. Migration Postgres si multi-user.

**Haiku pour le quotidien, Sonnet pour les plans.** Coût ~$0.05-0.15/user/jour. Viable avec pricing $10-15/mois.

## Prochaine évolution structurante

Ordre recommandé :
1. Fiabiliser Telegram et la fréquence des messages
2. Introduire le calcul de charge (`tss`, `CTL/ATL/TSB`)
3. Finir la bascule complète des mutations et vues app vers `scheduled_session_id`
4. Construire le dashboard performance sur cette base
5. Ajouter la périodisation
6. Repousser l'architecture multi-agent après stabilisation

### Pourquoi le calendrier persistant est prioritaire

Le principal défaut structurel actuel n'est pas le manque de graphes ou de LLM.
C'est le fait que le modèle principal reste encore piloté par un `WeeklyPlan` destructif.

Conséquences :
- historique planning fragile
- lecture calendaire approximative
- adaptation semaine suivante peu propre
- base faible pour dashboard et périodisation

Le pivot est maintenant bien avancé avec `ScheduledSession`, et la boucle coach sait cibler ou échanger des séances datées.
Il reste encore quelques chemins legacy `day key`, mais ils sont désormais secondaires et servent surtout de fallback.

## Modules

```
backend/src/fitmas/
├── api.py                 (46 lignes) — bootstrap FastAPI + lifespan
├── api_static.py          (23 lignes) — health + fichiers statiques
├── api_read.py            (~150 lignes) — profile, week, today, timeline, messages, facts, activities
├── api_onboarding.py      (134 lignes) — preview, onboard, regenerate
├── api_plan.py            (~50 lignes) — actions déterministes sur séances datées
├── api_stats.py           (~30 lignes) — endpoints stats performance
├── api_messages.py        (80 lignes) — boucle message -> decision -> facts + timeline datee
├── api_activities.py      (121 lignes) — activités manuelles + Strava OAuth/sync
├── api_debug.py           (97 lignes) — debug protégé, heartbeat manuel, reset
├── api_support.py         (137 lignes) — normalisation onboarding + garde-fous debug
├── api_payloads.py        (38 lignes) — payloads Pydantic
├── telegram_bot.py        (48 lignes) — bootstrap bot
├── telegram_onboarding.py (274 lignes) — ConversationHandler onboarding
├── telegram_commands.py   (151 lignes) — commandes et free text
├── telegram_scheduler.py  (159 lignes) — jobs APScheduler du bot
├── telegram_api.py        (41 lignes) — client backend partagé pour le bot
├── telegram_shared.py     (67 lignes) — constantes + persistance drafts + helpers rendu
├── telegram_channel.py    (44 lignes) — résolution chat_id + envoi Telegram partagé
├── llm.py                 (~630 lignes) — Anthropic client, decisions, extraction, formulation
├── repository.py          (469 lignes) — CRUD + convertisseurs Pydantic
├── planner.py             (359 lignes) — planner multisport déterministe
├── heartbeat.py           (403 lignes) — génération des drafts proactifs
├── signals.py             (312 lignes) — signaux dérivés
├── time_context.py        (122 lignes) — timezone + helpers UTC
├── coach_messages.py      (31 lignes) — draft coach + persistance centralisée
├── strava.py              (210 lignes) — OAuth + import activités + enrichissement TSS
├── activities.py          (93 lignes) — normalisation + matching activités
├── mutations.py           (~170 lignes) — mutations hybrides: session ciblee + fallback semaine
├── plan_actions.py        (~120 lignes) — actions déterministes séance datée
├── schema.py              (239 lignes) — SQLAlchemy ORM
├── models.py              (155 lignes) — modèles Pydantic
├── db.py                  (101 lignes) — engine, sessions, migrations légères
├── training_load.py       (132 lignes) — TSS + CTL/ATL/TSB
├── performance_stats.py   (~110 lignes) — agrégations volume / charge / records
├── seed.py                (235 lignes) — seed si vide
├── state.py               (151 lignes) — état global app
├── nlp.py                 (88 lignes) — fallback rule-based
├── main.py                (3 lignes) — re-export app
└── __init__.py            (2 lignes)

frontend/
├── index.html             (~2200 lignes) — webapp complète, encore majoritairement monolithique
└── js/
    ├── utils.js           (~30 lignes) — helpers purs frontend
    └── charts.js          (~70 lignes) — construction des graphes Chart.js
```

## Modèle de données

### Tables (14)

```
User
  id, name, age, objective, coaching_style, timezone
  telegram_chat_id, onboarding_status
  primary_objective, weekly_structure_notes
  coach_name, coach_style, coach_relationship
  coach_do, coach_dont, coach_soul
  created_at, updated_at

UserSport
  id, user_id (FK), sport_type, priority_rank, level_note, active

UserConstraint
  id, user_id (FK), text

UserPreference
  id, user_id (FK), text

WeeklyPlan
  id, user_id (FK), status (active/superseded)
  intention, summary, created_at

DayPlan
  id, weekly_plan_id (FK), sort_order
  day, label, sport_type, session_type
  session_title, session_goal, session_note
  duration_min, intensity, load_score
  priority, nutrition_focus, flexibility
  completion_status (planned/done/skipped/adapted)

ChangeNote
  id, day_plan_id (FK), title, detail

WatchItem
  id, day_plan_id (FK), title, detail

CoachMessage
  id, user_id (FK), role (user/agent), text, created_at
  proactive (bool)

UserFact
  id, user_id (FK), category, key, value
  source, confidence, confirmed, active
  created_at, updated_at

Activity
  id, user_id (FK), source (manual/strava)
  external_id, sport_type, title
  duration_min, distance_m, elevation_m
  perceived_load, note, started_at
  avg_hr, max_hr, avg_speed, calories, suffer_score, tss
  matched_day, match_reason, scheduled_session_id, created_at

ScheduledSession
  id, user_id (FK), day, label, scheduled_date
  source_plan_created_at
  sport_type, session_type, session_title
  session_goal, session_note, session_description
  duration_min, intensity, load_score
  priority, nutrition_focus, flexibility, completion_status
  created_at, updated_at

StravaConnection
  id, user_id (FK), athlete_id
  access_token, refresh_token
  expires_at, scopes, last_sync_at
```

### Principes de données

- SQL est la source de vérité. Le LLM n'est jamais source de vérité.
- Les preferences explicites user priment sur les inférences.
- Les facts distinguent : déclaré / observé / inféré / confirmé.
- Le modèle reste petit tant que le produit n'est pas stabilisé.

## Flux techniques

### Flux onboarding (Telegram → API)
1. User fait `/start` sur Telegram
2. `telegram_onboarding.py` guide à travers les étapes
3. Le bot appelle `POST /api/v0/onboard` avec le payload complet
4. Backend normalise sports, contraintes, préférences, âme du coach
5. `planner.py` génère un squelette hebdo multisport déterministe
6. `llm.py` formule le récap et l'habillage du plan (Sonnet)
7. Backend persiste User + UserSport + UserFact + WeeklyPlan + DayPlan
8. Webapp affiche récap → semaine → today

### Flux message entrant
1. User envoie un message (Telegram ou webapp)
2. Backend persiste CoachMessage(role=user)
3. Prompt assemblé : âme du coach + plan courant + derniers messages + facts + contexte temporel exact
4. LLM (Haiku) propose une MutationDecision ou no-op
5. `mutations.py` applique le changement si besoin
6. Backend persiste CoachMessage(role=agent)
7. LLM extrait des facts stables à mémoriser

### Contexte temporel partagé

Module: `time_context.py`

Il centralise:
- timezone user
- date/heure locale
- jour local
- interprétation de `aujourd'hui`, `demain`, `hier`, `ce soir`
- helpers UTC partagés pour les cooldowns et fenêtres temporelles

Ce module doit être utilisé par:
- prompts LLM
- heartbeat
- commandes Telegram qui dépendent du jour courant
- signaux et calculs de récence

### Flux activité
1. Import Strava (toutes les 2h) ou log manuel (webapp/Telegram)
2. Normalisation sport + titre
3. `activities.py` matche vers un jour du plan (heuristique : sport +4, jour +3, durée +1-2)
4. Filtre : seules les activités des 7 derniers jours matchent le plan courant
5. Persist Activity + marque le jour comme "done" si match cette semaine

Limite actuelle :
- le matching travaille encore sur un plan hebdomadaire, pas sur un vrai calendrier persistant

### Flux heartbeat
1. APScheduler déclenche le trigger (matin 7h30, soir 18h, dimanche 20h)
2. Garde-fous déterministes : cooldown 4h sur dernier message `proactive=true`, échange récent <2h
3. Si OK → le coeur heartbeat génère un **draft** avec contexte (plan, veille, coach soul)
4. L'orchestrateur (bot ou endpoint debug) envoie via Telegram
5. Persist `CoachMessage(role=agent)` seulement après succès de livraison

### Flux signaux proactifs
1. `signals.py` collecte les signaux : missed_key_session, silence_3_days, high_cumulative_load, big_session_done, streak
2. Chaque signal a un `severity` : info, warning, action
3. Le morning briefing injecte les signaux dans le prompt LLM pour un message contextualisé
4. Le signal check (cron 14h + post-Strava sync) génère un message proactif si signal actionable
5. Garde-fous identiques au heartbeat : cooldown 4h, skip si échange récent

Cap recommandé :
- supprimer le cron 14h autonome
- garder les signaux dans briefing + rappel seulement
- viser 0 à 2 messages proactifs utiles par jour

### Debug heartbeat

- Endpoint: `POST /api/v0/debug/heartbeat/{kind}`
- `kind` supportés: `morning`, `pre_session`, `signal_check`
- Endpoint: `GET /api/v0/signals` — voir les signaux actifs
- Endpoint: `POST /api/v0/reset` — reset admin local/debug
- Usage: test prod réel sans SSH lourd
- Option `send=true|false` pour envoyer ou non sur Telegram
- Par défaut: désactivé sur Fly / prod, activable explicitement via `FITMAS_ENABLE_DEBUG_ENDPOINTS`

### Flux revue hebdomadaire (dimanche 20h)
1. `telegram_scheduler.weekly_review_cron()` déclenche
2. `heartbeat.weekly_review()` génère un draft bilan
3. Le draft est livré sur Telegram puis persisté
4. Le scheduler appelle `POST /api/v0/week/regenerate`
5. Le nouveau plan est livré puis persisté comme message proactif

## Stratégie mémoire

3 couches :

1. **État produit (SQL)** — user, sports, contraintes, plans, messages, facts, activités
2. **Âme système (coach soul)** — définie à l'onboarding, injectée dans chaque prompt
3. **Contexte LLM assemblé** — plan courant + derniers messages + facts sélectionnés

Pas en V0 : vector DB, RAG, mémoire épisodique, pgvector.

## Coût LLM estimé

Par user par jour (~3-4 appels LLM) :
- Heartbeat briefing : ~500 tokens in + 200 out (Haiku)
- Message mutation : ~800 tokens in + 300 out (Haiku)
- Fact extraction : ~400 tokens in + 100 out (Haiku)
- Plan generation : ~1200 tokens in + 800 out (Sonnet, hebdomadaire)

Estimation : ~$0.05-0.15/user/jour avec Haiku.
~$1.5-4.5/user/mois. Marge viable avec pricing $10-15/mois.
