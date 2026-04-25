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

## Principes de harness

### Comprendre puis decider

Le LLM ne doit pas comprendre, choisir et agir en un seul bloc.
Le bon flux : message → extraction structuree → scoring de scenarios → choix → explication.
Le LLM aide a comprendre et expliquer. Le moteur protege la coherence.

### Contexte en couches

| Couche | Contenu | Stabilite |
|--------|---------|-----------|
| Stable | identite coach, style, doctrine, regles | Quasi jamais |
| Semi-stable | profil resume, mission semaine, calendrier date | Par session/semaine |
| Immediate | temps local, realite recente, signaux du jour | Chaque tour |
| Memoire | memoire utile selectionnee, highlights transcript | Variable |

Regles : le contexte durable vit hors prompt, le prompt recoit des resumes compacts, pas d'historique brut par reflexe.

### Transcript et memoire sont differents

Le transcript garde ce qui a ete dit, decide, utilise — pour audit et debug.
La memoire garde uniquement ce qui merite d'influencer le futur (`profile / working / patterns`).
On ne promeut pas un message brut en verite durable sans raison.

### Tools atomiques et bornes

Un tool = une lecture metier claire. Pas de shell mental "fais tout avec un seul appel".
Les tools restent read-only. Les orchestrateurs possedent les writes.

### Liberte asymetrique

| Axe | Liberte | Raison |
|-----|---------|--------|
| Parole | Moyenne | Un message imparfait se rattrape |
| Memoire | Faible a moyenne, structuree | Une memoire fausse pollue des semaines |
| Action | Faible, tres bornee | Une action fausse casse la confiance |

### Anti-patterns a eviter

- faire lire tout le profil brut a chaque tour
- heartbeat sur les memes contraintes stables sans nouveaute
- perdre l'intention utilisateur entre extraction et mutation
- laisser un "jour libre" gagner contre une semaine absurde
- confondre fact actif, verite durable et souvenir conversationnel

## Contrat d'architecture produit

- **Telegram = interface coach** : messages, adaptations, relation, proactivité
- **App = interface performance** : calendrier, charge, exécution, progression
- le contrat UX détaillé de l'app vit dans `APP-UX.md`
- Le domaine entraînement doit rester pur autant que possible
- Les effets de bord vivent dans les orchestrateurs : API, bot, scheduler
- Les futures briques de sophistication doivent s'appuyer sur une vérité planning stable

## État réel du code — 17 avril 2026

**Déployé sur Fly.io : https://the deployed app/**

### Ce qui existe et tourne

- API FastAPI + bot splittés par domaine (34 modules, ~5200 lignes Python)
- Webapp React/Vite/Tailwind v4 mobile-first servie par FastAPI après build
- Bot Telegram avec onboarding conversationnel + commandes + crons
- Planner hebdo multisport déterministe
- Mutation loop : message → LLM → decision → update plan → réponse
- Mémoire utile via UserFact (extraction + upsert + sélection pour prompt)
- `UserFact` enrichi avec sémantique mémoire : `urgency`, `ttl`, `affects`, `expires_at`
- mémoire V2 amorcée :
  - `UserFact` sert maintenant surtout de backing `profile_memory`
  - `working_memory_entries` porte le court terme
  - `user_patterns` porte les patterns promus de façon déterministe
  - une maintenance loop purge et promeut régulièrement ces couches
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
- `/api/v0/week` reste une surface template/compat marquee `runtime_role=template_compat`; les surfaces runtime app passent par les read models dedies
- les vues app datees exposent aussi un `load_band` dérivé pour distinguer plus clairement hard / moderate / easy / recovery / mobility
- La boucle coach reçoit aussi la timeline datée et peut cibler une séance précise
- `swap_sessions` sait aussi passer par des ids de séances concrètes
- Router stats performance : `training-load`, `volume`, `records`
- App React Router structurée autour de 3 surfaces primaires `Aperçu / Calendrier / Évolution`
- route dédiée `/workout/:sessionId` pour le détail séance
- read models backend dédiés : `/api/v0/app/overview`, `/api/v0/app/calendar`, `/api/v0/app/evolution`, `/api/v0/sessions/{id}`
- `calendar_resolution.py` résout `planned / done / missing / offplan` côté backend
- `load_projection.py` calcule la vision de montée de charge sur 4 semaines
- Motion, Embla et Recharts branchés pour la fidélité visuelle + les interactions
- `Aperçu` enrichi : contexte de forme + prochains jours + utilitaires secondaires
- Strava callback redirige vers webapp (plus de JSON brut)
- `/help` Telegram
- Grounding conversationnel pose : `execution_context.py`, `temporal_resolver.py`, `activity_claims.py`, `conversation_context.py`
- Nouveau bounded context `user indications` : interpretation LLM bornee, resolution planning future et routing metier (`user_indications.py`, `user_indication_llm.py`, `planning_window_resolution.py`)
- Tool mémoire partagé : `fact_memory.py`
- Socle runtime tools posé : `tool_contract.py`, `tool_registry.py`, `tool_runtime.py`, `tool_metrics.py`, `tool_routing.py`, `conversation_prompting.py`
- Le chat peut maintenant faire un unique tool call read-only borne pour certaines questions de lecture
- Les tools offerts au chat sont maintenant choisis par routing déterministe selon le type de question
- Le prompt conversationnel commence aussi a se compacter selon la requete, au lieu d'injecter toujours les memes blocs
- Le prompt conversationnel est maintenant splitte en 2 zones avec une partie `system` stable cachee cote Anthropic
- Le chemin live `llm.decide()` passe maintenant par `prompt_layers.py` / `llm_prompt_builder.py`
- Un `profile_summary` deterministe compacte maintenant le profil injecte au coach
- Les metrics tools couvrent aussi maintenant les branches `tools offerts sans appel`, `tool loop complete` et `fallback de la boucle`
- Les metrics tools remontent aussi un volume de prompt exploitable (`prompt_char_count`, `history_messages_used`, `tool_count_offered`)
- La boucle coach reçoit maintenant un résumé structuré `prévu vs réel`, une résolution temporelle, des claims d'activité récents, une mémoire utile sélectionnée et quelques signaux filtrés
- Les mutations structurantes passent maintenant par une policy d'impact explicite avec confirmation `oui/non`
- Chaque tour de conversation est maintenant persisté dans `conversation_turns` avec contexte, décision et memory writes
- Le hotspot `repository.py` commence a se vider via un premier slice `repo_conversation.py`
- `signals.py` et `heartbeat.py` lisent mieux les activités réelles hors plan au lieu de s'appuyer uniquement sur le plan
- le chat et le heartbeat traitent maintenant le calendrier daté / app comme source de vérité planning avant le `WeeklyPlan`
- L'evaluation des garde-fous heartbeat est maintenant extraite dans `heartbeat_evaluation.py`
- Les runtime tools couvrent aussi maintenant `get_recent_reality_window` et `get_load_context`
- le moteur planner V2 a maintenant `session_templates.py` + `plan_validator.py`
- `planner.py` consomme déjà `PlanningDecision` pour structurer la semaine avant le LLM
- l'onboarding et la régénération hebdo passent maintenant par `planning_state.py`

- **Mutation middleware** : `mutation_hooks.py` — pre/post hooks autour des mutations. Les pre-hooks valident plausibilité (date passée, collision séance intense, limite hard/week). Les post-hooks calculent l'impact (delta charge, séances clé affectées, recovery perdu) et déclenchent une recalibration si seuil franchi.
- **Intent-based tool routing** : `tool_routing.py` refactoré — classification d'intent déterministe (9 catégories : casual_chat, execution_report, plan_negotiation, plan_lookup, activity_review, activity_highlights, load_review, fact_recall, generic_question) avec budget de tools explicite par catégorie. Remplace le matching regex par mots-clés.
- **Heartbeat par rôles** : `heartbeat_roles.py` — 4 rôles bornés (BriefingRole, ReminderRole, ReviewRole, SignalRole) avec capabilities déclarées (can_read, can_write, max_output_sentences). Chaque rôle a son propre prompt builder. `heartbeat.py` reste la façade qui gère le gating et la livraison.
- **Prompt layers** : `prompt_layers.py` — assemblage structuré du prompt en 5 couches (L0: identité coach, L1: profil athlète, L2: état plan, L3: contexte immédiat, L4: mémoire épisodique) avec budgets token par couche et cache breakpoints pour prompt caching Anthropic.
- **Ops plane** : `api_ops.py` — endpoints `/ops/` séparés du tool plane conversationnel. Inspection signaux, mémoire, mutations récentes, stats tools. Auth debug distincte.
- **Tool observability** : `tool_runtime.py` enrichi avec post-hooks — annotation résultats vides, annotation latence sur appels lents.
- **Structure backend rangée par clusters** :
  - `fitmas/tools/` pour les modules runtime tools
  - `fitmas/skills/heartbeat/` pour le cluster heartbeat
  - wrappers de compat gardés aux anciens chemins pour éviter un big bang d'imports

### Durcissement conversation — 15-17 avril 2026

- **Turn planner LLM** (`conversation_turn_planner.py`, e79d734) : classifieur read-only (Haiku) execute avant les side-effects du pipeline conversation. Sort un `ConversationTurnPlan` avec `primary_intent`, `secondary_intents`, `has_plan_mutation`. Le pipeline arbitre `plan_mutation_request = heuristic OR llm` — aucun des deux ne peut silencieusement supprimer l'intention (failles A/C closures).
- **LLM gateway unifie** (`llm_gateway.py`, eea74e7) : toutes les routes LLM passent par un client partage et un parseur JSON robuste (strip fences, balanced prefix, truncated repair). Les queues tronquees et le prose residuel ne droppent plus les payloads valides.
- **Force LLM arbitrage sur mutation** (af54eda, faille B) : quand l'heuristique flagge `plan_mutation`, le contexte availability / adaptation / health est route au LLM au lieu d'etre applique en early-exit deterministe. Les clarifications execution et contestations sont aussi skippees.
- **Block_reason typed** (199a40e) : `PlanMutationService` expose `PlanBlockedMutationEvent.block_reason`. La reply utilisateur est derivee du code (`protected_recovery_target`, `same_sport_proximity`, `occupied_training_target`), jamais improvisee par le LLM. Chaque blocage loggue un `mutation_blocked` structure.
- **Observabilite LLM failures** (e81c3da, faille D) : `_classify_llm_exception` retourne des labels stables (`timeout / rate_limit / bad_request / auth / connection / api_other / json_parse / unknown`). Le pipeline distingue `llm=unavailable` (crash) de `llm=False` (classifieur propre) pour le WARNING de divergence heuristique.
- **Protected recovery guards** (b39c712, 216bf11, 605eb5f) : `mutation_hooks` etend `protected_recovery_target` aux mutations `replace / update / lighten / move` et autorise `swap_sessions` meme si la seance de recuperation est impliquee (c'est un satellite).
- **Briefing grounding** (910f47a) : le prompt de briefing matin recoit des compteurs execution 7 jours (`planned / confirmed / claimed / missed_streak`). Le systeme prompt interdit d'inventer un decompte hebdo. Empeche la confabulation "tu as sorti 4 seances cette semaine" quand une seule a reellement eu lieu.
- **Streak signal propre** (a59a6da) : `signals.py` filtre les activites non-substantives (< 15 min) avant de calculer un streak — une marche courte ne deverrouille plus le signal `streak`.

### Digest coach — 19 avril 2026

- **`coach_reading_digest.py`** (12b4bf8) : contexte pre-digere pour messages proactifs et conversation, remplace les compteurs bruts qui faisaient parler le coach comme un dashboard.
- Deux couches :
  - **Faits (deterministe)** : reel 7j avec offplan distingue, plan 7j (prevues / executees conformes / hors plan / streak manquee), silence_days, 7j d'echanges bruts (avec fallback dernier tour meme plus vieux pour eviter l'amnesie sur silence long), patterns `user_patterns`, contexte jour.
  - **Lecture (LLM pre-pass Haiku JSON)** : triplet `{sens_du_jour, angle, ne_pas_faire}` que le LLM de composition finale suit.
- Injection :
  - **Briefing matin** (`skills/heartbeat/roles.py`) : remplace le bloc `Execution reelle semaine` par le digest. Voice rules : interdit `zero realisees` quand offplan > 0, interdit `oublie la culpabilite`, conseils sommeil/assiette sans signal, listings TSS/CTL abstraits, felicitations vides. A faire : reconnaitre ce qui est fait (y compris offplan), poser UNE question si un pourquoi manque, aligner le ton sur le dernier echange.
  - **`decide()`** : via `coach_context["coach_reading_digest_text"]` consomme par le layer `immediate` (`prompt_layers.py`), gate par `turn_plan.primary_intent in {plan_lookup, execution_report, availability_constraint}`. Les intents mutation n'activent pas le digest (le prompt de mutation a deja son propre grounding).
- Degradation : lens Haiku rate → `lens=None`, les faits partent seuls. Digest entier rate → fallback sur le bloc `recent_reality` legacy.
- Audit : logs structures `coach_reading_lens.ok / .dropped / .failed` avec timing + champs tronques.
- Tests : 3 snapshots sur fixtures (offplan / vide / conforme) verrouillent le rendu — les changements de format sont attrapes immediatement.

### Ce qui n'existe pas encore

- Consolidation memoire periodique propre
- Heartbeat scoring tick-based
- Verrou robuste anti-doublon multi-instance
- Polish visuel écran par écran pour coller encore davantage au Figma
- Périodisation plus riche que le simple cycle actuel
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
| Front | React 18 + Vite + React Router + Tailwind CSS v4 + motion + Embla + Recharts | Fidélité UI, maintenance, animations, écrans modulaires |
| Cron | APScheduler (in-process) | Pas de Temporal en V0. Suffisant pour 1 user. |
| Messagerie | Telegram bot (python-telegram-bot 21) | Gratuit, instantané, proactivité validée |
| IA | DeepSeek V4 (`deepseek-v4-flash` quotidien, `deepseek-v4-pro` plans/coach) | API Anthropic-compatible + tools + JSON robuste ; `ANTHROPIC_API_KEY` reste fallback temporaire |
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
1. substrate partagé de capacités métier (`reality / planning / session_drafting / session_analysis / plan_review`)
2. weekly reality digest + consolidation mémoire utile
3. split progressif restant du repository (`memory / planning / activities / adaptation / read models`)
4. heartbeat scoring tick-based
5. verrou robuste anti-doublon multi-instance
6. ensuite seulement : planner plus riche, polish Figma, extensions
Voir `BUILD-ORDER.md` pour le sequencing canonique.

### Pourquoi le calendrier persistant reste une fondation, mais plus le prochain chantier

Le principal défaut structurel recent etait le pilotage runtime par un `WeeklyPlan` destructif.
Ce pivot est maintenant largement pose : `ScheduledSession` est la verite planning runtime, `CoachStateBundle` centralise la lecture, et `PlanMutationService` centralise les writes visibles avec events.

Il reste utile de garder `WeeklyPlan` / `DayPlan` comme template planner, onboarding, regeneration et compat `/api/v0/week`, mais ils ne doivent plus ancrer chat, heartbeat ou read models app.

Conséquence récente importante :
- Telegram et l'app doivent suivre la timeline datée quand elle diverge du template
- les futurs nettoyages doivent supprimer les vieux consommateurs compat plutot que recreer une deuxieme verite

## Modules

```
backend/src/fitmas/
├── tools/
│   ├── contract.py         — contrat typed des tools runtime
│   ├── registry.py         — registre explicite des tools read-only
│   ├── routing.py          — routing d'intent -> budget de tools
│   ├── runtime.py          — executor borne + trace
│   └── metrics.py          — metrics et observability tools
├── skills/
│   └── heartbeat/
│       ├── heartbeat.py    — facade generation/gating heartbeat
│       ├── evaluation.py   — garde-fous proactifs
│       └── roles.py        — roles heartbeat et prompt builders
├── api.py                 (46 lignes) — bootstrap FastAPI + lifespan
├── api_static.py          (~50 lignes) — health + shell SPA React + assets buildés
├── api_read.py            (~150 lignes) — profile, week, today, timeline, messages, facts, activities
├── api_app.py             (~120 lignes) — read endpoints app dedicaces overview/calendar/evolution/session detail
├── api_onboarding.py      (134 lignes) — preview, onboard, regenerate
├── api_plan.py            (~50 lignes) — actions déterministes sur séances datées
├── api_stats.py           (~30 lignes) — endpoints stats performance
├── api_messages.py        (80 lignes) — boucle message -> decision -> facts + timeline datee
├── api_activities.py      (121 lignes) — activités manuelles + Strava OAuth/sync
├── api_debug.py           (97 lignes) — debug protégé, heartbeat manuel, reset
├── api_support.py         (137 lignes) — normalisation onboarding + garde-fous debug
├── api_payloads.py        (38 lignes) — payloads Pydantic
├── app_views.py           (~250 lignes) — composition read models app
├── user_indications.py    (~180 lignes) — contrat ferme des signaux user (dispo, sante, execution)
├── user_indication_llm.py (~70 lignes) — extraction structuree d'indications utilisateur
├── planning_window_resolution.py (~120 lignes) — grounding planning date pour contraintes futures
├── calendar_resolution.py (~140 lignes) — résolution planning vs réel pour le calendrier
├── telegram_bot.py        (48 lignes) — bootstrap bot
├── telegram_onboarding.py (274 lignes) — ConversationHandler onboarding
├── telegram_commands.py   (151 lignes) — commandes et free text
├── telegram_scheduler.py  (159 lignes) — jobs APScheduler du bot
├── telegram_api.py        (41 lignes) — client backend partagé pour le bot
├── telegram_shared.py     (67 lignes) — constantes + persistance drafts + helpers rendu
├── telegram_channel.py    (44 lignes) — résolution chat_id + envoi Telegram partagé
├── llm.py                 (~630 lignes) — Anthropic client, decisions, extraction, formulation
├── memory_profile.py      (~15 lignes) — facade explicite profile memory au-dessus de UserFact
├── memory_routing.py      (~40 lignes) — split profile vs working memory selon TTL
├── memory_patterns.py     (~200 lignes) — promotion deterministe des patterns depuis messages, activites, adaptations
├── memory_maintenance.py  (~40 lignes) — boucle maintenance memoire : purge working + sync patterns
├── load_projection.py     (~90 lignes) — projection de charge backend sur 4 semaines
├── repository.py          (469 lignes) — CRUD + convertisseurs Pydantic
├── planner.py             (359 lignes) — planner multisport déterministe
├── heartbeat.py           — wrapper de compat vers `skills/heartbeat/heartbeat.py`
├── heartbeat_evaluation.py — wrapper de compat vers `skills/heartbeat/evaluation.py`
├── heartbeat_roles.py     — wrapper de compat vers `skills/heartbeat/roles.py`
├── signals.py             (312 lignes) — signaux dérivés
├── time_context.py        (122 lignes) — timezone + helpers UTC
├── tool_contract.py       — wrapper de compat vers `tools/contract.py`
├── tool_registry.py       — wrapper de compat vers `tools/registry.py`
├── tool_routing.py        — wrapper de compat vers `tools/routing.py`
├── tool_runtime.py        — wrapper de compat vers `tools/runtime.py`
├── tool_metrics.py        — wrapper de compat vers `tools/metrics.py`
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
├── index.html             — entree Vite
├── package.json           — stack frontend + scripts build/dev
├── public/
│   └── manifest.json      — manifest PWA
└── src/
    ├── app/               — router + layout shell
    ├── features/          — overview, calendar, evolution, workout-detail
    ├── shared/            — API, format, visuels, primitives UI
    ├── state/app-actions.tsx — mutations UI + revalidation
    ├── lib/polyline.ts    — decodage polyline Strava
    ├── styles/            — index.css, theme.css
    └── test/              — Vitest + routes + view models
```

## Contrat app React

- les lectures d'écran passent par des loaders par route
- l'état global React ne porte plus toute la lecture de l'app
- les mutations (`done / skip / move / add activity / strava sync`) vivent dans un petit provider de revalidation
- le backend envoie déjà des payloads prêts pour l'UI
- l'app adapte le rendu au produit, pas l'inverse

## Read models backend app

### `GET /api/v0/app/overview`

- séance du jour si présente
- séance lead de fallback si aujourd'hui est vide
- prochains jours
- snapshot charge / TSS / complétion
- profil court + statut Strava

### `GET /api/v0/app/calendar?month=YYYY-MM`

- vue mois pré-résolue
- statut de chaque entrée : `planned`, `done`, `missing`, `offplan`
- date affichée, date planifiée, date exécutée
- contexte semaine courante / mésocycle

### `GET /api/v0/app/evolution`

- historique charge réelle
- semaine courante prévu vs réalisé
- distribution de charge
- projection 4 semaines
- flags de risque + rationale coach

### `GET /api/v0/sessions/{session_id}`

- séance unique riche
- activité liée si présente
- métriques utiles
- bloc coach
- distribution de zones
- polyline éventuelle

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
7. Backend persiste User + UserSport + UserFact + WeeklyPlan + DayPlan, puis instancie la verite runtime en `ScheduledSession`
8. Webapp affiche récap → semaine → today

### Flux message entrant
1. User envoie un message (Telegram ou webapp)
2. Backend persiste CoachMessage(role=user)
3. Interpreter : `user_indication_llm` produit un `UserIndication` structure
4. Turn planner : `conversation_turn_planner` classe `primary_intent` + `secondary_intents` (Haiku, read-only)
5. Gates deterministes : confirmation pending, low-signal, calibration, clarification — skippes si `plan_mutation_request == true`
6. Grounding : claims activite / non-completion, contexte adaptation / availability routes au LLM selon le turn plan
7. `llm.decide()` : Haiku avec prompt layers + tool budget route par `primary_intent` — sort une `MutationDecision`
8. Validation : `mutation_permissions.assess_mutation_impact` → confirmation pending si requires_confirmation
9. `PlanMutationService` : pre-hooks coherence → writer → events (ou `blocked_events` avec `block_reason` typed)
10. Reply finale derivee de l'event applique ou du `block_reason`
11. Persistance `CoachMessage(role=agent)` + `conversation_turns`
12. Extraction facts stables a memoriser, promotion patterns


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
- le matching et certains marquages auto gardent encore des traces de logique hebdomadaire legacy
- la vérité calendrier existe déjà, mais tout le pipeline activité n'est pas encore entièrement recentré dessus

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
