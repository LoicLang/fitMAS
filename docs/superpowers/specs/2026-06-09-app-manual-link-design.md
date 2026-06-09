---
summary: #4b — lien manuel activité↔séance depuis le calendrier de la webapp (mode V0). L'utilisateur rattache une activité réalisée à une séance planifiée → séance `done` + lien stocké, affiché dans le calendrier. 1er write webapp→store V0, via l'executor officiel. Inclut unlink.
read_when:
  - travailler sur le lien manuel activité<->séance dans l'app
  - ajouter un write de la webapp vers le store V0
  - toucher l'executor V0 (nouvelle commande), v0_source, ou le calendrier React
---

# #4b — Lien manuel activité ↔ séance (store V0)

> BUILD-ORDER #4, volet **app**. Décision (9 juin) : on fait **seulement le chemin app**
> maintenant ; le chemin **chat (#4a, LLM-first)** part avec la **tranche heartbeat** (différé —
> voir `2026-06-09-run-session-matching-design.md`, marqué différé).
> Lien **manuel** = l'utilisateur choisit explicitement la séance → **référence typée**, pas
> d'heuristique : le bon déterminisme (valide + commit), pas l'auto-link background refusé.

## Contexte / finding

- La webapp lit le store V0 en mode `FITMAS_APP_SOURCE=v0` via `legacy/app/api/v0_source.py`
  (sqlite brut, read-only, n'importe pas `runtime_v0`). Le calendrier montre les
  `v0_scheduled_sessions` + les `v0_activities`.
- **Les endpoints d'écriture existants** (`routes_plan.py` : `/api/v0/plan/sessions/{id}/complete`,
  `/skip`, `/move`) écrivent dans la **DB legacy** (`get_db` + `patch_mutation_service`), **pas dans
  le store V0**. En mode v0 ils sont donc **déconnectés de la vérité du coach** : cliquer
  « complete » aujourd'hui n'atteint pas le coach V0. (Cleanup à part — hors scope ici.)
- `v0_activities` n'a **pas** de colonne de lien ; `v0_scheduled_sessions` a `status`
  (`planned`/`done`/…). Le legacy avait `Activity.scheduled_session_id` + `matched_day` (on mirror
  la première).
- L'executor V0 (`runtime_v0/executor.py`, `CommandExecutor(db_path).execute(commands, turn_id,
  user_id)`) est le **writer officiel** : transactionnel, audité (`v0_command_events`). Il est
  invocable hors-runtime (il ne dépend que du `db_path`).

Ce serait le **1er write de la webapp vers le store V0**. Règle dure : aucun write hors executor →
on passe par l'executor, exposé à la webapp par un **adapter mince**.

## Décision / scope

L'utilisateur, dans le calendrier, rattache une activité réalisée à une séance planifiée :
→ la séance passe `done`, le lien est **stocké et affiché** (« complétée par ce run »), et c'est
**défaisable** (unlink). User-driven, déterministe, audité.

## Changements

### 1. Schéma (`runtime_v0/db.py`)

Ajouter `scheduled_session_id INTEGER` (nullable, défaut NULL) à `v0_activities`. **Migration
idempotente** (mirror le pattern `resolved_at` déjà présent : `ALTER TABLE … ADD COLUMN` si absent).

### 2. Executor (`runtime_v0/executor.py` + commandes)

Deux commandes typées + handlers, audités comme les autres :
- `LinkActivityToSessionCommand(activity_id, session_id)` → set `v0_activities.scheduled_session_id
  = session_id` **et** `v0_scheduled_sessions.status = 'done'` (même transaction).
- `UnlinkActivityCommand(activity_id)` → set le FK de l'activité à NULL **et** la séance liée
  repasse `status = 'planned'`.

Garde-fous handler : activité + séance existent et appartiennent au `user_id` ; sinon le handler
échoue proprement (pas d'écriture partielle).

### 3. Adapter (`runtime_v0/adapters/app_actions.py`, nouveau)

Le **seul** pont que la webapp importe (mirror `strava_v0_sync`) :
- `link_activity_to_session(v0_db_path, user_id, activity_id, session_id) -> CommandEvent`
- `unlink_activity(v0_db_path, user_id, activity_id) -> CommandEvent`

Chaque fonction construit la commande + lance `CommandExecutor(v0_db_path).execute(...)` avec un
`turn_id` synthétique (`app-link-<uuid>`). Retourne l'event d'audit.

### 4. API (`legacy/app/api/`, mode v0)

- `POST /api/v0/activities/{activity_id}/link` body `{ "session_id": int }` → appelle
  `app_actions.link_activity_to_session`. Retourne la séance MAJ (`ScheduledSession`).
- `POST /api/v0/activities/{activity_id}/unlink` → `app_actions.unlink_activity`.
- Actif seulement en mode v0 (`FITMAS_APP_SOURCE=v0`) ; `user_id` résolu comme les lectures v0.
  Valide existence (404 sinon). N'autorise pas le write si pas en mode v0 (409/400).

### 5. v0_source + view models

Exposer `scheduled_session_id` sur les activités (`get_activities` fait déjà `select *` → ajouter
le champ au `Activity` pydantic). Le calendrier peut alors afficher la séance `done` **et** le run
qui la complète. Vérifier que `ScheduledSession`/`Activity` (pydantic) portent les champs.

### 6. UI calendrier (React)

Dans le panneau jour du calendrier : sur une activité **non liée**, une action « lier à [séance du
jour] » (liste les séances `planned` du même jour). Au lien → `POST …/link` → refresh → la séance
s'affiche `done` (complétée par ce run) ; **undo** (« délier ») dispo sur une activité liée.
Composant exact à localiser en planning.

## Ce qu'on ne fait PAS (YAGNI / scope)

- Pas de matching automatique / heuristique (sport+jour) — refusé ; le lien est un **choix
  explicite**.
- Pas de chat / LLM ici (#4a → heartbeat).
- On ne **répare pas** les endpoints legacy `/complete` `/skip` `/move` (ils écrivent legacy) —
  cleanup séparé. (À noter dans BUILD-ORDER.)
- Pas de `matched_day` / raison de match (legacy) — un simple FK suffit.

## Risques / profil d'échec

- **2 stores divergents** : le bouton legacy `/complete` écrit legacy, le nouveau lien écrit v0.
  Tant que le cleanup n'est pas fait, ne pas exposer les deux dans la même UI v0 (le calendrier v0
  n'utilise que le nouveau chemin). À tracer.
- **Lien erroné** : couvert par l'unlink (état non coincé), audité dans les deux sens.
- **Write depuis la webapp** : la webapp dépend désormais de `runtime_v0` (via l'adapter). C'est un
  couplage **intentionnel et mince** (adapter only), cohérent avec la doctrine (executor = writer).

## Phasage

- **Phase 1 (backend)** : §1–5. Prouvable sans UI (tests + curl) : migration, commandes
  link/unlink (FK + status + audit), adapter, endpoint, exposition v0_source.
- **Phase 2 (UI)** : §6, le calendrier.

## Preuve

- **Couche 1** : tests executor (`link` pose FK + `done` + 1 `v0_command_events` ; `unlink`
  remet NULL + `planned` ; garde-fou user/inexistant) ; test migration idempotente ; test adapter ;
  test endpoint FastAPI (mode v0). fake-matrix `11/11`, danger `0` inchangés.
- **App** : vérif manuelle — lier un run à une séance dans le calendrier → `done` affiché +
  rattachement visible ; délier → revient `planned`. (Le coach Telegram voit ensuite la séance
  `done` au tour suivant via le snapshot — vérif bonus.)

## À localiser en planning

- Le module exact où poser les routes (`routes_activities.py` vs un nouveau `routes_v0_link.py`).
- Le composant React du panneau jour du calendrier.
- Le mécanisme de résolution du `user_id` côté v0 (comment `v0_source` choisit l'utilisateur).
