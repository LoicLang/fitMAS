---
summary: strategie de canal messagerie v1 pour FitMAS, contraintes de WhatsApp et limites des alternatives standard
read_when:
  - choisir le canal conversationnel principal
  - integrer WhatsApp
  - evaluer Messages for Business
  - definir la proactivite du produit
---

# Messaging Channel Strategy V1

## Decision recommandee

Pour `FitMAS`, le bon choix V1 est:

- app iOS comme coeur produit
- WhatsApp comme canal conversationnel principal
- abstraction interne `messaging provider` pour ne pas verrouiller le systeme trop tot

## Pourquoi WhatsApp est le bon primaire

FitMAS a besoin d'un canal qui permette:

- messages proactifs
- reponses utilisateur
- webhook entrant
- automatisation officielle
- experience familiere

Par rapport a cet objectif, WhatsApp a un avantage clair:

- vraie API officielle
- webhooks
- envoi programme
- support des templates et messages interactifs

## Contraintes reelles de WhatsApp Business Platform

### 1. Ce n'est pas "juste un numero WhatsApp"

Il faut au minimum:

- un Meta business portfolio
- un WhatsApp Business Account
- un numero business
- des tokens et permissions API

### 2. Webhooks obligatoires

Pour une experience reactive et fiable, il faut:

- configurer les webhooks
- subscribre l'app au WABA
- gerer les messages entrants et les statuts de livraison

### 3. Regles d'initiation de conversation

Regle structurante:

- dans la fenetre de support client, on peut envoyer des messages libres
- en dehors, un message initie par le business doit passer par un template

Donc pour FitMAS:

- les messages heartbeat tres simples et proactifs doivent souvent etre templates
- les vraies conversations libres sont plus simples apres reponse utilisateur

### 4. Templates

Il faut assumer:

- creation de templates
- validation Meta
- maintenance des templates utiles

FitMAS ne doit donc pas dependre d'un seul template fourre-tout.
Il faut un petit catalogue propre:

- adaptation de plan
- demande de clarification
- rappel contextuel
- feedback post-seance

### 5. Cout variable

Le cout n'est pas un simple abonnement fixe.
Il depend au minimum:

- du type de message
- du pays
- du volume

Conclusion:

- il faut une vraie policy anti-bruit
- chaque message proactif doit avoir une valeur reelle

### 6. Setup et operations Meta

Il faut assumer:

- configuration Meta un peu lourde
- permissions
- tokens system user
- verification du numero
- possible friction d'onboarding business

Ce n'est pas bloquant,
mais ce n'est pas zero-friction.

## Ce que cela implique pour FitMAS

FitMAS ne doit pas etre pense comme:

- un agent qui discute librement toute la journee

FitMAS doit etre pense comme:

- un systeme qui envoie peu de messages
- des messages utiles
- souvent structures
- puis bascule en echange plus libre quand l'utilisateur repond

## Pourquoi Apple Messages for Business n'est pas un bon primaire

Apple Messages for Business est elegant,
mais il est structurellement moins adapte a notre promesse.

Limites importantes:

- l'utilisateur demarre la conversation
- si le thread est supprime, le business ne peut plus recontacter tant que l'utilisateur ne relance pas
- le positionnement est plus proche du support / commerce / rendez-vous que d'un coach proactif continu

Donc:

- bon canal secondaire possible a terme
- mauvais canal primaire pour un produit dont la valeur est la proactivite

## Recommandation d'architecture

Ne pas coder `WhatsApp` partout.

Creer une interface logique du type:

- `send_message`
- `send_template`
- `receive_inbound_message`
- `receive_delivery_event`
- `check_channel_policy`

Ainsi:

- WhatsApp est le provider V1
- un autre canal peut etre ajoute plus tard
- la logique produit ne depend pas d'un SDK specifique

## Politique produit recommandee

### A faire

- utiliser WhatsApp pour les moments a forte valeur
- garder l'app comme source de lecture du plan complet
- utiliser les templates pour ouvrir proprement certaines interactions
- convertir rapidement vers une conversation utile quand l'utilisateur repond

### A eviter

- envoyer trop de messages generiques
- mettre toute la valeur dans la messagerie seule
- confondre "presence" et "bruit"

## Recommendation finale

Pour V1:

- oui a WhatsApp
- non a une dependance conceptuelle totale a WhatsApp
- oui a une abstraction de canal
- non a Apple Messages for Business comme primaire
