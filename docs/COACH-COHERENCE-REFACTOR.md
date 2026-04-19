---
summary: plan de refactor coherence coach/app/planning, avec verites runtime, writer unique, bundle partage et gates de verification
read_when:
  - lancer le refactor coherence coach
  - corriger une contradiction coach vs app
  - unifier les writes planning et les evenements de mutation
  - retirer WeeklyPlan ou DayPlan des lectures runtime
  - durcir adaptation, heartbeat ou tools autour d une verite unique
---

# Coach Coherence Refactor

## But

Remettre FitMAS sur une base simple, lisible et fiable avant toute sophistication supplementaire.

Le probleme principal n'est pas le prompt.
Le probleme principal est la gouvernance de l'etat :

- plusieurs verites planning runtime
- plusieurs writers capables de muter le planning
- plusieurs lectures user-facing qui ne racontent pas la meme histoire
- plusieurs chemins de narration pour expliquer ou nier les changements

Le chantier vise donc une coherence-first refactor :

- une verite planning runtime
- un writer unique
- un bundle de lecture partage
- une explication derivee du changement applique
- aucun write tool libre donne au modele

## Objectifs

- le coach et l'app lisent la meme verite planning live
- aucune mutation planning visible n'existe sans evenement d'audit
- chaque changement applique peut etre explique depuis son evenement reel
- le coach ne peut plus nier un etat deja visible dans l'app
- la base devient assez simple pour faire evoluer planner, heartbeat, memoire et tools sans spaghetti

## Hors scope

- refaire tout le planner multisport
- ouvrir des write tools runtime au LLM
- introduire du multi-agent produit
- optimiser le ton ou l'UI avant d'avoir repare la coherence
- lancer une migration infra lourde ou multi-user

## Principes

### 1. One runtime planning truth

`ScheduledSession` devient l'unique verite planning live.

Consequence :

- l'app lit `ScheduledSession`
- le coach lit `ScheduledSession`
- le heartbeat lit `ScheduledSession`
- `WeeklyPlan` et `DayPlan` cessent d'etre une verite runtime

### 2. One execution truth

La verite execution reste construite sur :

- `Activity`
- user claims bornes
- `ExecutionEvidence`
- `RecentRealityWindow`

### 3. One mutation writer

Toute mutation planning runtime passe par un seul gateway de write.

Regle :

- conversation explicite et actions app peuvent demander une mutation
- un seul service l'applique vraiment
- aucun autre chemin ne mute le planning live en direct

### 4. One shared read bundle

Les surfaces user-facing lisent le meme bundle de verite ou des slices strictes de ce bundle.

Cible :

- Telegram
- heartbeat
- app overview
- app calendar
- ops/debug si besoin

### 5. Explain from event, not from prompt fantasy

Le message visible doit etre derive d'un evenement de mutation reel.
On ne veut plus d'explication inventee a cote du vrai changement applique.

### 6. Tools read, orchestrators write

Les tools runtime restent peu nombreux et read-only.
Les side effects restent possedes par les orchestrateurs.

### 7. Memory is layered

- identite / doctrine
- profile memory durable
- runtime state courant
- working memory court terme
- transcript et event truth pour audit

Le prompt ne doit jamais arbitrer deux verites planning concurrentes.

## Modele cible

### `PlanTemplate`

Role :

- stocker l'intention hebdo
- servir de template planner

Backing :

- `WeeklyPlan`
- `DayPlan`

Regle :

- jamais utilise comme verite planning live

### `SessionInstance`

Role :

- seule verite planning datee

Backing :

- `ScheduledSession`

Semantique cible :

- `status`: `planned | adapted | done | skipped | canceled`
- `instance_kind`: `training | placeholder | recovery | offplan_shadow`
- `origin`: `planner | user_action | adaptation | import`
- `origin_event_id`

### `PlanMutationEvent`

Role :

- audit canonique de chaque mutation appliquee

Champs cibles :

- `source`
- `trigger_type`
- `command_type`
- `target_session_ids`
- `before_snapshot_json`
- `after_snapshot_json`
- `reason_json`
- `impact_json`
- `user_visible_summary`
- `explained_to_user`
- `conversation_turn_id`
- `created_at`

Regle :

- chaque mutation appliquee cree exactement un evenement

### `CoachStateBundle`

Role :

- read model canonique pour toutes les surfaces user-facing

Contenu cible :

- `clock`
- `timeline`
- `today`
- `next_72h`
- `recent_reality`
- `week_mission`
- `planning_contract`
- `open_clarifications`
- `last_mutation`
- `truth_notes`

Important :

- au debut du chantier, ce bundle peut etre un builder deterministe non persiste
- on converge d'abord en code avant de formaliser davantage

## Contrat de migration

### Runtime truth

Des le debut du chantier :

- `ScheduledSession` = seule verite planning runtime
- `WeeklyPlan` et `DayPlan` = template / input planner uniquement

### Read contract

Pendant toute la migration :

- le coach ne lit plus `WeeklyPlan` ou `DayPlan` comme verite live
- le heartbeat ne lit plus `WeeklyPlan` ou `DayPlan` comme verite live
- les read models app ne lisent plus `WeeklyPlan` ou `DayPlan` comme verite live

### Write contract

Pendant toute la migration :

- `WeeklyPlan` et `DayPlan` peuvent encore etre ecrits par planner, onboarding ou regeneration
- ces ecritures ne sont pas des mutations runtime visibles
- toute mutation planning visible passe par le writer unique sur la timeline datee

### Freeze matrix

Writers temporairement autorises :

- conversation explicite utilisateur
- actions app explicites

Chemins forces en suggestion-only pendant la phase initiale :

- `backend/src/fitmas/adaptation.py`
- `backend/src/fitmas/skills/heartbeat/heartbeat.py`
- les chemins post-activity
- tout trigger background ou cron qui touche au planning

Regle :

- si un chemin n'est pas autorise, il ne peut pas appeler `mutations.apply()` ou `plan_actions.*` pour modifier le planning live

## Phases

## Statut actuel

### Mise a jour du 17 avril 2026 — durcissement conversation

Une passe dediee a la fiabilite conversation a ete close :

- **Intent routing arbitrage** : `plan_mutation_request = heuristic OR llm_turn_planner` (failles A + C closures). Divergence → WARNING structure, `llm=unavailable` accepte sans downgrade (e79d734, b78db28).
- **LLM force arbitrage sur mutation** (faille B, af54eda) : les early-exits deterministes (availability week_scope / no_candidate, adaptation candidate, health auto-apply, execution clarification, execution contestation) sont gatees sur `plan_mutation_request`. Un message compose `mutation + claim` ne peut plus etre silencieusement swallowe par un extracteur deterministe.
- **LLM failure modes types** (faille D, e81c3da) : `_classify_llm_exception` produit des labels stables pour triage operationnel.
- **JSON parsing robuste** (eea74e7) : tous les chemins LLM passent par `llm_gateway._robust_json_loads` — les queues tronquees et le prose residuel ne droppent plus de payloads.
- **Protected recovery guards** (b39c712, 216bf11, 605eb5f) : extension `protected_recovery_target` aux mutations `replace / update / lighten / move` + autorisation `swap` impliquant une recuperation (c'est un satellite).
- **Block_reason typed propage a l'utilisateur** (199a40e) : le pre-hook ne produit plus une reply generique, mais une raison lisible (`protected_recovery_target`, `same_sport_proximity`, `occupied_training_target`).
- **Briefing grounding** (910f47a) : compteurs execution 7 jours injectes dans le briefing matin — ferme un trou de confabulation de decompte hebdo.
- **Streak signal propre** (a59a6da) : activites < 15 min filtrees avant computation streak.

Invariants consolides :
- aucun side-effect planning ne peut arriver avant l'arbitrage du tour quand une mutation est demandee
- la reply de mutation bloquee est derivee du `block_reason` typed, jamais improvisee
- le briefing matin ne peut plus citer un decompte hebdo en l'absence de compteurs reels

### Audit du 13 avril 2026

Verdict franc :

- phase 0 = fermee (prompts live ne dependent plus de WeeklyPlan/DayPlan comme verite)
- phase 1 = fermee cote lectures app (overview, calendar, evolution, session detail lisent ScheduledSession)
- phase 2 = fermee cote routing (PlanMutationService est le gateway unique)
- phase 3 = partiellement fermee (lectures user-facing migrees, mais signals.py lit encore WeeklyPlan)
- phase 4 = partiellement fermee (adaptation produit des propositions, mais certains chemins auto-appliquent encore)
- phase 5 = fermee sur 2 guards (same_sport_proximity, protected_recovery_target)

#### Realite dual-write non resolue

Le pattern reel du systeme de mutation est un **dual-write** `ScheduledSession` + `DayPlan`.

`plan_actions.py` ecrit dans DayPlan dans **tous** ses chemins principaux :
- `lighten_session()` mute DayPlan
- `modify_session()` mute DayPlan
- `replace_session()` mute DayPlan
- `swap_sessions()` mute DayPlan directement
- `move_session_to_date()` lit et mute DayPlan
- `set_completion_status()` mute DayPlan

`plan_mutation_service.py` appelle `repo.mark_day_completed()` a chaque completion.
`strava.py` et `api_activities.py` marquent DayPlan done via `mark_day_completed_for_user()`.

Ce n'est pas du template/compat — c'est le coeur du systeme de mutation.

#### Lectures legacy encore actives

`signals.py` (354 lignes) lit `WeeklyPlan` / `DayPlan` pour les 5 detecteurs de signaux.
Ces signaux alimentent le heartbeat (user-facing). Ce n'est pas isole.

`activities.py` matche les activites Strava contre `DayPlan` via `match_activity_to_day()`.

#### Ce qui a ete retire (reel)

- lectures DayPlan dans les read models app (overview, calendar, evolution, session detail)
- DayPlan dans TodayView et `/api/v0/today/{day}`
- DayPlan dans le briefing heartbeat
- plan_summary legacy dans la plomberie conversationnelle
- WeeklyPlan dans le chemin conversation (`ConversationTurnState`)
- Telegram `/plan` lit la timeline datee

#### Ce qui reste

- **dual-write actif** dans plan_actions.py (6 chemins)
- **dual-write completion** dans plan_mutation_service / strava / api_activities
- **runtime read** dans signals.py (5 detecteurs)
- **runtime read** dans activities.py (matching Strava)
- `/api/v0/week` comme compat endpoint
- frontend dead code (`src/pages/`, `src/lib/api.ts`)

### Audit precedent du 10 avril 2026

Ce qui a ete retire pour fermer la phase 1 :

- le fallback `DayPlan` dans `/api/v0/today/{day}`
- les lectures `DayPlan` dans `TodayView`
- les lectures `DayPlan` dans le detail seance app
- la reprise `DayPlan` dans le briefing heartbeat
- le passage de `plan_summary` legacy dans la plomberie conversationnelle

Verification realisee :

- `./scripts/test-backend -q tests/test_coach_state_bundle.py tests/test_prompt_truth_gates.py tests/test_plan_mutation_service.py tests/test_app_endpoints.py tests/test_core_flows.py tests/test_heartbeat_grounding.py`
- `./scripts/test-backend -q tests/test_adaptation.py tests/test_api_messages_helpers.py tests/test_temporal_resolver.py tests/test_llm_prompt_builder.py`
- `83 passed`

### Phase 0 - Freeze and protect

But :

- stopper les nouvelles incoherences pendant le refactor

Actions :

- retirer le resume legacy du plan des prompts live
- desactiver les writes planning background non visibles
- forcer les flows mutateurs a passer par un gateway temporaire unique
- transformer les incidents reels en tests de regression
- poser la freeze matrix dans le code et la doc

Exit gates :

- aucun prompt user-facing n'injecte `WeeklyPlan` ou `DayPlan` comme verite runtime
- aucun chemin background n'appelle de write planning live
- les incidents reels sont rejouables en tests
- seules la conversation explicite et les actions app peuvent muter le planning

### Phase 1 - Single read truth

But :

- introduire `CoachStateBundle`

Actions :

- extraire un builder deterministe commun
- faire lire ce bundle par la conversation et le heartbeat
- faire deriver les vues app du meme bundle
- garder les payloads d'endpoint stables pour le front

Exit gates :

- coach et app sont alignes sur `today`, `next_72h` et la semaine visible
- aucun contrat frontend n'est casse
- plus aucun chemin de lecture user-facing ne depend de `DayPlan` comme verite live

Statut au 10 avril 2026 :

- bundle partage = en place
- alignement principal app / conversation / heartbeat = en place
- gate stricte `no DayPlan runtime truth` = satisfaite

### Phase 2 - Single writer

But :

- introduire `PlanMutationService`

Actions :

- faire passer tous les writes planning par ce service
- produire un record canonique de mutation
- deriver l'explication visible depuis le delta applique
- introduire `plan_mutation_events` en forward-only quand le contrat est stable

Exit gates :

- aucun write planning ne survit hors `PlanMutationService`
- chaque mutation appliquee cree exactement un event
- chaque reponse utilisateur sur mutation est derivee de l'event applique

Statut courant :

- premier slice en place
- table forward-only `plan_mutation_events` ajoutee
- `PlanMutationService` route maintenant :
  - decisions conversation via l'executeur interne `mutations.apply`
  - actions app explicites `complete / skip / move`
  - completion liee aux activites manuelles et Strava
  - contestations d'execution conversationnelles vers `skip`
  - sync legacy `DayPlan done` depuis activite, en attendant retrait complet du template live
- chaque action appliquee par ce service ecrit maintenant un event minimal avec source, trigger, command, ids cibles, snapshots JSON, raison, impact et resume visible disponible
- la completion activite + sync legacy `DayPlan done` est maintenant repliee dans un seul event `activity_completed` quand une `ScheduledSession` datee existe
- les reponses conversationnelles apres mutation appliquee utilisent maintenant le `user_visible_summary` issu de l'event applique
- les reponses conversationnelles ne peuvent plus annoncer un changement applique si `applied_count` ou `event_count` vaut zero
- garde de test ajoutee pour empecher `api_plan.py`, `api_activities.py`, `api_messages.py` et `strava.py` d'appeler les writers bas niveau directement
- `mutations.py` est maintenant cache derriere `PlanMutationService` cote code live
- le gate `event_count == applied_count` est verrouille sur les decisions appliquees, y compris les decisions multi-seances comme `swap_sessions`

Phase 2 est fermee sur le gate actuel.

Reste comme durcissement ulterieur hors gate strict :

- enrichir les snapshots before/after pour les decisions legacy sans `target_session_id`
- renommer `mutations.py` si le nom continue a creer une ambiguite de frontiere

### Phase 3 - Retire legacy runtime reads

But :

- sortir definitivement `WeeklyPlan` et `DayPlan` des lectures runtime

Actions :

- les garder pour planner et template seulement
- interdire leur usage dans les prompts et lectures live
- documenter clairement `PlanTemplate` vs `SessionInstance`

Exit gates :

- aucun chemin coach, app ou heartbeat ne lit les objets legacy comme verite live
- seuls planner, onboarding et regeneration touchent encore aux templates legacy

Statut courant :

- premier slice app/stat en place
- `api_app.py`, `api_stats.py` et `performance_overview.py` ne chargent plus `WeeklyPlan` / `DayPlan` comme verite runtime
- le chemin conversation ne charge plus `WeeklyPlan` / `DayPlan` dans `ConversationTurnState`
- le heartbeat review ne charge plus `WeeklyPlan` / `DayPlan`
- Telegram `/plan` lit maintenant la timeline datee plutot que `/api/v0/week`
- `/api/v0/week` reste disponible comme surface template/compat et expose `runtime_role=template_compat`
- `CoachStateBundle` accepte maintenant l'absence de template legacy et retombe sur une meta planning neutre

Reste :

- `/api/v0/week` en compat — les anciennes pages `frontend/src/pages` ont ete supprimees le 13 avril 2026

### Phase 4 - Rebuild adaptation paths

But :

- supprimer les ghost mutations

Actions :

- `adaptation.py` ne produit plus que des propositions de mutation
- `heartbeat` peut suggerer ou mettre en attente, pas muter silencieusement
- l'auto-apply ne revient que pour des cas low-impact explicites et tracables

Exit gates :

- plus aucun write silencieux depuis adaptation ou heartbeat
- les chemins background restent suggestion-only tant que la policy n'est pas revalidee

Statut courant :

- `adaptation.py` produit maintenant des propositions uniquement
- le chemin sante conversationnel transforme une proposition d'adaptation en confirmation utilisateur, sans appliquer silencieusement
- la fatigue explicite low-impact peut encore auto-appliquer une proposition tracee via `PlanMutationService`
- l'API `allow_apply` a ete retiree de `adaptation.py`
- le heartbeat peut maintenant relayer une proposition d'adaptation (`tsb` / seances manquees) sans attendre `applied=True` et sans ecrire au planning

Reste :

- aucun gate strict restant

Policy future pour reouvrir l'auto-apply low-impact :

- seulement depuis un orchestrateur explicite, jamais depuis `adaptation.py`
- uniquement si `assess_mutation_impact(...).requires_confirmation == False`
- passage obligatoire par `PlanMutationService`
- event `plan_mutation_events` obligatoire avant toute reponse qui parle de changement applique
- source explicite (`conversation`, `app`, `strava`, `heartbeat`) et `trigger_type` explicite
- heartbeat/background restent suggestion-only tant que cette policy n'a pas de test dedie par trigger

### Phase 5 - Add semantic coherence guards

But :

- empecher les semaines localement absurdes

Actions :

- ajouter `session_similarity`
- penaliser ou bloquer les quasi-doublons meme sport sur 24-48h
- proteger recuperation et mission hebdo au niveau writer

Exit gates :

- les quasi-doublons n'apparaissent plus sans justification explicite
- un move ne peut plus casser silencieusement la coherence locale de la semaine

Statut courant :

- `PlanMutationService` passe maintenant la timeline runtime a l'executeur de mutation pour alimenter les hooks de coherence
- premier guard pose : un `move_session` avec date explicite qui cree un quasi-doublon meme sport / meme type a moins de 48h est bloque avec `same_sport_proximity`
- ce guard couvre les decisions conversationnelles et les actions app avec `target_date`; les moves app sans date restent un auto-placement a traiter separement si besoin
- deuxieme guard pose : un `move_session` vers une recuperation stable/protegee est bloque avec `protected_recovery_target`, tandis qu'un repos `flexible` reste utilisable
- troisieme guard pose : un `move_session` vers une journee qui contient deja une vraie seance training est bloque avec `occupied_training_target`; il faut un `swap_sessions` ou une clarification
- la similarite initiale vit dans `session_similarity.py` pour pouvoir etre enrichie sans grossir `mutation_hooks.py`

Phase 5 est fermee sur le gate actuel.

Reste comme durcissement ulterieur hors gate strict :

- enrichir la notion de similarite au-dela de `sport_type + session_type`
- enrichir la mission hebdo au niveau writer quand le signal produit sera plus concret

### Phase 6 - Tools and memory cleanup

But :

- aligner tools et memoire sur le nouveau modele de verite

Actions :

- n'exposer au LLM que des slices read-only du bundle
- ne plus utiliser les events comme pseudo-memoire
- construire un `WeeklyRealityDigest`
- garder transcript et events comme inputs de digest, pas comme dump prompt

Exit gates :

- le prompt recoit la verite runtime + une memoire selectionnee compacte
- les tools LLM-facing restent peu nombreux et read-only

## Verification

### Invariants a verrouiller

- coach et app lisent les memes session instances pour `today`, `next_72h` et la semaine visible
- chaque mutation appliquee a exactement un evenement
- aucun writer silencieux ne survit
- aucun prompt live n'arbitre entre verite legacy et timeline datee
- les quasi-doublons meme sport 24-48h sont bloques ou explicitement justifies

### Cas critiques

- incident screenshot : coach dit repos, app dit natation
- confirmation future : `demain piscine sans faute j'y serai`
- alignement explicite jour/date : `demain = jeudi`
- move utilisateur avec un seul event et une seule explication
- adaptation sante sans write cache
- app overview, calendrier et heartbeat alignes sur la meme verite

### Fichiers de tests cibles

- `tests/test_coach_state_bundle.py`
- `tests/test_plan_mutation_service.py`
- `tests/test_plan_mutation_events.py`
- `tests/test_coach_app_truth_alignment.py`
- `tests/test_no_silent_mutations.py`
- `tests/test_session_similarity_guards.py`
- `tests/test_freeze_matrix.py`
- `tests/test_prompt_truth_gates.py`

Extensions utiles :

- `tests/test_core_flows.py`
- `tests/test_heartbeat_grounding.py`
- `tests/test_app_endpoints.py`
- `tests/test_replan_from_life_change.py`
- `tests/test_temporal_resolver.py`

### Commandes de verification

- `./scripts/test-backend -q tests/test_coach_state_bundle.py`
- `./scripts/test-backend -q tests/test_plan_mutation_service.py`
- `./scripts/test-backend -q tests/test_prompt_truth_gates.py`
- `./scripts/test-backend -q tests/test_core_flows.py tests/test_heartbeat_grounding.py tests/test_app_endpoints.py`

## Choix de sequencing

Le point cle n'est pas de formaliser tout de suite de nouveaux objets partout.

Ordre voulu :

1. converger sur une seule lecture runtime
2. geler les writes silencieux
3. converger sur un writer unique
4. formaliser ensuite les contrats durables et la persistence cible

Formule courte :

- converge first
- formalize second
- trust before cleverness
