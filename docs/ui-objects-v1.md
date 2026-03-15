---
summary: objets UI principaux v1 par ecran pour rendre FitMAS clair, premium et pilote au quotidien
read_when:
  - designer les composants
  - preparer un prototype iOS
  - traduire les specs produit en UI concrete
  - aligner front et produit
---

# UI Objects V1

## Principe

Les objets UI doivent porter la logique produit.
Pas juste afficher de la data.

Chaque composant doit repondre a une question utilisateur.

## Today

### TodayDecisionCard

Repond a:

- que fais-je aujourd'hui ?

Contenu:

- titre seance
- objectif
- duree / intensite
- niveau de priorite

### TodayNutritionCard

Repond a:

- quel est le point nutrition utile aujourd'hui ?

Contenu:

- focus du jour
- timing utile
- note courte

### PlanChangeCard

Repond a:

- qu'est-ce qui a change ?

Contenu:

- changement
- raison
- impact attendu

### WatchlistCard

Repond a:

- qu'est-ce que FitMAS surveille ?

Contenu:

- 1 a 3 points de surveillance

### QuickFeedbackCard

Repond a:

- est-ce realiste / rien a signaler ?

Contenu:

- CTA simple

## Plan

### WeeklyIntentHeader

Repond a:

- quel est le sens de cette semaine ?

### DayPlanCard

Repond a:

- que porte chaque jour ?

Contenu:

- seance
- niveau de charge
- flexibilite
- note nutrition si utile

### WeeklyAdjustmentNote

Repond a:

- quels arbitrages ont ete faits ?

## Profil

### GoalCard

### ConstraintsCard

### PreferencesCard

### CoachingStyleCard

### IntegrationsStatusCard

### WhatFitmasUnderstandsCard

But:

- rendre visible ce que le systeme croit savoir

## Onboarding

### StepIntroCard

Explique:

- pourquoi on pose ces questions

### ChoiceGrid

Pour:

- objectifs
- ton
- styles preferes

### ConstraintPicker

Pour:

- jours disponibles
- jours a eviter
- creneaux

### RecapCard

Pour:

- montrer ce que FitMAS a compris

## Regle de design produit

Chaque objet doit faire au moins une des trois choses:

- orienter l'action
- expliquer une decision
- renforcer la confiance
