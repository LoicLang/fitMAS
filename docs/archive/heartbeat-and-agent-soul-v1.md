---
summary: design du heartbeat v1 et de l'ame produit de FitMAS, inspire des patterns OpenClaw
read_when:
  - concevoir la proactivite
  - definir la messagerie WhatsApp
  - donner une voix coherente au produit
  - implementer les routines autonomes
---

# Heartbeat And Agent Soul V1

## Intention

FitMAS doit sembler vivant.
Pas juste reactif.
Pas juste bavard non plus.

L'inspiration utile venue d'OpenClaw n'est pas de copier un chatbot.
C'est de copier trois principes:

- un heartbeat explicite
- une memoire structuree
- une ame produit stable

## Ce qu'il faut reprendre d'OpenClaw

Patterns tres pertinents:

- heartbeat regulier qui reveille le systeme
- contrat de silence quand rien n'est utile
- checklist courte et stable
- separation entre identite, memoire et instructions de routine

## Ce qu'il ne faut pas copier tel quel

FitMAS n'est pas un assistant personnel generaliste.

Donc il ne faut pas:

- le reveiller juste "pour voir"
- lui laisser une liberte totale de conversation
- exposer plusieurs voix agentiques a l'utilisateur

Le heartbeat FitMAS doit etre beaucoup plus cadre,
oriente performance et anti-friction.

## Le bon modele FitMAS

Le bon systeme est un `heartbeat hybride`.

Il y a 3 facons de reveiller l'orchestrateur:

1. par evenement
2. par routine planifiee
3. par exception

### 1. Reveil par evenement

Le plus important.

Exemples:

- nouvelle activite Strava
- nouvelle donnee HealthKit utile
- changement de calendrier
- retour utilisateur WhatsApp

Quand un vrai signal arrive,
le systeme se reveille.

### 2. Reveil par routine planifiee

Necessaire pour garder une presence proactive.

Exemples:

- nuit: reevaluer le lendemain
- debut de semaine: produire / ajuster le plan hebdo
- milieu de journee: check de conflit ou d'incertitude

### 3. Reveil par exception

Exemples:

- aucun signal recent alors qu'une seance cle etait prevue
- utilisateur silencieux apres grosse adaptation
- donnee incoherente

## Le contrat de heartbeat V1

A chaque reveil, le systeme doit se poser la meme suite de questions:

1. y a-t-il un changement de contexte reel ?
2. faut-il mettre a jour le plan ?
3. faut-il mettre a jour le double numerique ?
4. faut-il poser une question ?
5. faut-il envoyer un message ?
6. sinon, rester silencieux

Le no-op doit etre un vrai resultat possible.

## Active hours et cooldown

Le heartbeat doit etre borne.

Regles V1 recommandees:

- fenetre active locale utilisateur
- cooldown minimal entre deux messages proactifs
- jamais de message si la valeur est faible
- jamais de ping de "presence vide"

FitMAS doit paraitre attentif,
pas needy.

## Policy de messagerie proactive

Envoyer un message seulement si au moins une de ces conditions est vraie:

- adaptation utile a expliquer
- ambiguite bloquante a lever
- risque d'adhesion a traiter
- check-in contextuel a forte valeur
- retour apres evenement important

Important:

la proactivite utile ne doit pas etre comprise de facon trop froide.
FitMAS doit aussi pouvoir envoyer des messages spontanes,
si ces messages sont ancrés dans un evenement reel et augmentent la sensation d'equipe vivante.

Ne pas envoyer de message si:

- le plan n'a pas change
- aucune action n'est attendue
- le systeme ne ferait que "prendre des nouvelles" sans contexte solide

## Types de messages V1

Pour rester juste, V1 doit distinguer 3 familles:

### 1. Messages operationnels

Exemples:

- adaptation de plan
- clarification necessaire
- rappel avant conflit connu

But:

- faire avancer le systeme

### 2. Messages de feedback contextuel

Exemples:

- demande courte apres une seance cle
- verification de ressenti apres fatigue inhabituelle

But:

- apprendre
- mieux ajuster le double numerique

### 3. Messages spontanes relationnels-contextuels

Exemples:

- acknowledgement apres grosse seance
- message bref apres evenement important
- reconnaissance d'un cap franchi

But:

- donner de l'ame
- renforcer la sensation de suivi
- rendre l'equipe vivante

Regle:

ces messages ne doivent jamais etre generiques.
Ils doivent etre declenches par un signal reel.

Exemple d'esprit:

- "Belle seance. Gros bloc valide aujourd'hui. Je garde demain un peu plus leger pour proteger la recuperation."

Mauvais exemple:

- "Bravo, continue comme ca !"

## L'ame produit

L'utilisateur ne doit pas sentir 3 agents differents qui parlent.
Il doit sentir une seule equipe coherente.

Recommendation:

- une seule voix externe: `FitMAS`
- plusieurs specialistes internes invisibles

## Composants de l'ame

Je recommande de separer 4 couches conceptuelles:

### 1. TEAM_SOUL

Ce que FitMAS defend:

- performance durable
- personnalisation reelle
- exigence sans brutalite
- adaptation a la vraie vie
- aide concrete plutot que discours generique

### 2. COACH_IDENTITY

Comment FitMAS parle:

- clair
- court
- precis
- confiant
- chaleureux sans faux enthousiasme

### 3. USER_IDENTITY

Qui est la personne:

- objectifs
- gouts
- contraintes
- style de motivation
- patterns connus

### 4. HEARTBEAT_CHECKLIST

Ce que le systeme doit verifier regulierement.

## Fichiers / artefacts conceptuels recommandes

Meme si l'implementation finale ne repose pas sur des fichiers texte prompts bruts,
la separation conceptuelle doit exister.

Artefacts recommandes:

- `SOUL.md` ou equivalent system prompt stable
- `IDENTITY.md` ou equivalent voix de marque
- `USER_STATE` structurel
- `HEARTBEAT.md` ou equivalent checklist courte

## Proposition concrete pour FitMAS

### SOUL.md

Contient:

- mission
- valeurs
- garde-fous
- maniere d'aider

### IDENTITY.md

Contient:

- ton
- style de message
- regles de formulation
- niveau de challenge

### HEARTBEAT.md

Tres court.
Exemple de logique:

- verifier s'il y a une adaptation utile
- verifier si le plan de demain est toujours realiste
- verifier si une question courte debloquerait une meilleure decision
- sinon rester silencieux

## Rendu utilisateur

Le message FitMAS parfait en V1 doit:

- etre court
- etre contextuel
- faire sentir une vraie lecture de la situation
- donner une action ou une clarification nette

Ou, dans le cas d'un message spontane:

- reconnaitre un evenement reel
- ajouter une lecture utile
- renforcer la sensation que l'equipe suit vraiment la personne

Exemple d'esprit:

- "Ta sortie de mardi saute avec ton agenda. J'ai deplace la seance tempo a jeudi et allege demain pour garder de la fraicheur."
- "Belle sortie longue aujourd'hui. Tu as tenu proprement le bloc. Je surveille la recup demain avant de confirmer l'intensite de mardi."

Mauvais exemple:

- "Salut, comment ca va aujourd'hui ?"

## Architecture du heartbeat

Le heartbeat ne doit pas envoyer directement du texte brut.

Pipeline recommande:

1. reveil du workflow
2. collecte du contexte utile
3. evaluation des triggers
4. decision no-op ou action
5. si message: generation par la couche de voix FitMAS
6. envoi WhatsApp
7. persistence du message et du motif

## Priorite V1

Le meilleur heartbeat V1 n'est pas le plus frequent.
C'est le plus juste.

Objectif:

- peu de messages
- bons messages
- bon timing
- bon ton
