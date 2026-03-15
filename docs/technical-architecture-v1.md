---
summary: architecture technique v1 recommandee pour FitMAS, stack, services et choix structurants
read_when:
  - choisir la stack
  - demarrer le backend
  - demarrer l'application mobile
  - aligner l'implementation avec les integrations reelles
---

# Technical Architecture V1

## Conclusion executive

La meilleure architecture V1 pour `FitMAS` n'est pas:

- une app web classique
- un simple chatbot WhatsApp
- un multi-agent qui improvise tout

La meilleure architecture V1 est:

- une app iPhone en premier
- un backend event-driven
- un orchestrateur central durable
- quelques agents specialises derriere
- un heartbeat hybride: evenements + reveils planifies

## Choix structurants

### 1. iOS first

Recommendation forte:

- V1 mobile: iPhone d'abord
- pas de vrai Android en premiere iteration

Pourquoi:

- Apple Health est une integration prioritaire
- HealthKit se lit depuis l'app, pas depuis un simple backend
- la permission et la collecte sont fortement liees au device
- l'experience premium de setup est plus naturelle en mobile

### 2. Un seul cerveau produit

Le systeme peut avoir plusieurs agents,
mais il ne doit avoir qu'un seul arbitre.

Decision:

- agent sport
- agent nutrition
- agent adherence / comportement
- orchestrateur central qui tranche

### 3. Determinisme avant LLM

Le LLM ne doit pas controler:

- la planification des jobs
- les garde-fous de sante
- les permissions
- la frequence de messagerie
- les cooldowns
- la persistance d'etat

Le LLM intervient pour:

- proposer
- arbitrer des nuances
- formuler
- adapter le ton
- extraire du feedback

## Stack recommandee V1

## Client mobile

Recommendation:

- SwiftUI pour l'app iOS

Pourquoi:

- meilleur acces natif a HealthKit
- meilleur controle des permissions
- meilleur support du background delivery
- moins de risque qu'un wrapper cross-platform sur une brique critique

Fonctions du client:

- onboarding
- configuration du double numerique
- affichage du plan du jour et du plan hebdo
- edition des preferences et contraintes
- lecture HealthKit
- sync vers backend

## Backend API

Recommendation:

- Python + FastAPI

Pourquoi:

- cohérent avec le repo actuel
- bon fit pour APIs, workers, outils ML, orchestration
- iteration rapide

Responsabilites:

- auth
- APIs app
- webhooks Strava et WhatsApp
- ingestion des events
- lecture / ecriture du double numerique
- lecture / ecriture des plans

## Base de donnees

Recommendation:

- PostgreSQL

Pourquoi:

- source de verite transactionnelle
- bon support JSONB pour l'etat evolutif du double numerique
- bonne base pour audit log, events, plans, decisions

Ne pas utiliser SQLite en production pour ce produit.

## Workflow engine

Recommendation forte:

- Temporal

Pourquoi:

- FitMAS a besoin de reveils, timers, retries, signaux et workflows durables
- le produit depend de boucles longues par utilisateur
- les jobs critiques ne doivent pas se perdre si un worker redemarre

Temporal est un bon fit pour:

- nightly refresh
- attente d'un event utilisateur
- relance apres un delai
- replanification differree
- heartbeat par utilisateur

## Queue / async

Si Temporal est adopte serieusement,
eviter de doubler inutilement avec une deuxieme couche d'orchestration riche.

Le pattern recommande:

- Temporal pour les workflows
- activites workers pour les traitements
- taches legeres eventuelles pour les jobs non critiques

## Messagerie

Recommendation V1:

- WhatsApp Business Platform / Cloud API

Responsabilites:

- messages proactifs
- feedback utilisateur
- confirmations eventuelles
- delivery/status webhooks

## Fichiers et objets

Recommendation:

- stockage objet simple pour assets utiles plus tard

Pas critique en V1 si l'app ne gere pas encore de media lourd.

## Service IA

Recommendation:

- service interne dedie aux appels LLM

Responsabilites:

- prompt routing
- model routing
- journaling des decisions
- controle de cout
- gestion de retries

## Frameworks agentiques

Recommendation:

- ne pas faire de framework agentique la colonne vertebrale du systeme

Position de travail:

- Temporal pour l'orchestration systeme
- Postgres pour la source de verite
- service IA pour les decisions et formulations
- LangGraph eventuellement comme sous-couche locale de raisonnement

Regle critique:

si LangGraph est utilise plus tard,
il doit vivre a l'interieur d'une activite ou d'un service IA,
pas remplacer le workflow engine du produit.

## Schema de services

V1 peut etre pense avec 5 blocs deployables:

1. app iOS
2. API backend
3. workflow workers
4. base PostgreSQL
5. provider WhatsApp / integrations externes

## Flux technique cible

### Flux HealthKit

1. l'app iOS recoit ou relit les donnees HealthKit
2. elle transforme en evenements normalises
3. elle pousse au backend
4. le backend persiste les raw events
5. un workflow utilisateur est reveille

### Flux Strava

1. Strava envoie un webhook
2. le backend accuse reception vite
3. le backend fetch les donnees utiles de maniere asynchrone
4. les evenements sont normalises
5. le workflow utilisateur est reveille

### Flux WhatsApp

1. WhatsApp envoie message ou statut via webhook
2. le backend persiste
3. un extracteur structure le feedback
4. le workflow utilisateur est reveille si utile

### Flux planning

1. le workflow nocturne se reveille
2. il lit les nouvelles donnees
3. il met a jour le double numerique
4. il appelle les agents necessaires
5. l'orchestrateur arbitre
6. le plan du jour et / ou le plan hebdo sont mis a jour
7. un message n'est envoye que si la policy le justifie

## Pourquoi pas "tout dans le prompt"

Mauvaise approche:

- envoyer tout l'historique
- demander au modele de se souvenir
- demander au modele quand ecrire
- demander au modele de s'auto-reguler

Bonne approche:

- etat explicite en base
- events explicites
- policies explicites
- heartbeat explicite
- LLM comme moteur d'analyse et de formulation

## Contraintes reelles des integrations

### Apple Health

Implication produit:

- la lecture passe par une app ayant les bonnes permissions
- les autorisations sont granuleuses
- le produit doit tres bien gerer les cas ou certaines donnees sont absentes

### Strava

Implication produit:

- webhooks indispensables
- les limites API imposent d'eviter le polling
- le mode initial de l'app Strava est tres limite tant que l'app n'est pas revue

### WhatsApp

Implication produit:

- la messagerie proactive doit etre geree proprement
- il faut une vraie policy anti-spam
- la couche messagerie doit etre un canal, pas la source de verite

## Recommendation d'implementation

Ordre conseille:

1. modele de donnees
2. API backend
3. app iOS onboarding + sync
4. ingestion Strava
5. orchestrateur simple
6. heartbeat
7. WhatsApp proactif

## Non-objectifs V1

Ne pas faire tout de suite:

- Android natif complet
- chat in-app
- vrai systeme temps reel complexe
- marketplace de coachs
- orchestration libre entre de nombreux agents
