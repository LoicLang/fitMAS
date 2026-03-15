---
summary: arborescence de navigation iOS v1 de FitMAS et logique de circulation entre onboarding, today, plan et profil
read_when:
  - designer la navigation mobile
  - structurer l'application iOS
  - prioriser les surfaces principales
  - preparer l'architecture front mobile
---

# iOS Navigation V1

## Principe

La navigation V1 doit servir une idee simple:

- peu d'ecrans
- peu de branches
- acces rapide a l'essentiel

FitMAS ne doit pas paraitre dense.
Il doit paraitre pilote.

## Structure generale

Je recommande une structure a 4 onglets maximum apres onboarding:

1. Today
2. Plan
3. Profil
4. Settings leger ou aucun onglet dedie si le profil suffit

Recommendation V1:

- rester a 3 onglets visibles

## Flow de premier lancement

Ordre recommande:

1. welcome / promesse
2. sign in with Apple
3. onboarding multi-etapes
4. recap FitMAS
5. generation du premier plan
6. arrivee sur Today

## Tab 1. Today

Role:

- point d'entree quotidien
- ecran par defaut a chaque ouverture

Actions possibles:

- voir la decision du jour
- comprendre ce qui a change
- envoyer un feedback simple
- ouvrir le detail du jour

## Tab 2. Plan

Role:

- voir la semaine
- comprendre la logique globale

Actions possibles:

- naviguer dans les jours
- voir les jours flexibles
- voir les points nutrition utiles
- ouvrir le detail d'un jour

## Tab 3. Profil

Role:

- voir ce que FitMAS sait
- corriger le double numerique
- gerer les integrations et preferences

Sections:

- objectifs
- contraintes
- preferences
- style de coaching
- integrations

## Flows secondaires

### Detail du jour

Depuis Today ou Plan:

- detail seance
- detail focus nutrition
- raison de la decision

### Update preference

Depuis Profil:

- modifier une preference
- modifier une contrainte
- changer le ton

### Integration flow

Depuis onboarding ou profil:

- connecter / reconnecter Health
- connecter Strava
- connecter calendrier
- lier WhatsApp

## Ce qu'on evite en V1

- navigation profonde
- sous-menus complexes
- chat in-app
- analytics detailles comme ecran principal

## Regle directrice

Si une information n'aide pas:

- a agir aujourd'hui
- a comprendre la semaine
- ou a corriger le modele

alors elle ne doit probablement pas avoir une surface de premier niveau.
