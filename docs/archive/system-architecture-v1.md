---
summary: architecture logique v1 du produit FitMAS, de l'orchestrateur aux agents et au double numerique
read_when:
  - penser l'architecture du systeme
  - definir les domaines back-end
  - modeliser les agents et l'orchestrateur
  - preparer l'implementation technique
---

# System Architecture V1

## Objectif

Definir l'architecture logique du produit `FitMAS`.

Ce document ne fixe pas encore une stack technique finale.
Il fixe les responsabilites fonctionnelles du systeme.

## Vue d'ensemble

Le systeme V1 doit reposer sur 7 blocs:

1. identite utilisateur
2. integrations et collecte de donnees
3. double numerique
4. agents specialises
5. orchestrateur central
6. planification et adaptations
7. couche d'experience app + WhatsApp

## 1. Identite utilisateur

Responsabilites:

- compte utilisateur
- consentements
- integrations connectees
- preferences de communication

Ce bloc porte l'identite, pas l'intelligence comportementale.

## 2. Integrations et collecte de donnees

Sources V1 prioritaires:

- Apple Health / Sante
- Strava
- calendrier
- WhatsApp comme canal de sortie et de feedback

Responsabilites:

- importer les donnees utiles
- normaliser les formats
- horodater les evenements
- fournir un historique exploitable par l'orchestrateur

## 3. Double numerique

Le double numerique est la representation vivante de l'utilisateur.

Ce n'est pas un simple profil statique.
C'est un modele evolutif combine:

- donnees explicites
- donnees observees
- apprentissages derives

### Contenu minimum V1

- objectifs
- contraintes de planning
- preferences sport
- preferences nutrition
- gouts
- niveau actuel
- historique recent
- style de motivation
- tolerance a la charge
- patterns d'adherence
- regles non negociables

### Principes

- versionne
- explicable
- modifiable par feedback utilisateur
- enrichi apres chaque cycle utile

## 4. Agents specialises

V1 peut reposer sur un petit noyau:

- agent sport
- agent nutrition
- agent adherence / comportement

Chaque agent:

- lit le double numerique
- lit les donnees recentes
- propose des recommandations dans son domaine
- ne prend pas la decision finale seul

## 5. Orchestrateur central

L'orchestrateur est le cerveau arbitre du systeme.

Responsabilites:

- fusionner les signaux
- arbitrer les conflits entre agents
- appliquer les garde-fous
- decider s'il faut adapter le plan
- decider s'il faut solliciter l'utilisateur

### Regle critique

L'utilisateur ne doit jamais percevoir des agents qui se contredisent.
Une seule decision finale doit etre exposee.

## 6. Planification et adaptations

Ce bloc produit les livrables visibles:

- plan hebdomadaire
- plan du jour
- adaptations ponctuelles

Il doit gerer deux dimensions:

- sport
- nutrition

### Types d'adaptation V1

- ordre des seances
- timing
- volume modere
- repos / deload leger
- collations / timing repas
- ajustements fins de macros

### Adaptations sous validation

- changement d'objectif
- forte variation calorique
- suppression d'une seance cle
- changement majeur de strategie
- signaux de sante / blessure

## 7. Couche d'experience

Le produit s'exprime dans deux surfaces:

### App

Role:

- setup
- consultation du plan
- lecture du jour
- visibilite sur les changements
- edition du double numerique

### WhatsApp

Role:

- proactivite
- questions contextuelles
- check-ins utiles
- feedback ponctuel
- notification d'adaptation

## Boucle logique quotidienne

Sequence cible:

1. ingestion de donnees
2. normalisation
3. mise a jour du contexte utilisateur
4. lecture du double numerique
5. propositions des agents
6. arbitrage de l'orchestrateur
7. mise a jour du plan
8. envoi eventuel d'un message WhatsApp
9. collecte eventuelle de feedback
10. enrichissement du double numerique

## Memoire et apprentissage

Le systeme doit distinguer:

- faits observes
- preferences declarees
- hypotheses inferrees
- decisions prises
- feedback utilisateur

Cette separation est critique pour ne pas confondre:

- ce qui est vrai
- ce qui est suppose
- ce qui a deja ete invalide

## Garde-fous systeme

L'orchestrateur doit appliquer:

- limites wellness/performance
- limites d'autonomie
- prevention des changements trop frequents
- prevention des messages inutiles
- besoin d'explicabilite minimale

## Qualites produit a proteger

L'architecture doit permettre:

- personnalisation profonde
- proactivite utile
- faible friction
- coherence des decisions
- confiance utilisateur

## Evolution probable

Phase ulterieure possible:

- plus d'agents specialises
- plus de verticales sportives
- plus de signaux comportementaux
- plus d'autonomie dans les ajustements

Mais en V1, la priorite est simple:

- une bonne boucle
- un bon arbitrage
- un bon ressenti utilisateur
