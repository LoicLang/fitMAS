---
summary: vérité de conversation, sources de contexte fiables, trous actuels et plan d'implémentation du grounding Telegram
read_when:
  - corriger un bug de contexte conversationnel
  - modifier api_messages.py
  - modifier heartbeat.py ou signals.py
  - brancher des tools de lecture pour le coach Telegram
---

# Conversation Grounding

## But

Rendre le coach Telegram factuellement fiable quand il parle :
- de ce qui a ete fait
- de ce qui etait prevu
- de aujourd'hui / demain / hier
- d'une correction apportee par l'utilisateur

Le sujet n'est pas d'ajouter "plus de contexte" au LLM.
Le sujet est de lui donner une verite plus structuree et plus parcimonieuse.

## Probleme produit actuel

Symptomes observes :
- le coach peut dire "zero seance" alors qu'une activite hors plan a bien eu lieu
- le coach peut reutiliser la duree planifiee comme si elle etait la duree reelle
- le coach peut mal resoudre "aujourd'hui", "demain" ou "ce soir" apres une correction utilisateur

Ca casse la credibilite au pire endroit : la conversation naturelle.

## Sources de verite actuelles en base

### 1. `Activity`

Source la plus forte sur le reel execute.

Utilisable pour :
- sport reel
- duree reelle
- distance, FC, vitesse, TSS
- date de realisation
- lien explicite vers `scheduled_session_id` si connu

Limites actuelles :
- toute activite n'est pas forcement rattachee a une seance
- une activite hors plan existe en DB mais n'est pas toujours bien interpretee par le coach

### 2. `ScheduledSession`

Source la plus forte sur le plan date reel.

Utilisable pour :
- seance prevue aujourd'hui
- sport attendu
- duree cible
- statut `planned/done/skipped/adapted`
- timeline visible

Limites actuelles :
- le statut peut rester centre sur la seance prevue, pas sur l'activite reelle du jour
- une activite hors plan ne doit pas etre lue comme "rien fait"

### 3. `CoachMessage`

Source sur le contexte conversationnel recent.

Utilisable pour :
- derniere consigne du coach
- derniere correction utilisateur
- chaine de referents (`ce soir`, `demain`, `30 min`, etc.)

Limites actuelles :
- historique injecte trop brut
- pas de structuration des corrections recentes

### 4. `UserFact`

Source sur les contraintes stables et semi-stables.

Utilisable pour :
- disponibilites
- contraintes
- patterns
- preferences

Limites actuelles :
- pas fait pour stocker chaque evenement d'execution a chaud
- ne doit pas devenir un journal d'activite bis

Etat mis a jour :
- `UserFact` porte maintenant aussi une sémantique mémoire explicite :
  - `urgency`
  - `ttl`
  - `affects`
  - `expires_at`
- le système sait donc mieux distinguer :
  - info durable
  - info temporaire
  - info prioritaire pour la conversation

### 5. `WeeklyPlan` / `DayPlan`

Source legacy encore utile pour :
- intention de semaine
- notes coach
- watch items

Limites actuelles :
- ne doit plus etre la verite principale pour juger ce qui a vraiment ete fait aujourd'hui
- plusieurs signaux et prompts legacy s'appuient encore trop dessus

## Hierarchie de verite recommandee

Ordre strict pour le coach :

1. activite reelle persistée (`Activity`)
2. declaration explicite utilisateur dans le message courant
3. correction explicite recente dans la conversation
4. seance planifiee (`ScheduledSession`)
5. heuristique faible

Regle :
- le coach ne doit jamais presenter 4 ou 5 comme un fait si 1, 2 ou 3 disent autre chose

## Ce que le LLM doit recevoir

Pas :
- tout l'historique brut
- toute la DB brute
- tout le plan brut

Oui :
- `temporal_context`
- `today_execution_context`
- `recent_activity_context`
- `relevant_timeline_context`
- `recent_user_corrections`

## Outils domaine a ajouter

### `execution_context.py`

Role :
- resumer ce qui etait prevu et ce qui a ete reellement fait
- distinguer `planned_done_as_expected`, `planned_done_modified`, `off_plan_done`, `planned_pending`, etc.

Etat :
- pose
- pur
- teste

Consommateurs cibles :
- `api_messages.py`
- `heartbeat.py`
- `signals.py`

### `temporal_resolver.py`

Role :
- resoudre `aujourd'hui`, `demain`, `hier`, `ce soir`, `demain matin`
- s'appuyer sur timezone user + heure locale exacte

Etat :
- pose
- pur
- teste

Consommateurs cibles :
- `api_messages.py`
- `llm.py`
- futurs extracteurs de claims activite

### `activity_claims.py`

Role :
- extraire de maniere deterministe ou semi-structuree :
  - sport mentionne
  - duree mentionnee
  - date relative ou absolue
  - certitude

Exemples :
- "j'ai couru aujourd'hui"
- "j'ai fait 30 min"
- "non c'etait hier"
- "je n'ai pas nage, j'ai couru"

Etat :
- pose
- fusion simple des claims recents supportee
- persistance deterministe d'un claim fusionne en `UserFact(category="execution")` quand le message courant porte une declaration d'activite
- teste

Regle :
- on persiste seulement si le message courant contient bien un claim
- on persiste la version fusionnee avec le contexte recent pour capter `j'ai fait 30 min` apres `j'ai couru aujourd'hui`
- on ne persiste pas si une vraie `Activity` couvre deja ce claim
- TTL courte (`immediate`) pour ne pas transformer `UserFact` en faux journal d'activite

### `conversation_context.py`

Role :
- assembler pour le LLM le minimum utile :
  - activite du jour
  - seance prevue du jour
  - delta prevu vs reel
  - dernieres corrections explicites

## Trous actuels

### Trou 1 — lecture trop faible du reel execute

Le coach peut encore raisonner principalement sur `DayPlan` / `completion_status`.

Effet :
- "zero seance" alors qu'une activite hors plan existe

### Trou 2 — pas de statut d'execution assez fin

Il manque un statut conversationnel explicite du genre :
- `planned_done_as_expected`
- `planned_done_modified`
- `off_plan_done`
- `planned_missed`
- `user_claimed_unlogged_activity`

### Trou 3 — pas de resolution de referent conversationnel

Le systeme ne garde pas assez proprement :
- a quoi renvoie `30 min`
- si on parle de la seance faite aujourd'hui ou de celle de demain

### Trou 4 — pas de tool de verification cible pour le LLM

Le LLM recoit un prompt, pas une boite a outils de lecture.

Effet :
- il comble avec le plan au lieu de verifier le reel

### Trou 5 — declaration user non durable

Sans persistance courte, le systeme oublie trop vite :
- une activite declaree dans le chat mais pas encore loggee
- une correction de duree immediate

Etat :
- corrige pour les claims activite recentes
- reste a voir si d'autres claims temporels meritent la meme approche

## Plan recommande

### Etape A — grounding sur la DB actuelle

Objectif :
- corriger la majorite des erreurs sans changer massivement le schema

Ordre :
1. `execution_context.py`
2. `temporal_resolver.py`
3. `activity_claims.py`
4. integration `api_messages.py`
5. integration `heartbeat.py`
6. integration `signals.py`

### Etape B — enrichissements de modele si necessaire

Seulement si A ne suffit pas.

Possibles ajouts :
- `user_claimed_activity`
- `execution_event`
- statut persistant `off_plan_done`

### Etat courant

En place :
- `api_messages.py` persiste maintenant un claim d'activite fusionne en `UserFact` de categorie `execution`
- cette memoire courte alimente les prochains tours de conversation et le heartbeat
- les claims ne doublonnent pas une `Activity` deja loggee le meme jour

## Regles non negociables

- le coach ne dit jamais "rien fait" si une activite reelle existe dans la fenetre pertinente
- une correction utilisateur immediate prime sur la duree planifiee
- `aujourd'hui` et `demain` doivent toujours etre resolus depuis le temps local exact
- un prompt ne remplace pas un tool de verite

## Etat actuel

Deja pose :
- temps local fiable via `time_context.py`
- `ScheduledSession` datees
- `Activity` persistées
- pipeline planning V2 pour l'etat athlete/fitness/readiness/decision
- `execution_context.py` pour resumer proprement prevu vs reel sur la journee
- `temporal_resolver.py` pour resoudre les references relatives
- `activity_claims.py` pour extraire et merger les declarations d'activite recentes
- `api_messages.py` branche maintenant execution + temps + claims dans le prompt LLM
- `signals.py` et `heartbeat.py` lisent mieux les activites reelles hors plan
- `fact_memory.py` + `UserFact` enrichi pour distinguer info durable / temporaire / prioritaire

Manque encore :
- vraie couche shared de grounding conversationnel
- integration plus fine des corrections conversationnelles
- persistance eventuelle d'un `user_claimed_activity` si la DB actuelle ne suffit pas
