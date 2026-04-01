---
summary: contrat des indications utilisateur FitMAS, pipeline event candidate -> grounding -> mutation
read_when:
  - modifier api_messages.py
  - ajouter un nouveau type de signal utilisateur
  - traiter une indisponibilite future, un signal sante ou un update d'execution
  - brancher un tool ou module de resolution planning
---

# User Indications

## But

Traiter un message utilisateur comme un **event candidate**.

Pas comme :
- une commande brute
- une mutation directe
- une phrase que le LLM improvise seul

Le bon split :
1. interpreter
2. grounder
3. decider
4. expliquer

## Principe directeur

Une indication utilisateur n'est pas une instruction directe.

Exemples :
- `je ne suis pas dispo demain soir`
- `j'ai mal a l'epaule quand je nage`
- `j'ai couru 40 min`

Avant toute mutation, FitMAS doit produire un objet structure.

Règle de parsing :

- tout message user non trivial doit passer d'abord par l'interpréteur structuré
- les regex fallback restent un secours, pas le portier principal
- le backend valide ensuite, grounde, persiste et mute

## Types MVP

### `availability_constraint`

Exemples :
- indispo ponctuelle
- voyage
- creneau impossible

Role :
- resoudre une fenetre reelle du planning
- puis replanifier si une seule seance cible est claire

### `health_signal`

Exemples :
- douleur
- gene
- fatigue locale

Role :
- normaliser un signal sante avant la conversation libre
- ecrire un fait sante propre
- lancer une adaptation protective si besoin

### `execution_update`

Exemples :
- activite faite
- correction d'execution

Role :
- reconciler le reel
- alimenter les claims d'activite / memoire courte

Etat MVP :
- interprete
- mais la voie principale reste encore `activity_claims.py`

## Pipeline

### 1. `interpret_user_indication`

Module :
- `backend/src/fitmas/user_indication_llm.py`

Sortie :
- `UserIndication`

Regles :
- LLM en nominal
- fallback minimal seulement pour les cas triviaux
- aucune mutation
- aucune ecriture DB directe

### 2. `resolve_planning_window`

Module :
- `backend/src/fitmas/planning_window_resolution.py`

Role :
- ancrer une contrainte temporelle contre le vrai planning
- trouver une seance candidate
- signaler s'il faut clarifier

Regles :
- lecture bornée
- pas de mutation
- peut aussi etre expose en runtime tool read-only

### 3. `generate / choose valid actions`

Modules :
- `backend/src/fitmas/replan_from_life_change.py`
- `backend/src/fitmas/adaptation.py`

Role :
- produire des actions autorisees
- choisir la moins destructrice

Regles :
- moteur backend
- garde-fous planning
- jamais de write direct par le LLM

### 4. `explain`

Modules :
- `backend/src/fitmas/llm.py`
- `backend/src/fitmas/calibration_llm.py`
- `backend/src/fitmas/adaptation.py`

Role :
- garder une voix naturelle
- expliquer ce qui change et pourquoi

## Objets clefs

### `UserIndication`

Porte :
- `kind`
- `confidence`
- `scope`
- `time_reference`
- `polarity`
- champs sante ou execution si utiles

### `PlanningWindowResolution`

Porte :
- fenetre cible
- liste de seances candidates
- `matched_session_id`
- `needs_clarification`

## Regles d'ecriture

- le LLM n'ecrit jamais directement en memoire
- les indications sante ecrivent d'abord un fait normalise
- les indispos futures ne touchent pas la memoire durable
- les mutations passent toujours par les orchestrateurs

## Implémentation actuelle

### Conversation

Dans `api_messages.py` :

1. on interprete le message en `UserIndication`
   - en pratique, presque tous les messages non triviaux passent par le parseur structuré
   - le parseur voit aussi le dernier message coach utile quand une clarification est en cours
2. si c'est un `health_signal` fort :
   - on ecrit un fait sante
   - on tente une adaptation protective
   - si l'analyse adaptation ne sort rien de propre, un fallback conservateur protege au moins la prochaine seance du geste signale
   - si elle s'applique, la reponse sante devient la reponse principale
3. sinon, si c'est une `availability_constraint` future :
   - on resout la fenetre planning
   - on tente un replan borne via `maybe_replan_from_user_indication`
   - si aucune seance ne matche vraiment cette fenetre, on repond honnetement qu'il n'y a rien a bouger
4. sinon, on laisse le pipeline conversation normal continuer

Comportements importants :
- `voyage`, `deplacement`, `je bouge` sont traites comme des `availability_constraint`
- un `demain soir` sans seance cible ne doit jamais inventer une mutation sur un autre jour
- `douleur epaule + natation` force une adaptation protective hors natation, meme si le LLM propose juste une version plus douce de nage
- une reponse courte a une clarification d'execution (`oui`, `non`, `j'ai rien fait`, `je suis malade`) doit etre interpretee dans le contexte de la question precedente
- une clarification d'execution deja resolue ne doit pas etre repetee verbatim au tour suivant

### Runtime tools

`resolve_planning_window` existe aussi comme tool read-only.

But :
- reutilisable plus tard par le chat outille
- meme resolution metier pour API + tools

## Anti-patterns

- laisser le LLM choisir seul la seance du futur sans grounding
- parser toute la langue naturelle avec des regex
- muter le plan directement depuis une extraction LLM
- ecrire un signal utilisateur flou en memoire durable
- retraiter un meme signal sante une deuxieme fois apres la reponse user
