---
summary: evaluation des frameworks agentiques et de workflow pour FitMAS, avec recommandation pratique sur LangGraph et alternatives
read_when:
  - choisir les librairies d'orchestration IA
  - evaluer LangGraph
  - choisir entre framework agentique et logique maison
  - preparer le runtime de decision
---

# Agent Framework Evaluation V1

## Question

Quelles librairies ont un interet reel pour `FitMAS` ?

Le risque est classique:

- prendre un framework "multi-agent" parce que le produit parle d'agents
- puis decouvrir qu'il gere mal les vrais besoins:
  - webhooks
  - heartbeat durable
  - timers
  - source de verite
  - garde-fous
  - auditabilite

## Besoins reels de FitMAS

FitMAS a besoin de 4 couches distinctes:

1. orchestration systeme durable
2. source de verite de l'etat
3. runtime de decision IA
4. couche de voix / formulation

Un seul framework ne doit pas essayer de tout faire.

## Criteres de selection

Les librairies utiles pour FitMAS doivent aider sur:

- durabilite
- reprise apres panne
- timers et signaux
- etat explicite
- structured outputs
- observabilite
- human-in-the-loop
- faible ambiguite sur la source de verite

## Temporal

Verdict:

- oui, couche centrale recommandee

Pourquoi c'est fort pour FitMAS:

- workflows durables
- timers fiables
- signaux externes
- retries
- historique d'execution
- bon fit pour heartbeat et routines utilisateur

Ce que Temporal doit gerer:

- nightly planning
- weekly review
- reveils sur evenement
- cooldowns de messagerie
- attentes de feedback

Ce que Temporal ne doit pas gerer:

- le raisonnement LLM lui-meme

## LangGraph

Verdict:

- utile, mais pas comme colonne vertebrale du produit

LangGraph est interessant si:

- on veut un graphe de decision interne
- on a plusieurs etapes de raisonnement
- on veut persistence, memory ou interrupts au niveau IA
- on veut un sous-systeme sport / nutrition / adherence plus compose

LangGraph n'est pas le bon moteur principal pour:

- la source de verite
- les webhooks systeme
- le heartbeat global du produit
- les garanties de livraison et de reprise de jobs

Recommendation FitMAS:

- ne pas lancer le projet en "tout LangGraph"
- l'introduire seulement si le moteur IA a besoin d'un vrai graphe stateful

Bon usage de LangGraph chez FitMAS:

- a l'interieur d'une activite de planification
- a l'interieur d'un service IA dedie
- pour un sous-flux sport + nutrition + adherence

Mauvais usage:

- le laisser piloter toute la plateforme

## PydanticAI

Verdict:

- tres bon candidat pour V1 du runtime IA

Pourquoi:

- Python natif
- fort alignement avec les structured outputs
- bon fit pour outils, schemas et validations
- plus simple a garder lisible qu'un gros graphe trop tot

Bon usage:

- agent sport typé
- agent nutrition typé
- extracteur de feedback WhatsApp
- decideur local avec sorties valideses

Pourquoi c'est potentiellement meilleur que LangGraph au debut:

- moins de ceremonie
- meilleur controle des schemas
- plus facile a debug
- plus coherent avec notre principe "determinisme avant LLM"

## Logique maison

Verdict:

- indispensable pour une partie du systeme

Il faut garder maison:

- policies de messagerie
- garde-fous sante
- regles de cooldown
- regles de verification avant envoi
- modeles de donnees
- evolution du double numerique

Le framework ne doit jamais absorber ces regles critiques.

## Recommendation finale

Recommendation V1:

- Temporal pour l'orchestration durable
- Postgres pour l'etat
- FastAPI pour les APIs et webhooks
- service IA Python
- PydanticAI ou sorties Pydantic maison pour les agents specialises
- LangGraph plus tard, seulement si le moteur de decision devient vraiment graphe

## Architecture outillee conseillee

1. webhook ou sync event
2. persistence event en base
3. reveil workflow Temporal
4. lecture du double numerique
5. appel du service IA
6. service IA:
   - logique typée simple au debut
   - LangGraph possible plus tard pour sous-flux complexes
7. decision finale
8. persistence
9. message eventuel

## Quand introduire LangGraph

Seuil d'introduction raisonnable:

- quand un simple appel agent + outils ne suffit plus
- quand sport, nutrition et adherence ont de vraies dependances iteratives
- quand on veut un sous-systeme avec interrupts ou reprise interne

Avant ce seuil,
LangGraph ajoute souvent plus de complexite que de valeur.

## Recommandation 90 jours

### Sprint 1

- pas de LangGraph
- workflows durables
- schemas de donnees
- agents simples a sorties structurees

### Sprint 2

- service IA mieux structure
- prompts stables
- evaluation et journaling

### Sprint 3

- reevaluer LangGraph pour la planification hebdo ou l'arbitrage multi-specialistes

## Regle d'architecture

Le multi-agent doit etre une implementation interne.
Pas une religion d'architecture.

FitMAS gagne si:

- le systeme est fiable
- le plan est juste
- les messages sont pertinents

Pas si:

- le diagramme des agents est impressionnant
