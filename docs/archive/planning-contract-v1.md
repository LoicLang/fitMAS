---
summary: contrat produit et technique de la planification adaptative FitMAS
read_when:
  - lancer un refactor du planner
  - rendre la planification plus lisible dans l'app
  - ajouter des adaptations suite a un imprevu utilisateur
  - definir ce qui est ferme, adaptable ou projete
---

# FitMAS Planning Contract

## But

Faire de FitMAS un coach **ultra adaptatif mais stable**.

Le systeme ne doit pas recalculer tout le plan a chaque message.
Il doit :

- comprendre la contrainte reelle
- proteger l'intention d'entrainement
- modifier le moins possible
- expliquer clairement ce qui change

## Principe directeur

Le vrai plan n'est pas le calendrier.

Le vrai plan est compose de :

1. `block_intent` — ce qu'on construit sur 4 a 6 semaines
2. `week_mission` — ce qu'il faut sauver cette semaine
3. `session_policy` — ce qui est protege, compressible ou remplacable
4. `calendar_instantiation` — la meilleure organisation actuelle des seances

Le calendrier est une **instanciation datée**.
Il peut bouger.
L'intention ne doit pas bouger sans raison explicite.

## Horizons de verite

Le produit doit assumer des niveaux de certitude differents selon la distance temporelle.

- `Aujourd'hui` = exact, actionnable
- `Cette semaine` = engage, mais reconfigurable sous contraintes
- `J+8 a J+14` = probable
- `Bloc 4-6 semaines` = intention strategique, pas promesse seance par seance
- `Objectif long terme` = cap et jalons

Ces horizons doivent etre visibles dans l'app.

## Plan Confidence

Chaque seance et chaque horizon portent un niveau de confiance :

- `committed`
- `tentative`
- `projected`

Regles produit :

- `committed` = on ne bouge pas silencieusement
- `tentative` = on peut reequilibrer
- `projected` = lecture de direction seulement

## Week Mission

Chaque semaine doit exposer une mission explicite :

- objectif de semaine
- 2 a 3 seances cles
- critere de reussite dimanche
- risque principal a eviter
- seuil minimum acceptable si la semaine se degrade

La mission est plus importante que le placement exact des seances.

## Session Policy

Chaque seance datee doit porter une politique exploitable par le moteur :

- `role` : `key` | `support` | `recovery` | `optional`
- `plan_confidence`
- `move_window_hours`
- `minimum_effective_dose`
- `allowed_substitutions`
- `drop_cost`

Sans cette couche, on ne fait pas de vraie adaptation.
On fait seulement du drag-and-drop plus ou moins intelligent.

## Availability State

Les disponibilites ne doivent pas etre une question improvisee a chaque message.
Il faut un etat vivant minimal :

- creneaux preferes
- creneaux impossibles
- flexibilite par jour
- temps disponible indicatif
- equipement / modalites possibles
- source et fraicheur de l'info

Le moteur doit distinguer :

- `confirmed`
- `inferred`
- `sparse`

## Budget de changement

Un plan trop vivant devient anxiogene.

Le moteur doit donc porter une notion de stabilite :

- `change_budget_week`
- `adaptation_stability_penalty`

Principe :

**modifier le moins possible pour sauver le plus important**

Le moteur doit penaliser :

- les deplacements multiples
- les remplacements successifs
- les changements de mission
- les semaines qui changent tous les jours

## Niveaux d'adaptation

### Micro

Cas :

- indispo ponctuelle
- fatigue legere
- meteo
- petit conflit logistique

Droits :

- deplacer
- compresser
- substituer
- passer en `minimum effective dose`

Interdit :

- changer la mission de semaine
- recalibrer le bloc

### Meso

Cas :

- plusieurs seances touchees
- semaine pro fortement contrainte
- fatigue persistante
- accumulation d'adaptations micro

Droits :

- adoucir la mission
- reviser la semaine

Interdit :

- changer le block intent sans signal fort

### Macro

Cas :

- blessure
- maladie
- voyage lourd
- rupture forte de routine

Droits :

- recalibrer la nature du bloc
- reevaluer la trajectoire

## Reponse attendue a un imprevu

Avant toute mutation, un message utilisateur doit devenir un **event candidate** structure.

Exemple :

- `je ne suis pas dispo demain soir`
  - `UserIndication(kind="availability_constraint")`
  - puis `resolve_planning_window`
  - puis moteur de replan

Le LLM ne choisit jamais seul la seance future touchee.

Quand l'utilisateur dit :

`Merde, je ne peux pas ce soir`

FitMAS doit repondre a 4 questions :

1. Qu'est-ce qui change ?
2. Qu'est-ce qu'on protege ?
3. La mission de semaine reste-t-elle la meme ?
4. Quel est l'impact sur la trajectoire ?

Quand l'utilisateur dit :

`Je suis rince aujourd'hui`

FitMAS doit preferer :

1. version courte / minimum efficace
2. alleger franchement
3. seulement ensuite reviser la semaine

## Separation des responsabilites

### LLM

- comprend le message
- clarifie si besoin
- reformule la contrainte
- aide a classer des scenarios proches
- explique la decision

### Moteur deterministe / hybride

- genere les scenarios valides
- applique les garde-fous
- score les options
- limite l'instabilite
- choisit le niveau micro / meso / macro autorise

### Etat / persistance

- conserve la verite datee
- garde la trace des changements
- alimente l'app et Telegram

## Ordre d'implementation recommande

1. `WeekMission`
2. `SessionPolicy`
3. `AvailabilityState`
4. `PlanConfidence`
5. triggers `micro -> meso -> macro`
6. `replan_from_life_change`
7. `AdaptationDecision`
8. surfaces app :
   - planning contract
   - weekly mission
   - dernier changement
   - impact trajectoire

## Modules cibles

Premiere tranche :

- `planning_contract.py`
  - horizons
  - confidence
  - week mission
  - availability state
  - session policy
- read models app
  - `planning_contract`
  - `week_mission`
  - `availability_state`

Deuxieme tranche :

- `replan_from_life_change.py`
- `adaptation_decision.py`
- `adaptation_log.py`
- persistance `adaptation_events`
- read model app `last_adaptation`

Troisieme tranche :

- `trajectory.py`
- `progress_state.py`
- surfaces app plus profondes

## Regle produit a ne pas casser

FitMAS ne doit jamais donner l'impression :

- que le plan bouge au hasard
- que le futur lointain est ferme alors qu'il ne l'est pas
- qu'une belle explication remplace une mauvaise logique

Le luxe produit ici n'est pas :

`l'IA a tout recalculé`

Le luxe produit est :

`le systeme comprend ma vie, protege l'essentiel, et me dit franchement ce qu'il vient de changer`
