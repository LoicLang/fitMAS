---
summary: 1re brique de run<->session matching — surfacer les activités Strava réalisées dans le prompt du coach + lui apprendre à noter une séance `done` quand un run matche clairement la séance planifiée (LLM juge, auto-commit si cible unique, user-prompted). BUILD-ORDER #4.
read_when:
  - travailler sur le matching activité Strava <-> séance planifiée
  - toucher snapshot.py (header / to_prompt_text) ou le prompt coach
  - ouvrir la tranche execution-from-activity / run-session matching
---

# Run ↔ session matching (1re brique, couche 2)

> BUILD-ORDER #4. Lier un run Strava réalisé à la séance planifiée pour la noter `done`.
> Décision (9 juin) : **LLM-first**, **user-prompted**, **auto-commit si cible unique**.
> PAS d'auto-link déterministe en background (= fix-on-fix / auto-commit sur heuristique,
> classe de danger ; reconcile proactif = tranche heartbeat, différée).

## Contexte / finding

Les briques existent déjà :
- le tool `propose_execution_update(status=done|skipped|partial)` (`tools_proposal.py`) ;
- le gate policy `_execution_update` (`policy.py` : la séance doit exister, pas de `done`/`partial`
  sur une date future) ;
- `recent_activities` (les runs Strava, fenêtre J-21→J) chargés dans le `WorldSnapshot`
  (`snapshot.py`) ;
- les séances d'une semaine committée sont sur le calendrier (`v0_scheduled_sessions`, 3bis),
  donc l'exécution a une cible à accrocher.

**Trou bloquant (constaté 9 juin)** : `recent_activities` n'est **jamais rendu dans le prompt**.
`SnapshotHeader.to_prompt_text` affiche `next_sessions` (J→, **avec id**), `recent_training`
(séances planifiées J-7→J-1, **sans id**) et les faits — **pas les activités réalisées**. Le coach
est donc **aveugle au run Strava** : il ne peut pas proposer de noter la séance `done`. De plus,
pour noter une séance **passée** `done`, il lui faut **l'id** de cette séance dans le prompt — or
`recent_training` l'omet.

## Décision

User-prompted + auto si clair. Le coach agit quand l'utilisateur évoque sa sortie / demande de
logger. S'il y a **exactement une** séance du même sport ce jour-là, encore `planned` → il note
`done` directement (cible claire, auto-commit via la policy existante). **0 ou plusieurs** candidats
→ il demande, il ne devine pas. **Le LLM juge le match** (même sport, même jour) ; **zéro
regex/keyword** sur la durée/le titre.

## Changements

### 1. Prompt snapshot (`snapshot.py`)

- **Surfacer `recent_activities`** dans le header. `WorldSnapshot.header()` passe les ~5 activités
  les plus récentes à `SnapshotHeader` ; `to_prompt_text` rend une section :
  ```
  recent_activities (completed runs):
  - 2026-06-08 running 52min 9.7km strava
  ```
  (champs : `date sport durée distance source` ; distance omise si nulle.)
- **Ajouter l'id de séance** au rendu `recent_training` (séances passées), pour qu'une séance
  passée soit référençable par `propose_execution_update`. (les `next_sessions` portent déjà l'id.)
- **Budget** : `to_prompt_text` garde son `assert len(text.split()) <= 500`. Compteurs bornés
  (activités ≤ 5, recent_training déjà `[:6]`).

### 2. Prompt coach (instruction)

Apprendre au coach : quand l'utilisateur réfère à un run réalisé (ou demande de le logger) et qu'une
`recent_activities` matche clairement une séance `planned` (même sport, même date) :
- **exactement 1 candidat** → `propose_execution_update(session_id, status="done")` ;
- **0 ou plusieurs** plausibles → demander laquelle, ne pas deviner.

Le match est jugé par le LLM à partir de l'activité + du plan rendus. Ne jamais affirmer un `done`
non committé (couvert par le guard / `claim_without_event`).

## Ce qu'on ne fait PAS (YAGNI / doctrine)

- **Pas de FK activité→séance** stockée. Noter `done` est le livrable ; un lien explicite
  (`v0_scheduled_sessions.activity_id`) = nicety ultérieure, demande une colonne.
- **Pas de nouveau vérificateur déterministe de match.** Le gate `_execution_update` existant tient
  (séance existe, pas dans le futur). Le match reste jugé par le LLM, **visible** dans la réply et
  **corrigeable** (correction d'exécution déjà en scope). On n'ajoute pas de déterminisme tant qu'on
  n'a pas la preuve d'une dérive.
- **Pas de reconcile proactif/background** (sans message user) = tranche heartbeat, différée.

## Risques / profil d'échec

- Le LLM propose la mauvaise séance (hallucine un match) → faux `done`. Mitigation : cible unique
  seulement en auto ; sinon il demande. L'erreur est **visible** (réply « j'ai noté la séance X
  done ») et **recoverable** (correction d'exécution). C'est le profil **safe** vs l'auto-link
  background silencieux refusé.
- Run hors-plan le même jour qu'une séance planifiée → risque de noter `done` une séance pas faite.
  Mitigation : le coach voit l'activité ET la séance ; l'utilisateur a initié le tour (« j'ai fait
  ma sortie »), donc le contexte conversationnel désambiguïse. À surveiller en couche 2.

## Preuve

- **Couche 1** : tests de rendu snapshot (section `recent_activities` présente ; id de séance passée
  présent) ; fake-matrix reste `11/11`, danger metrics `0`, guard fallback `0 %`.
- **Couche 2** : probe dédiée (`scripts/v0_eval/probe_*`) sur un tour réel non scripté —
  « j'ai fait ma sortie d'hier » + un run Strava matchant une séance planifiée → le coach note
  `done` (auto, cible unique), guard clean, réply honnête. Cas **ambigu** (2 séances même sport
  même jour) → il demande, 0 commit. Oracle déterministe + juge LLM.

## À localiser en planning

- Le fichier du prompt coach (instructions système de l'agent) où brancher la consigne.
- La forme exacte du rendu `recent_activities` (vérifier le budget 500 mots sur un snapshot réel).
