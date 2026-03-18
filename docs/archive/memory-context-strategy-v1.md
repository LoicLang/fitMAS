---
summary: strategie de contexte et memoire v1 pour garantir la continuite du plan, des decisions et des discussions
read_when:
  - concevoir la memoire du systeme
  - gerer le contexte LLM
  - garantir la continuite des plans
  - implementer la persistance conversationnelle
---

# Memory Context Strategy V1

## Pourquoi c'est critique

Pour `FitMAS`, la memoire n'est pas un plus.
C'est le produit.

Si la memoire est faible:

- le plan devient incoherent
- les messages semblent generiques
- les agents se contredisent
- l'utilisateur perd confiance

La continuite doit exister sur 3 axes:

- continuite du plan
- continuite de la relation
- continuite des decisions

## Erreur classique a eviter

Ne pas confondre:

- historique complet
- memoire utile
- contexte a injecter au modele

Ce n'est pas parce qu'une information a existe qu'elle doit vivre:

- dans le prompt
- dans le thread
- dans la memoire long terme

Le bon systeme separe:

- ce qui s'est passe
- ce qu'on sait durablement
- ce qu'on pense temporairement
- ce qu'il faut montrer au modele maintenant

## Principe directeur

La memoire de FitMAS doit etre `stratifiee`.

Pas une seule memoire.
Pas un seul store.
Pas un seul prompt.

## Ce qu'OpenClaw confirme

Les patterns OpenClaw les plus utiles pour FitMAS sont:

- distinguer clairement `context` et `memory`
- garder un petit noyau identitaire toujours charge
- traiter les fichiers / etats stables comme une memoire durable
- utiliser la recherche memoire comme un rappel, pas comme la verite
- compresser les sessions plutot que trainer tout l'historique
- deriver un index de rappel a partir d'une source de verite editable

Ce que cela valide pour FitMAS:

- le modele ne "se souvient" pas tout seul
- il faut une source de verite persistante
- il faut injecter peu de contexte, mais le bon
- la memoire semantique doit etre derivee de l'etat, pas l'inverse

## Les 6 couches de memoire recommandees

## 1. Raw event log

Memoire brute et auditable.

Contient:

- activites Strava
- signaux HealthKit
- messages WhatsApp
- changements calendrier
- evenements app

Usage:

- audit
- replay
- derivation de signaux

Ne jamais envoyer cette couche telle quelle au LLM.

## 2. Workflow state

Memoire de court / moyen terme du processus en cours.

Contient:

- workflow utilisateur actif
- tick en attente
- cooldowns
- attentes de feedback
- prochaines reevaluations

Bonne maison:

- Temporal

Usage:

- garantir la continuite d'execution
- reprendre apres panne
- attendre un signal ou un timer

## 3. Thread memory

Memoire conversationnelle locale a un fil.

Contient:

- dernieres interactions d'une conversation
- messages pertinents recents
- contexte de l'echange actuel

Usage:

- repondre correctement a court terme
- garder le ton et l'objet du fil

Important:

- cette couche doit etre compacte
- elle doit etre resumee regulierement
- elle ne doit pas devenir la source de verite

## 4. Digital twin memory

C'est la memoire identitaire et comportementale durable.

Contient:

- objectifs
- preferences
- gouts
- contraintes
- style de motivation
- tolerance a la charge
- patterns d'adherence
- non negociables

Usage:

- personnalisation
- decisions de plan
- ton des messages

Regle:

- les preferences explicites priment sur les simples inférences

Inspiration OpenClaw:

- equivalent du petit noyau `MEMORY.md` ou des fichiers bootstrap
- petit volume
- charge tres frequemment
- stable et relu a chaque cycle important

## 5. Plan lineage memory

C'est une couche cruciale souvent oubliee.

Contient:

- versions des plans
- rationales des changements
- ce qui a ete deplace, supprime, ajoute
- pourquoi une adaptation a eu lieu

Usage:

- continuité du plan
- explicabilité
- éviter les changements incohérents

Sans cette couche,
le systeme oublie facilement pourquoi il a decide quelque chose.

## 6. Episodic and semantic memory

Memoire compressée des apprentissages utiles.

Deux sous-types:

- episodique: resumes de semaines, evenements marquants, patterns observes
- semantique: faits rappelables par sens ou theme

Exemples:

- adhere mieux quand la semaine est visible des le dimanche soir
- ne tolere pas bien les seances intenses apres mauvaise nuit
- prefere les messages tres directs avant une seance cle

Usage:

- recuperer des apprentissages sans recharger tout l'historique

Inspiration OpenClaw:

- journal quotidien / session snapshots pour la memoire episodique
- index derive pour le rappel
- recence et diversite des resultats utiles pour eviter les rappels repetitifs

## Ce qui doit etre la source de verite

Source de verite recommandee:

- Postgres

Pas:

- le thread du LLM
- une base vectorielle seule
- des resumes libres en texte

Equivalent conceptuel inspire d'OpenClaw:

- OpenClaw garde ses fichiers memoire comme source de verite
- l'index de recherche n'est qu'une vue derivee

Pour FitMAS, on garde la meme philosophie:

- les tables produit sont la verite
- les resumes et index servent au rappel

## Pourquoi SQL reste pertinent meme pour du texte libre

SQL ne veut pas dire:

- uniquement des colonnes tres structurees
- uniquement des nombres et enums
- impossible pour les explications longues

Au contraire, pour FitMAS on peut stocker sans probleme en base:

- un resume de conversation en `TEXT`
- une rationale de changement de plan en `TEXT`
- un objet de double numerique souple en `JSONB`
- une liste de faits / preferences en `JSONB`
- des payloads d'evenements en `JSONB`

Autrement dit:

- SQL = moteur de persistance et de requete
- pas forcement schema rigide partout

Le point important n'est pas "est-ce du texte ?"
Le point important est:

- est-ce adressable ?
- versionnable ?
- requetable ?
- liant a un utilisateur, un plan, un event, une decision ?

Sur ces points, SQL est tres fort.

## Quand Markdown fait vraiment sens

OpenClaw utilise Markdown comme source de verite memoire,
et cela fait sens dans son contexte:

- un agent avec un workspace
- des fichiers bootstrap injectes
- une logique de notes durables et journaux quotidiens
- une memoire lisible / editable a la main

Pour FitMAS, Markdown fait sens surtout pour:

- l'ame FitMAS
- l'identite de marque
- la checklist heartbeat
- des playbooks ou policies stables

Markdown fait moins sens comme memoire primaire par utilisateur pour:

- des milliers d'evenements
- des versions de plan
- des relations entre decisions et triggers
- des requetes du type "recupere les 3 derniers changements de plan dus au sommeil"

## Bonne synthese pour FitMAS

La bonne approche n'est ni:

- tout SQL structure dur

ni:

- tout Markdown facon workspace local

La bonne approche est:

- SQL comme memoire produit et relationnelle
- texte libre a l'interieur de SQL quand il faut
- Markdown pour les instructions stables du systeme
- retrieval pour rappeler quelques souvenirs utiles

## Role des vecteurs

Les vecteurs peuvent aider.
Ils ne doivent pas piloter la verite.

Bon usage:

- retrouver des souvenirs semantiquement proches
- enrichir le contexte d'un cycle complexe
- retrouver d'anciens patterns pertinents

Mauvais usage:

- stocker toutes les decisions critiques uniquement en vector DB
- faire du vector search la seule facon de se souvenir

Recommendation V1:

- pas de vector DB obligatoire des le debut
- Postgres d'abord
- pgvector possible plus tard si la memoire semantique devient utile

OpenClaw va dans le meme sens:

- d'abord rappel lexical / structure
- puis enrichissement semantique si necessaire
- les vecteurs sont un accelerateur, pas le coeur du modele memoire

## Strategie de contexte LLM

Le contexte envoye au modele ne doit jamais etre:

- tout l'historique
- toutes les memories
- toutes les activites

Le contexte doit etre compose dynamiquement.

Rappel utile inspire d'OpenClaw:

- le contexte est la fenetre du run courant
- la memoire est ce qui peut etre recharge plus tard

Donc:

- ne pas confondre `ce qu'on stocke`
- et `ce qu'on injecte maintenant`

## Contexte minimal pour un cycle de decision

Pour un cycle typique d'adaptation, injecter seulement:

- objectif principal
- contraintes critiques
- etat recent utile
- plan courant
- dernieres adaptations
- signaux derives recents
- quelques faits du double numerique
- eventuel feedback utilisateur recent

## Contexte minimal pour un message WhatsApp

Pour un message sortant, injecter seulement:

- ton / style FitMAS
- etat utile du plan
- raison du message
- 1 a 3 faits personnels pertinents
- dernier echange recent si necessaire

## Compression et summarisation

Le systeme doit resumer regulierement,
pas seulement truncater.

Compression recommandee:

- resume de conversation a la fin d'un echange utile
- resume quotidien si beaucoup d'activite
- resume hebdo centre sur adherence et apprentissages

Idee reprise d'OpenClaw:

- snapshots de session ou de periode courte
- puis resume plus stable a plus long terme

Pour FitMAS:

- snapshot apres echange WhatsApp important
- resume quotidien si nombreux signaux
- resume hebdo pour apprentissages durables

## Ecriture memoire

Toute information ne doit pas devenir memoire.

Une ecriture durable doit passer un filtre:

- est-ce stable ?
- est-ce actionnable plus tard ?
- est-ce personnel a cet utilisateur ?
- est-ce suffisamment confirme ?

Sinon:

- garder en thread local
- ou ne pas stocker du tout

## Schema de mise a jour recommande

Quand un evenement arrive:

1. log brut
2. signaux derives
3. eventuelle mise a jour workflow
4. eventuelle mise a jour du double numerique
5. eventuelle adaptation de plan
6. eventuelle ecriture episodique
7. eventuel message

## Continuite du plan

Pour que le plan paraisse coherent dans le temps,
il faut versionner et relier les plans.

Chaque plan doit porter:

- parent_plan_id
- motive du changement
- evenements declencheurs
- impacts attendus

Ainsi, FitMAS peut dire:

- ce qui a change
- pourquoi
- et comment cela preserve l'objectif global

## Continuite des discussions

La relation conversationnelle ne doit pas dependre d'un seul thread.

Il faut distinguer:

- derniers messages utiles
- preference de ton durable
- faits personnels durables
- questions ouvertes en attente

Un bon systeme peut reprendre une discussion meme si:

- le thread WhatsApp est calme depuis plusieurs jours
- le workflow a redemarre
- l'app a ete fermee

## Continuite des decisions

Chaque decision importante doit laisser une trace structuree.

Exemples:

- pourquoi la seance a ete deplacee
- pourquoi les calories ont ete maintenues
- pourquoi aucun message n'a ete envoye

Le no-op doit aussi etre memorisable si c'est utile.

## Recommendation pratique V1

V1 doit etre construit avec:

- Postgres pour l'etat et l'historique structure
- Temporal pour l'etat des workflows
- conversation recente compacte
- double numerique durable
- versions de plan
- resumes episodiques

Et en pratique:

- un `core context builder` qui assemble le minimum utile par type de run
- un `memory writer` qui decide ce qui merite d'etre persiste durablement
- un `memory retriever` qui recupere quelques faits / episodes pertinents
- une policy stricte pour eviter que la conversation brute devienne la memoire centrale

V1 ne doit pas encore compter sur:

- une memoire vectorielle centrale
- un giant prompt
- une simple pile de chats

## Decision d'architecture

La bonne memoire FitMAS n'est pas:

- "plus de contexte"

La bonne memoire FitMAS est:

- "le bon contexte, dans la bonne couche, au bon moment"

## Traduction concrete pour FitMAS

Si on reprend l'esprit OpenClaw sans copier son format,
on obtient:

- `SOUL` FitMAS: mission, ton, garde-fous, role
- `USER_IDENTITY`: informations stables sur la personne
- `DIGITAL_TWIN`: etat produit durable
- `THREAD_MEMORY`: echange recent
- `PLAN_LINEAGE`: historique des choix
- `EPISODIC_SUMMARIES`: ce qu'on veut encore savoir dans 1 semaine
- `RETRIEVAL_INDEX`: vue derivee pour rappel lexical ou semantique
