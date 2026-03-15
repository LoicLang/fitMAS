---
summary: cadrage produit v1 de FitMAS, wedge initial, promesse et garde-fous
read_when:
  - definir le MVP
  - choisir le premier segment utilisateur
  - cadrer la boucle produit quotidienne
  - aligner produit et architecture
---

# Product V1 Cadrage

## Positionnement

`FitMAS` n'est pas une application fitness classique.

Le produit vise a devenir une equipe IA proactive de performance:

- coach sport
- coach nutrition
- autres specialistes a terme
- orchestres par un arbitre central
- personnalises par un double numerique evolutif

La promesse centrale n'est pas seulement le conseil.
La promesse est la delegation intelligente:
l'utilisateur ne doit plus porter seul la charge mentale de planification et d'ajustement.

## Promesse produit

Formulation de travail:

`FitMAS aide des pratiquants motives a mieux performer avec une equipe IA qui ajuste sport et nutrition selon leur vraie vie.`

Promesse fonctionnelle:

- mieux performer
- moins reflechir / moins planifier
- avoir le sentiment d'etre suivi par une equipe premium

## ICP V1 recommande

Le V1 doit commencer par un seul wedge.

Recommendation:

- pratiquants endurance motives
- deja engages dans une pratique reelle
- ouverts a un setup initial premium
- sensibles a la personnalisation et aux integrations de donnees

Pourquoi endurance en premier:

- meilleur fit avec les integrations initiales
- donnees plus riches via Apple Health et Strava
- progression plus facile a mesurer
- adaptation quotidienne plus lisible
- boucle proactive plus naturelle

## Pourquoi pas endurance + muscu en meme temps

Les deux sont possibles a terme.
Les deux ne sont pas souhaitables en V1.

Raison:

- deux logiques de programmation distinctes
- deux systemes de feedback differents
- deux niveaux de qualite data differents
- risque de produire une experience moyenne sur les deux segments

Decision de cadrage:

- V1: endurance
- V2 possible: extension musculation / street lifting / hybrid training

Le moteur produit peut etre pense des le depart pour supporter plusieurs domaines,
mais l'experience, les heuristiques et la promesse doivent etre verticalisees en V1.

## Job To Be Done principal

Formulation retenue:

`Je veux une equipe qui ajuste tout pour moi selon ma vraie vie.`

Traduction utilisateur:

- je veux mieux performer
- je ne veux pas passer mon temps a planifier
- je veux un systeme qui me comprend et s'adapte

## Experience produit V1

### Role de l'app

L'application est le coeur du systeme pour:

- onboarding et configuration du double numerique
- visualisation du plan sport et nutrition
- consultation du plan du jour
- lecture des adaptations et de leur rationale

Il n'y a pas de chat in-app en V1.

### Role de WhatsApp

WhatsApp est le canal proactif:

- questions contextuelles
- check-ins ponctuels
- notifications d'adaptation utiles
- recueil de feedback apres certaines seances

## Boucle quotidienne cible

Boucle de travail cible V1:

1. les donnees sont importees automatiquement
2. l'orchestrateur reevalue le contexte utilisateur
3. le plan du jour et le plan hebdo peuvent etre ajustes
4. WhatsApp est utilise seulement si une interaction utile est necessaire
5. le feedback utilisateur affine le double numerique

## Double numerique V1

Le double numerique doit contenir au minimum:

- objectifs
- contraintes de planning
- preferences sportives
- preferences alimentaires
- gouts
- niveau actuel
- historique recent
- style de motivation
- tolerance a la charge
- patterns d'adherence
- regles personnelles non negociables

Principe produit:

- onboarding initial
- enrichissement par donnees reelles
- enrichissement par feedback utilisateur
- enrichissement progressif par inference agentique

Le feedback explicite utilisateur est critique:
le systeme doit apprendre ce qui est vrai, pas seulement ce qui est plausible.

## Agents et orchestration

Le multi-agent est un choix de systeme, pas une complexite exposee a l'utilisateur.

Principe V1:

- plusieurs agents specialises peuvent contribuer
- un orchestrateur central arbitre toujours
- l'utilisateur percoit une equipe coherente, pas un debat entre agents

## Livrables concrets V1

L'equipe IA doit produire:

- un plan hebdomadaire adaptatif
- un plan du jour
- une replanification automatique en cas d'imprevu
- une dimension sport
- une dimension nutrition

## Frontiere d'autonomie V1

Peut etre ajuste sans validation humaine:

- ordre des seances
- timing des seances
- ajustements moderes de volume
- repos ou deload legers
- collations et timing alimentaire
- ajustements fins de macros
- niveau de challenge dans les messages

Doit rester sous validation explicite:

- changement d'objectif principal
- forte variation calorique
- suppression d'une seance cle
- bascule majeure de strategie nutritionnelle
- situations de sante ou blessure

## Integrations prioritaires V1

Integrations prioritaires:

- Apple Health / Sante
- Strava
- WhatsApp
- calendrier

## Signal de valeur precoce

Au bout des 14 premiers jours, le produit doit deja creer:

- de la confiance dans le systeme
- une reduction de l'effort de planification mentale

Ces signaux sont prioritaires avant toute promesse de transformation physique forte.

## Garde-fous

Positionnement V1:

- focus wellness et performance
- pas de conseil medical
- pas de prise en charge pathologique
- pas de gestion clinique des blessures

## Pricing de travail

Hypothese de travail:

- beta ou apprentissage: prix plus bas possible
- lancement credibile: abonnement premium superieur a une app fitness grand public

Point d'attention:

Le pricing ne doit pas etre structure "par nombre d'agents".
La valeur percue doit etre packagee par niveau de service et profondeur d'accompagnement.

## Roadmap de principe

### Phase 1

- endurance seulement
- double numerique V1
- plan sport + nutrition
- plan du jour
- replanification simple
- boucle proactive WhatsApp

### Phase 2

- enrichissement du double numerique
- meilleure personnalisation comportementale
- autonomie plus fine dans les ajustements
- extension progressive a d'autres sous-profils

### Phase 3

- ouverture possible a musculation / hybrid / autres verticales
- equipe multi-agent plus riche
- personnalisation de plus en plus invisible et proactive
