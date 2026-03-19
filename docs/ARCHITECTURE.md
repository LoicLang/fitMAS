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

## État réel du code — Mars 2026

**Déployé sur Fly.io : https://the deployed app/**

### Ce qui existe et tourne

- API FastAPI (17 modules, ~4100 lignes Python)
- Webapp HTML/CSS/JS mobile-first (single-file, ~530 lignes)
- Bot Telegram avec onboarding conversationnel + commandes + crons
- Planner hebdo multisport déterministe
- Mutation loop : message → LLM → decision → update plan → réponse
- Mémoire utile via UserFact (extraction + upsert + sélection pour prompt)
- Activités manuelles + Strava OAuth + import + synchro automatique
- Heartbeat proactif : briefing matin 7h30, rappel pré-séance 18h, revue dimanche 20h
- Cooldowns : 4h entre messages proactifs, skip si échange récent (<2h)
- Revue hebdomadaire avec régénération automatique du plan
- Seed intelligent si pas d'utilisateur (profil multisport complet)

### Ce qui n'existe pas encore

- Webhook Strava (actuellement polling toutes les 2h)
- Module `signals.py` pour signaux dérivés
- Lineage de plans (historique des plans passés)
- Decision log explicite
- Tests automatisés
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

**Pas de multi-agent.** Un seul appel LLM bien structuré > pipeline multi-agent.

**Telegram avant WhatsApp.** WhatsApp Business API = vérification Meta + templates + coût/msg. Telegram est instantané et gratuit.

**Heuristiques d'entraînement en dur.** Le plan sort d'un moteur déterministe. Le LLM personnalise et formule autour du squelette.

**SQLite, pas Postgres.** Single-user, un seul process, volume Fly.io. Migration Postgres si multi-user.

**Haiku pour le quotidien, Sonnet pour les plans.** Coût ~$0.05-0.15/user/jour. Viable avec pricing $10-15/mois.

## Modules

```
backend/src/fitmas/
├── api.py            (611 lignes) — FastAPI, endpoints, lifespan
├── llm.py            (542 lignes) — Anthropic client, decisions, extraction, formulation
├── telegram_bot.py   (529 lignes) — Bot, onboarding, commandes, crons
├── repository.py     (437 lignes) — CRUD + convertisseurs Pydantic
├── planner.py        (359 lignes) — Planner multisport déterministe
├── heartbeat.py      (326 lignes) — Messages proactifs, cooldowns
├── seed.py           (235 lignes) — Seed profil multisport si vide
├── schema.py         (229 lignes) — SQLAlchemy ORM (13 tables)
├── strava.py         (169 lignes) — OAuth + import activités
├── state.py          (151 lignes) — État global app
├── models.py         (145 lignes) — Pydantic API models
├── mutations.py      (113 lignes) — Mutations plan (move, lighten, swap, update)
├── db.py              (87 lignes) — Engine SQLite, SessionLocal, init_db
├── nlp.py             (81 lignes) — Fallback NLP rule-based (sans API key)
├── activities.py      (78 lignes) — Normalisation + matching activités
├── main.py             (3 lignes) — Re-export app
└── __init__.py         (2 lignes)

frontend/
└── index.html        (~530 lignes) — Webapp complète
```

## Modèle de données

### Tables (13)

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

UserFact
  id, user_id (FK), category, key, value
  source, confidence, confirmed, active
  created_at, updated_at

Activity
  id, user_id (FK), source (manual/strava)
  external_id, sport_type, title
  duration_min, distance_m, elevation_m
  perceived_load, note, started_at
  matched_day, match_reason, created_at

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
2. ConversationHandler guide à travers les étapes
3. Bot appelle `POST /api/v0/onboard` avec le payload complet
4. Backend normalise sports, contraintes, préférences, âme du coach
5. `planner.py` génère un squelette hebdo multisport déterministe
6. `llm.py` formule le récap et l'habillage du plan (Sonnet)
7. Backend persiste User + UserSport + UserFact + WeeklyPlan + DayPlan
8. Webapp affiche récap → semaine → today

### Flux message entrant
1. User envoie un message (Telegram ou webapp)
2. Backend persiste CoachMessage(role=user)
3. Prompt assemblé : âme du coach + plan courant + derniers messages + facts
4. LLM (Haiku) propose une MutationDecision ou no-op
5. `mutations.py` applique le changement si besoin
6. Backend persiste CoachMessage(role=agent)
7. LLM extrait des facts stables à mémoriser

### Flux activité
1. Import Strava (toutes les 2h) ou log manuel (webapp/Telegram)
2. Normalisation sport + titre
3. `activities.py` matche vers un jour du plan (heuristique : sport +4, jour +3, durée +1-2)
4. Persist Activity + marque le jour comme "done" si match

### Flux heartbeat
1. APScheduler déclenche le trigger (matin 7h30, soir 18h, dimanche 20h)
2. Garde-fous déterministes : cooldown 4h, échange récent <2h
3. Si OK → LLM génère le message avec contexte (plan, veille, coach soul)
4. Envoi via Telegram
5. Persist CoachMessage(role=agent)

### Flux revue hebdomadaire (dimanche 20h)
1. Heartbeat weekly_review() : bilan de la semaine (fait/prévu/sauté)
2. LLM génère le récap avec la voix du coach
3. `_regenerate_next_week()` : planner + LLM → nouveau plan
4. Persist nouveau WeeklyPlan + message

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
