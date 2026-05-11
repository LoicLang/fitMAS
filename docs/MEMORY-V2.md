---
summary: architecture memoire V2 FitMAS, decoupage profile vs working vs patterns et plan de migration
read_when:
  - refondre la memoire utilisateur
  - separer contexte court terme et faits durables
  - modifier api_messages.py ou conversation_context.py
  - ajouter des patterns appris pour le planner
---

# FitMAS Memory V2

## Statut Roadmap — 7 mai 2026

Gros chantier memoire : **pas maintenant**.

Position actuelle : garder cette grille en tete pendant les chantiers
sport/prompt, tagger progressivement les facts quand c'est peu couteux, mais ne
pas migrer la memoire tant que le comportement sportif cible n'est pas stabilise.

```text
DurableProfile     = objectifs, sports, preferences stables, contraintes recurrentes
WorkingMemory      = fatigue recente, douleur, indisponibilite temporaire, voyage
ExecutionReality   = fait, pas fait, partiel, offplan, claim utilisateur
ConversationFrame  = question ouverte, pending confirmation, hypothese en cours
```

## But

Faire de la memoire FitMAS un systeme :

- lisible
- stable
- sobre
- evolutif

Le probleme n'est pas d'avoir "plus de memoire".
Le probleme est de savoir :

- quoi ecrire
- ou l'ecrire
- quand l'expirer
- quand le promouvoir
- quoi injecter au prompt

## Probleme V1

`UserFact` porte aujourd'hui trop de roles :

- profil durable
- fatigue du jour
- indispo ponctuelle
- claim d'activite
- correction courte

Ca marche en V1 grace a `ttl` + `expires_at`, mais le contrat reste flou.

## Cible produit

FitMAS doit distinguer 4 couches.

### 1. Event Truth

Source brute, datée, non ambigue :

- `Activity`
- `AdaptationEvent`
- `CoachMessage`

Regle :
- jamais dupliquee en masse dans la memoire
- l'event store sert de verite episodique

### 2. Profile Memory

Memoire durable utilisateur.

Exemples :

- objectif principal
- preferences fortes
- contraintes stables
- style de coaching
- fragilite recurrente

Regles :

- petite
- structuree
- injectee souvent
- backing store de transition : `UserFact`

### 3. Working Memory

Whiteboard court terme.

Exemples :

- fatigue du jour
- indispo de cette semaine
- claim d'activite non encore logge
- correction recente
- adaptation en cours

Regles :

- TTL heures / jours
- injectee seulement si pertinente
- purgeable
- nouvelle table dediee

### 4. Pattern Memory

Patterns appris, utiles au planner.

Exemples :

- mardi soir souvent impossible
- meilleure adherence le matin
- saute souvent apres escalade
- accepte mieux les versions courtes que les doubles seances

Regles :

- jamais ecrite brut depuis une phrase unique
- promotion lente depuis le reel
- deterministe avant tout
- jamais depuis un regex/keyword sur texte utilisateur libre ; les signaux memoire conversationnels viennent d'une action structuree LLM puis d'un writer borne

## Mapping technique

### V2 tranche 1

- `UserFact` = `profile_memory`
- nouvelle table `working_memory_entries`
- nouveau module `memory_routing.py`
- nouveau module `memory_profile.py`
- nouveau module `memory_working.py`

Etat :

- fait
- `api_messages.py`, `heartbeat.py`, `planning_state.py` et les read models app lisent deja `profile + working`

### V2 tranche 2

- table `user_patterns`
- module `memory_patterns.py`
- module `memory_maintenance.py`

Etat :

- fait
- promotion deterministe actuelle :
  - creneau recurrentement indisponible depuis signaux memoire structures + adaptations logistiques
  - fenetre d'entrainement preferentielle depuis les activites reelles
- endpoint lecture : `/api/v0/patterns`
- cron maintenance : toutes les 6h cote scheduler Telegram

## Regles d'ecriture

Depuis le 30 avril 2026, une ecriture memoire issue d'une conversation doit suivre :

```text
texte user libre
  -> Coach LLM
  -> memory_actions structurees
  -> validation / dedup / TTL / permissions
  -> writer memoire borne
  -> audit
```

Interdit : creer une fatigue, douleur, disponibilite, preference ou contrainte depuis un pattern lexical local sur le texte user.

### Cycle de vie des facts — 11 mai 2026

Les facts ont maintenant une temporalite explicite et un statut de vie.

Champs canoniques :

```text
status            = open | new | ongoing | improving | worsening | resolved | stale | superseded
severity          = mild | moderate | severe | medium | high | unknown
signal_kind       = pain | injury | fatigue | sleep | illness | tension | availability_limited | ...
observed_at       = moment ou le signal est observe
valid_from        = debut de validite
valid_until       = fin de validite metier
last_seen_at      = derniere confirmation
resolved_at       = moment de resolution
resolution_reason = raison courte de resolution
```

Contrat important :

- le LLM decide si un message contient une info memoire importante ;
- le LLM emet une `memory_action` structuree ;
- le writer borne persiste statut, temporalite, severite et `signal_kind` ;
- les lecteurs runtime ne redevinent pas l'intention depuis le texte du fact.

Exemples :

```text
"j'ai mal au genou"
-> record_health_signal(signal_kind=pain, severity=unknown, status=new)

"plus de tension au tibia"
-> record_health_signal(signal_kind=tension, body_area=tibia, status=resolved)

"je ne peux pas nager deux semaines"
-> record_availability(availability=unavailable, starts_on/ends_on si inferables)
```

### Lecture readiness

`readiness.py` ne lit plus les mots des contraintes, preferences, objectifs,
notes coach ou valeurs de facts pour fabriquer des flags.

Il consomme uniquement :

```text
fact.active == true
fact.status non resolu
fact valid temporellement
fact.affects contient readiness
fact.category / signal_kind / severity / status
```

Donc un vieux fact qui mentionne "sommeil", "travail", "tendon" ou "maladie"
ne peut plus degrader le planning s'il n'est pas un signal readiness ouvert et
structure.

Cette frontiere est volontaire :

```text
LLM = comprendre le message et maintenir la memoire.
Runtime = valider, dater, expirer, filtrer et consommer les artefacts structures.
Readiness = etat sportif depuis facts structures + charge reelle, jamais depuis mots-cles.
```

### Ecrit dans profile memory

Faits :

- `medium`
- `long`
- `permanent`

Exemples :

- preference stable
- objectif
- contrainte recurrente
- douleur / blessure qui affecte plusieurs semaines

### Ecrit dans working memory

Faits :

- `immediate`
- `short`

Exemples :

- fatigue du jour
- indispo ponctuelle
- claim execution
- correction conversationnelle a courte duree

## Regles de lecture

### Conversation coach

Injecter :

1. profile memory utile
2. working memory utile
3. event truth resumee

Ne jamais injecter :

- historique brut
- liste brute des activites
- vieux messages non compactes

### Planner / replan

Lire :

1. profile memory
2. working memory
3. pattern memory
4. event truth si besoin

### Heartbeat

Lire :

1. working memory actuelle
2. profile memory utile
3. pattern memory si elle explique un comportement

## Promotion vers pattern memory

Principe :

- write less
- structure more
- promote slowly

Un pattern ne doit pas venir d'une phrase unique.

Il doit venir :

- d'evenements repetes
- sur plusieurs semaines
- avec un seuil minimal de preuve

Exemples de signaux promotables :

- 3+ indispos sur le meme creneau
- 3+ adaptations du meme type
- 3+ seances sautees apres le meme contexte

## Calibration Need Loop

Pour garder un coach humain sans rendre le write path flou, FitMAS ajoute une boucle courte :

1. detecter un doute utile
2. le faire vivre comme `CalibrationNeed`
3. laisser le coach le formuler naturellement
4. resoudre la reponse dans un schema ferme
5. ecrire seulement si la confiance est suffisante

Regles :

- on ne hardcode pas la question visible
- on hardcode le contrat systeme
- `CalibrationNeed` vit en `working_memory`
- TTL courte
- un seul besoin actif par sujet
- aucune ecriture directe en `profile_memory` depuis une simple reponse de calibration

Types MVP :

- `availability_window`
- `fatigue_state`
- `constraint_scope`

La promotion vers `pattern_memory` reste lente et deterministe.

## Migration recommandee

### Phase 1

- documenter la cible
- creer `working_memory_entries`
- router les ecritures `immediate/short` vers working memory
- garder `UserFact` pour le durable
- adapter conversation + heartbeat + athlete profile a lire profile + working

### Phase 2

- ajouter `user_patterns`
- creer des promotions deterministes simples
- injecter les patterns au planner

Etat :

- fait
- les patterns sont lus par `planning_state.py`, `heartbeat.py`, `api_messages.py`, `api_app.py`

### Phase 3

- maintenance loop
- purge des working memories expirees
- promotion / demotion de patterns
- compactage de profile memory si bruit

Etat :

- partiel
- purge working memory : fait
- promotion patterns : fait
- archivage des patterns maintenance absents au cycle suivant : fait
- compactage profile memory : plus tard

## Priorites maintenant

Le prochain gain memoire ne vient pas d'une V3 abstraite.
Il vient d'un meilleur write path et d'un meilleur resume injecte.

Ordre :

1. normaliser les faits temporels en date absolue avant `upsert_facts`
2. produire un `profile_summary` compact et toujours injectable
3. persister un transcript structure avant de lancer une vraie consolidation
4. seulement ensuite : compactage / consolidation periodique de `profile_memory`

Notes :

- `transcript != memory durable`
- la consolidation attend un write path temporel plus fiable
- un resume profil propre vaut mieux qu'une pile de facts bruts

## Idees V3

Garder pour plus tard.
Ne pas melanger avec la V2 tant que le systeme simple n'a pas prouve sa valeur.

- patterns contextuels plus fins
  - ex : adherence plus faible apres escalade
  - ex : repond mieux aux versions courtes qu'aux doubles seances
- demotion progressive au lieu d'un simple archivage
  - baisse de confiance si le pattern cesse d'etre observe
- promotion profile plus selective
  - faire remonter un pattern tres stable vers `profile_memory`
- compactage profile memory
  - dedupe
  - contradictions simples
  - vieillissement des faits semi-stables
- availability state appris
  - convertir des indispos recurrentes en contraintes de planning plus explicites
- patterns confirmables par l'utilisateur
  - FitMAS peut dire : `je remarque que le mardi soir saute souvent, je le traite comme fragile ?`
- analytics memoire
  - combien de patterns actifs
  - quels patterns sont utilises par le planner
  - quels patterns n'apportent rien

## Anti-patterns

- continuer a utiliser `UserFact` comme fourre-tout
- mettre execution, fatigue et objectif dans la meme lecture brute
- promouvoir un pattern depuis un seul message
- injecter la memoire complete au prompt
- dupliquer l'event truth dans tous les stores
