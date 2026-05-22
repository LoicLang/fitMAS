---
summary: doctrine zero determinisme sur texte utilisateur libre
read_when:
  - modifier conversation_pipeline.py
  - modifier llm/understanding_service.py
  - ajouter une action memoire, sante, disponibilite, execution ou preference
  - toucher aux pending confirmations
  - corriger un bug de comprehension du message utilisateur
---

# LLM-First Conversation

## Regle Dure

Aucun sens humain ne vient du code.

Le texte utilisateur libre ne doit jamais etre lu par un regex, keyword,
classifieur deterministe, short-circuit ou parser maison pour decider :

- intention ;
- negation ;
- sante, douleur, fatigue ;
- disponibilite ;
- execution faite ou non faite ;
- preference ;
- confirmation pending ;
- mutation planning ;
- sport, date ou fenetre cible.

Phrase canonique :

```text
Le LLM comprend le langage humain.
Le code comprend l'etat systeme.
```

## Determinisme Autorise

Autorise uniquement sur artefacts machine :

- sortie LLM structuree ;
- schema JSON / Pydantic ;
- IDs, dates, statuts, slugs, events DB ;
- `ScheduledSession`, `Activity`, facts actifs ;
- permissions, validation, dedup, TTL ;
- comparaison reply vs grounding/outcome.

Exemples valides :

- resoudre un `target_session_id` LLM contre la DB ;
- refuser une cible ambigue ;
- revalider un pending stocke avant commit ;
- bloquer une reply qui claim un commit sans event ;
- dedup un tool call identique dans un meme tour.

## Determinisme Interdit

Interdit en runtime conversation :

- detecter `oui/non` dans `user_text` ;
- detecter douleur/fatigue/dispo par mots cles ;
- choisir des tools depuis des keywords utilisateur ;
- ecrire une memoire depuis un pattern lexical ;
- declencher une mutation planning depuis une phrase libre ;
- faire un fallback reply canned pour masquer un trou d'architecture.

## Flux Cible

```text
User text
-> Understanding LLM
   -> intent, signaux, references, requested_change, pending_resolution
-> backend validation
-> domain policy
-> command/mutation service
-> events
-> DecisionOutcome
-> ReplyComposer
-> OutputVerifier
```

Le LLM peut comprendre et formuler.
Il ne commit pas.
Il ne produit pas de verite DB.

## Etat Actuel

En place :

- le routing deterministe user-text historique a ete retire ;
- les tools sont exposes par capacite, pas par parser local du message ;
- `pending_resolution` remplace le parsing local des confirmations ;
- `CoachUnderstanding` existe pour isoler la comprehension ;
- `DecisionOutcome` existe pour isoler la sortie runtime ;
- root `final_reply.py` et root `api_messages.py` sont supprimes.

Encore en transition :

- `CoachDecision` legacy est supprime du provider path ;
- `conversation_pipeline.py` orchestre encore trop ;
- `MutationDecision` vit dans `domain/planning/mutation_decision.py` pour le
  vieux writer planning.

## Pending

Une reponse courte a un pending suit ce flux :

```text
LLM -> pending_resolution
DB -> pending active unique et non expiree
validation -> artefact stocke encore applicable
policy -> accept / reject / modify / clarify
```

Le backend ne comprend jamais `oui` ou `non`.
Il comprend seulement le type structure rendu par le LLM.

## Tools

Les tools LLM-facing sont :

- read-only ;
- validation-only ;
- parfois candidate-only, sans write.

Ils ne doivent jamais devenir des writes DB libres.
Les writes restent apres la decision, dans des services bornes.

## Prompt Hygiene

Un prompt ne doit pas compenser une architecture floue.

Regles :

- prompts courts ;
- pas de mega contrat qui liste tous les bugs historiques ;
- pas d'exemples de tests qui leakent nos smokes ;
- 1 a 2 few-shots maximum quand utile ;
- schema de sortie clair ;
- si le prompt grossit, chercher la frontiere backend manquante.

## Tests D'Architecture

A proteger :

- aucun regex/keyword sur user text dans conversation runtime ;
- aucun `PlanPatch` final produit par Understanding cible ;
- aucune reply visible hors reply layer ;
- aucun write planning hors mutation/command service ;
- aucun import `legacy/` depuis `decision/` ;
- aucun retour de root wrappers supprimes.
