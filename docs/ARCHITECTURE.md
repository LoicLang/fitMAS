---
summary: architecture technique MVP, stack, modele de donnees, flux et decisions tranchees
read_when:
  - choisir la stack
  - implementer le backend
  - modeliser la base de donnees
  - ajouter une integration
  - comprendre les flux techniques
---

# FitMAS Architecture

## Principe directeur

Determinisme avant LLM. Le LLM propose, formule et adapte le ton.
Les garde-fous, la planification de jobs, les permissions, les cooldowns et la persistance sont deterministes.

## Stack MVP

| Composant | Choix | Pourquoi |
|-----------|-------|----------|
| Backend API | Python + FastAPI | Cohérent, iteration rapide, bon fit IA |
| Base de donnees | SQLite (dev) → PostgreSQL (prod) | SQLite suffit pour valider. Postgres quand multi-users. |
| Front MVP | Webapp mobile-first (React/Next.js ou similaire) | Valider le produit avant d'investir dans iOS natif. Pas besoin de Xcode pour lancer. |
| Workflow/cron | APScheduler ou simple cron | Pas de Temporal en V0. Un cron par user pour heartbeat suffit. |
| Messagerie V0 | Telegram bot | Valider la mecanique proactive avant le process Meta WhatsApp. Migration WhatsApp quand le produit est prouve. |
| Service IA | Appels LLM directs (Anthropic/OpenAI) + Pydantic pour structured outputs | Un seul "agent" bien prompte. Pas de multi-agent, pas de LangGraph. |
| Auth | Simple (email magic link ou Sign in with Apple plus tard) | Pas de friction inutile en beta. |

### Decisions tranchees

**Pas de Temporal en V0.** Temporal est pour des systemes a l'echelle. Un cron + task queue simple (APScheduler) fait le meme travail pour 5-50 users.

**Pas de SwiftUI natif en V0.** Le produit doit etre valide avant d'investir dans iOS natif. Une webapp mobile-first permet d'iterer sans App Store review. HealthKit et Strava se gèrent via webhooks/APIs côté serveur pour le MVP.

**Pas de multi-agent en V0.** Un seul appel LLM bien structure avec un system prompt complet (SOUL + user context + plan courant + signaux recents) produit de meilleurs resultats qu'un pipeline multi-agent avec overhead de routing.

**Telegram avant WhatsApp.** WhatsApp Business API demande: verification Meta, templates approuves, fenetre de 24h, cout par message. Telegram est instantane, gratuit, et la mecanique proactive est identique. On migre quand la valeur est prouvee.

**Heuristiques d'entrainement en dur.** Le plan ne sort pas d'un prompt libre. Un moteur deterministe gere: progression de volume (~10%/semaine), cycles charge/decharge, repartition des types de seances, placement des jours de repos. Le LLM personnalise et formule autour de ce squelette.

## Modele de donnees MVP

### Tables principales

```
User
  id, email, timezone, locale, onboarding_status
  created_at, updated_at

DigitalTwin
  user_id (FK)
  primary_goal, target_event, target_date
  planning_constraints (JSONB)  -- jours dispo, creneaux, jours a eviter
  sport_profile (JSONB)         -- volume recent, niveau, fragilites
  nutrition_preferences (JSONB) -- habitudes, contraintes, gouts
  coaching_style (JSONB)        -- ton, challenge level, relance tolerance
  non_negotiables (JSONB)
  version, updated_at

WeeklyPlan
  id, user_id (FK)
  status (active/superseded)
  week_start_date
  intent                        -- intention de la semaine (TEXT)
  sessions (JSONB)              -- [{day, type, objective, duration, intensity, flexible}]
  nutrition_notes (JSONB)       -- [{day, focus, timing_note}]
  rationale (TEXT)               -- pourquoi ce plan
  parent_plan_id (FK, nullable) -- lineage
  created_at

DailySnapshot
  id, user_id (FK), date
  planned_session (JSONB)
  actual_session (JSONB, nullable)
  nutrition_focus (TEXT)
  adaptations (JSONB)           -- [{change, reason, impact}]
  watching (JSONB)              -- ce que FitMAS surveille
  created_at, updated_at

RawEvent
  id, user_id (FK)
  provider (strava/healthkit/telegram/calendar/system)
  event_type
  occurred_at, received_at
  payload (JSONB)
  dedupe_key

CoachMessage
  id, user_id (FK)
  channel (telegram/app)
  direction (inbound/outbound)
  message_type (adaptation/clarification/feedback/spontaneous)
  content (TEXT)
  trigger_reason (TEXT)
  sent_at, delivered_at

UserFact
  id, user_id (FK)
  fact (TEXT)                   -- "prefere courir tot le matin"
  source (onboarding/observed/inferred/user_confirmed)
  confidence (float)
  created_at, last_confirmed_at

Decision
  id, user_id (FK)
  decision_type (move_session/reduce_volume/send_message/no_op)
  reason_summary (TEXT)
  confidence (float)
  requires_confirmation (bool)
  executed_at
```

### Principes de donnees

- SQL est la source de verite. Le LLM n'est jamais source de verite.
- JSONB pour les objets souples (plan sessions, preferences, payloads).
- TEXT pour les explications et rationales.
- Tout plan doit avoir un `parent_plan_id` pour le lineage.
- Les facts distinguent: declare / observe / infere / confirme par user.
- Les preferences explicites user priment toujours sur les inferences.

## Flux techniques

### Flux onboarding
1. User complete les 6 blocs
2. Backend cree DigitalTwin
3. Moteur de planification genere WeeklyPlan (heuristiques + LLM formulation)
4. App affiche recap → plan → Today

### Flux heartbeat (cron, 1-2x/jour par user)
1. Cron reveille le heartbeat pour chaque user
2. Lecture: nouveaux RawEvents, DigitalTwin, WeeklyPlan courant
3. Derivation de signaux (seance faite? fatigue? conflit agenda?)
4. Decision: no-op / adapter plan / poser question / envoyer message
5. Si action: persister Decision + mettre a jour plan + envoyer message si policy OK
6. Si no-op: persister Decision(type=no_op) pour tracabilite

### Flux message entrant (Telegram webhook)
1. User repond
2. Backend persiste RawEvent
3. Extracteur structure (1 appel LLM): intent, disponibilites, ressenti, confidence
4. Decision: action directe / clarification / no-op
5. Si update: modifier plan + confirmer dans l'app

### Flux Strava (webhook)
1. Strava envoie webhook activity.create
2. Backend accuse reception rapide
3. Fetch async des details de l'activite
4. Persiste RawEvent normalise
5. Reveille le heartbeat si seance notable

### Flux planification hebdo
1. Cron dimanche soir / lundi matin
2. Lecture: DigitalTwin + DailySnapshots de la semaine + facts
3. Moteur deterministe genere le squelette (types de seances, volume, placement)
4. LLM personnalise: intention, formulation, arbitrages visibles
5. Persiste nouveau WeeklyPlan (parent = ancien plan)
6. Genere revue de semaine passee

## Moteur de planification (heuristiques)

Le coeur du produit. Pas du LLM libre.

### Regles de base V0
- Progression volume: ~10% par semaine max
- Cycle: 3 semaines charge → 1 semaine decharge
- Repartition: 80% facile / 20% qualite (regle 80/20 endurance)
- Repos: minimum 1 jour complet ou actif leger
- Sortie longue: 1x/semaine, placement fixe si possible
- Qualite: 1x/semaine, pas le lendemain de la longue
- Respect des contraintes user: jours bloques, creneaux preferes

### Ce que le LLM fait
- Choisir l'intention de la semaine en langage naturel
- Formuler les arbitrages de facon personnalisee
- Adapter le ton selon le coaching style
- Generer les messages proactifs
- Extraire le feedback des reponses utilisateur

## Integrations V0

### Strava
- Webhook pour activity.create
- Fetch detail via API
- Signaux: seance faite, duree, distance, allure, effort percu

### Apple Health (differe)
- Pas en V0 webapp. Viendra avec l'app native.
- En attendant: user peut rapporter manuellement ou via Strava.

### Telegram (V0) → WhatsApp (plus tard)
- Bot Telegram pour messages proactifs et reception feedback
- Interface abstraite: `send_message`, `receive_message`, `check_policy`
- Migration WhatsApp quand: produit valide + process Meta complete

### Calendrier (optionnel V0)
- Si trop de friction, repousser.
- Le user peut signaler les conflits via messagerie.

## Strategie memoire MVP

3 couches suffisent en V0:

1. **Etat produit (SQL)** — DigitalTwin, plans, facts, decisions, events
2. **Ame systeme (Markdown)** — SOUL.md injecte dans chaque prompt
3. **Contexte LLM (assemble dynamiquement)** — objectif + contraintes + plan courant + signaux recents + derniers messages

Pas en V0: vector DB, RAG, memoire episodique, pgvector.
A introduire quand il y a assez de donnees pour que ca serve.

## Cout LLM estime

Par user par jour (~2 appels LLM en moyenne):
- Heartbeat decision: ~500 tokens in + 200 out
- Message generation: ~800 tokens in + 150 out
- Feedback extraction: ~400 tokens in + 100 out

Estimation: ~$0.05-0.15/user/jour avec Claude Haiku ou GPT-4o-mini.
~$1.5-4.5/user/mois. Marge viable avec pricing a $10-15/mois.

Optimisation: utiliser un modele rapide/cheap (Haiku) pour extraction et heartbeat decision.
Modele premium (Sonnet/GPT-4o) seulement pour generation de plan et messages importants.
