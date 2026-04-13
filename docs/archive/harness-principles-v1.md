---
summary: principes canoniques du harness FitMAS: couches de contexte, substrate de décision, transcript, mémoire et heartbeat
read_when:
  - refondre le harness conversationnel
  - modifier la chaîne message -> décision -> mutation
  - toucher la mémoire, le transcript ou les heartbeats
  - arbitrer ce qui relève du LLM vs du moteur déterministe
---

# FitMAS Harness Principles

## But

Donner une référence courte et opératoire du coeur FitMAS.

Le but n'est pas de documenter chaque module.
Le but est de figer les principes qui évitent de retomber dans :

- le gros prompt opaque
- le LLM qui comprend, choisit et agit seul
- la mémoire confuse
- les heartbeats mécaniques

## Principe 1 — comprendre puis décider

FitMAS ne doit pas demander à un seul bloc LLM de :

1. comprendre le langage naturel
2. choisir une option planning
3. exécuter la mutation
4. formuler la réponse

Le bon flux est :

1. message user
2. extraction d'une intention / contrainte structurée
3. génération ou scoring de scénarios valides
4. choix de la meilleure option
5. explication claire côté coach

Règle :
- le LLM aide à comprendre et expliquer
- le moteur protège la cohérence

## Principe 2 — le vrai contexte est en couches

FitMAS doit séparer :

### Couche stable

- identité coach
- style
- doctrine
- règles durables

### Couche semi-stable

- résumé profil
- mission de semaine
- calendrier daté

### Couche immédiate

- temps local
- réalité récente
- signaux du jour
- clarification ouverte

### Couche mémoire / transcript

- mémoire utile sélectionnée
- highlights conversationnels récents

Règles :

- le contexte durable vit hors prompt
- le prompt reçoit des résumés compacts
- on n'injecte pas l'historique brut par réflexe

## Principe 3 — transcript et mémoire sont différents

### Transcript

Le transcript garde :

- ce qui a été dit
- ce qui a été décidé
- le contexte utilisé
- les écritures mémoire

Le transcript sert à :

- auditer
- débugger
- reconstruire des highlights
- consolider plus tard

### Mémoire

La mémoire garde uniquement ce qui mérite d'influencer le futur.

Elle reste séparée en :

- `profile`
- `working`
- `patterns`

Règle :
- on ne promeut pas un message brut en vérité durable sans raison

## Principe 4 — les tools doivent être atomiques

Quand le modèle a besoin de lire quelque chose, on préfère des tools sémantiques étroits :

- `today_context`
- `plan_window`
- `resolve_planning_window`
- `recent_activities`
- `relevant_facts`

Pourquoi :

- moins de contexte brut
- permissions plus lisibles
- traces plus auditables
- réutilisation plus propre

Règle :
- un tool = une lecture métier claire
- éviter le shell mental “fais tout avec un seul appel”

## Principe 5 — le planning repose sur un substrate de décision

Une négociation planning doit produire un objet intermédiaire stable.

Exemples de champs utiles :

- séance touchée
- contrainte source
- jours autorisés
- préférence ordonnée
- borne minimale (`pas avant jeudi`)
- fenêtre horaire
- mission hebdo à protéger
- coût de changement

Règles :

- si l'utilisateur propose un espace valide, le moteur choisit dedans
- si cet espace ne marche pas, FitMAS clarifie
- FitMAS n'invente pas un autre jour silencieusement

## Principe 6 — la review hebdo juge la réalité, pas juste les compteurs

Le bilan du dimanche doit intégrer :

- activités réelles
- activités déclarées
- adaptations de semaine
- faits santé / fatigue
- highlights utiles du transcript

Règle :
- une semaine neutralisée par maladie n'est pas une semaine de simple non-adhérence

## Principe 7 — le heartbeat doit prouver son utilité

Un heartbeat n'existe que s'il apporte quelque chose.

Il doit être :

- ancré dans un delta réel
- non répétitif
- parcimonieux
- cohérent avec les garde-fous déterministes

Règles :

- le silence est un résultat valide
- ne pas recycler les contraintes stables tous les matins
- varier l'angle avant de varier le style
- l'horaire doit vivre dans une fenêtre, pas au même minuteur visible chaque jour

## Répartition des responsabilités

### LLM

- comprend
- reformule
- explique
- choisit parfois entre quelques options proches si le cadre est déjà borné

### Moteur déterministe / hybride

- résout la fenêtre touchée
- préserve l'espace autorisé
- score la cohérence semaine
- protège la mission
- limite l'instabilité

### Persistance

- garde transcript, mémoire, événements, activités
- alimente app + Telegram

## Anti-patterns à éviter

- faire lire tout le profil brut à chaque tour
- reposer un heartbeat sur les mêmes contraintes stables sans nouveauté
- perdre l'intention utilisateur entre extraction et mutation
- laisser un simple “jour libre” gagner contre une semaine sportivement absurde
- confondre fact actif, vérité durable et souvenir conversationnel

## État actuel visé

FitMAS doit converger vers :

- conversation mieux structurée
- planner plus cohérent
- review hebdo narrative et juste
- heartbeat moins robotique

Si un changement local améliore un symptôme mais renforce un anti-pattern ci-dessus, il faut le reconsidérer.

## Audit franc — avril 2026

## Ce qu'on garde

- la séparation `profile / working / patterns`
- le transcript structuré distinct de la mémoire
- les tools de lecture sémantiques et bornés
- le planner plus déterministe que le coach conversationnel
- les prompt layers maintenant branchés sur le chemin live
- la séparation heartbeat `evaluation / generation / delivery`

Pourquoi :

- ces briques rendent le système plus lisible
- elles réduisent la dépendance à un gros prompt opaque
- elles permettent d'augmenter la fiabilité sans tout réécrire

## Ce qu'on arrête

- laisser un bloc LLM faire seul `comprendre + décider + agir`
- recycler les contraintes stables dans les heartbeats par simple présence en mémoire
- croire qu'un "jour ouvert" suffit à faire un bon move planning
- ajouter de la liberté conversationnelle sans substrate explicite
- considérer qu'un coach plus libre est automatiquement un coach plus juste

## Ce qu'on doit extraire en primitives métier

Prochain niveau d'atomicité utile :

- `extract_planning_intent`
- `score_move_candidates`
- `build_weekly_reality_digest`
- `select_heartbeat_angle`
- `detect_novelty_since_last_proactive`

Règle :
- tant qu'une capacité importante n'existe que comme comportement émergent du prompt, elle reste fragile

## Liberté utile vs liberté dangereuse

FitMAS ne doit pas viser la même liberté qu'un coach humain sur tous les axes.

La bonne asymétrie :

- parole : liberté moyenne
- mémoire : liberté faible à moyenne, très structurée
- action : liberté faible, très bornée

Raison :

- un message un peu imparfait se rattrape
- une mémoire fausse pollue des semaines
- une action fausse casse directement la confiance

## Fiabilité cible

FitMAS devient crédible quand il sait :

- parler avec contexte et retenue
- se souvenir sans mélanger durable, temporaire et conversationnel
- agir dans un espace valide et cohérent

FitMAS n'est pas encore un "vrai coach humain".
La cible produit n'est pas de maximiser sa liberté.
La cible est de maximiser :

- la justesse
- la cohérence
- la continuité de contexte
- la confiance perçue
