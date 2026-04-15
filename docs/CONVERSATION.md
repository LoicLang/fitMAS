---
summary: grounding conversationnel, hierarchie de verite, pipeline indications utilisateur et modules de contexte
read_when:
  - corriger un bug de contexte conversationnel
  - modifier api_messages.py
  - modifier heartbeat.py ou signals.py
  - ajouter un nouveau type de signal utilisateur
  - traiter une indisponibilite future, un signal sante ou un update d'execution
  - brancher des tools de lecture pour le coach Telegram
---

# Conversation

## But

Rendre le coach Telegram factuellement fiable et reactif quand il parle de ce qui a ete fait, de ce qui etait prevu, et du contexte temporel.

Le sujet n'est pas d'ajouter "plus de contexte" au LLM.
Le sujet est de lui donner une verite structuree et parcimonieuse.

## Priorite relative

Le gros du grounding conversationnel est pose.
La priorite repo-wide a bouge vers substrate partage et weekly reality digest.
Voir `BUILD-ORDER.md`.

---

## Hierarchie de verite

Ordre strict pour le coach :

1. activite reelle persistee (`Activity`)
2. declaration explicite utilisateur dans le message courant
3. correction explicite recente dans la conversation
4. seance planifiee (`ScheduledSession`)
5. heuristique faible

Regle :
- le coach ne presente jamais 4 ou 5 comme un fait si 1, 2 ou 3 disent autre chose
- une confirmation future (`demain piscine j'y serai`) ne declenche pas de mutation si le planning est deja coherent
- si l'utilisateur aligne `demain` avec un jour explicite, le systeme repond avec la date absolue

## Sources de verite

| Source | Force | Usage | Limites |
|--------|-------|-------|---------|
| `Activity` | Plus forte sur le reel | Sport, duree, distance, FC, TSS, date, lien session | Pas toujours rattachee a une seance |
| `ScheduledSession` | Plus forte sur le plan date | Seance prevue, sport, duree cible, statut | Statut centre sur le prevu, pas le reel hors plan |
| `CoachMessage` | Contexte conversationnel | Derniere consigne, correction, referents | Historique trop brut si pas structure |
| `UserFact` | Contraintes stables | Dispo, preferences, patterns | Pas un journal d'activite |
| `WeeklyPlan`/`DayPlan` | Template/compat seulement | Generation planner, onboarding | Ne doit plus etre verite runtime |

---

## Pipeline indications utilisateur

Un message utilisateur n'est pas une instruction directe.
Avant toute mutation, FitMAS produit un objet structure.

### Flux

1. **Interpreter** — `user_indication_llm.py` produit un `UserIndication` structure
2. **Grounder** — `planning_window_resolution.py` ancre la contrainte contre le vrai planning
3. **Decider** — `replan_from_life_change.py` ou `adaptation.py` produisent des actions autorisees
4. **Expliquer** — `llm.py` formule la reponse naturelle

### Triage du tour

`conversation_turn_planner.py` ajoute un routage LLM read-only avant les side-effects d'execution.

Role :
- detecter l'intention principale du tour
- conserver les intentions secondaires quand le message est compose
- proteger les demandes de mutation implicites (`vendredi a la place ?`) que les marqueurs deterministes ne savent pas fiabiliser

Interdits :
- aucun write DB
- aucune reply finale
- aucune mutation planning

Le resultat sert de gate d'orchestration. Si le routeur marque `plan_mutation`, un claim de non-completion reste du contexte et ne peut pas skipper la seance avant arbitrage.
Cette intention structuree est aussi transmise a `llm.decide()` pour choisir la prompt policy et le budget de tools quand les heuristiques lexicales seraient trompeuses.

Pour les contraintes de disponibilite, les reponses deterministes `week_scope` et `no_candidate` deviennent aussi du grounding quand le routeur classe le tour comme `availability_constraint` ou `plan_mutation`.
Le LLM formule alors la reponse finale avec ce contexte. Si le LLM ne rend pas de decision valide, l'orchestrateur conserve la reponse deterministe comme fallback.

### Types d'indication

| Type | Exemples | Comportement |
|------|----------|-------------|
| `availability_constraint` | Indispo ponctuelle, voyage, creneau impossible | Resolve planning window → replan si seance cible claire |
| `health_signal` | Douleur, gene, fatigue locale | Normalise signal → ecrit fait sante → adaptation protective |
| `execution_update` | Activite faite, correction | Reconcile le reel → claims d'activite / memoire courte |

### Implementation dans api_messages.py

1. Presque tous les messages non triviaux passent par le parseur structure
2. Si `health_signal` fort : ecrit fait sante → adaptation protective → fallback conservateur si LLM ne sort rien de propre
3. Si `availability_constraint` future : resolve fenetre → replan borne → repond honnetement si rien a bouger
4. Sinon : pipeline conversation normal

Comportements importants :
- `voyage`, `deplacement` = `availability_constraint`
- `demain soir` sans seance cible ne doit jamais inventer une mutation sur un autre jour
- `douleur epaule + natation` force adaptation hors natation
- reponse courte a clarification (`oui`/`non`) interpretee dans le contexte de la question precedente
- si un message combine un claim d'execution et une demande explicite de mutation (`swap`, `echange`, `decale`, `deplace`, `remplace`, `change`), le claim enrichit le contexte mais ne produit pas de reply finale et ne doit pas muter la seance avant arbitrage LLM
- les contestations d'execution pures peuvent encore etre resolues par l'orchestrateur, mais les messages composes donnent la priorite a l'intention de mutation

---

## Modules de grounding

| Module | Role | Etat |
|--------|------|------|
| `execution_context.py` | Resume prevu vs reel sur la journee | Pose, pur, teste |
| `execution_evidence.py` | Preuve prudente (observed/claimed/candidate/none) | Pose, utilise par heartbeat |
| `execution_clarification.py` | Demande `faite ou non ?` quand l'incertitude est structurante | Pose |
| `temporal_resolver.py` | Resout aujourd'hui/demain/hier/ce soir depuis timezone user | Pose, pur, teste |
| `activity_claims.py` | Extrait sport/duree/date/certitude des messages | Pose, fusionne claims, teste |
| `conversation_context.py` | Assemble minimum utile pour le LLM | Pose, utilise par api_messages |
| `calibration_needs.py` | Detecte trous d'info qui changent la qualite du plan | Pose, branche heartbeat + messages |
| `user_indications.py` | Contrat ferme des signaux user | Pose |
| `user_indication_llm.py` | Extraction structuree LLM | Pose |
| `planning_window_resolution.py` | Grounding contrainte future contre planning reel | Pose, aussi tool read-only |

## Ce que le LLM recoit

Oui :
- `temporal_context`
- `today_execution_context`
- `recent_activity_context`
- `relevant_timeline_context`
- `recent_user_corrections`
- `calibration_need` eventuel (comme doute interne, pas question formulaire)

Non :
- tout l'historique brut
- toute la DB brute
- tout le plan brut

---

## Trous restants

1. **Digest hebdo** — manque un digest canonique de semaine pour eviter de recomposer transcript + activites + events a plusieurs endroits
2. **Referents** — a dogfooder : est-ce que `30 min`, `celle de demain`, `la piscine` restent ambigus ?
3. **Tools** — garder bornes, ne pas exposer trop de catalogue avant d'avoir stabilise les besoins reels
4. **Claims temporels** — observer si d'autres claims meritent la meme approche que les claims d'activite
5. **Chemins compat** — `WeeklyPlan`/`DayPlan` ne doivent plus etre lus comme verite runtime

## Regles non negociables

- le coach ne dit jamais "rien fait" si une activite reelle existe dans la fenetre pertinente
- une correction utilisateur immediate prime sur la duree planifiee
- `aujourd'hui` et `demain` resolus depuis le temps local exact
- un prompt ne remplace pas un tool de verite
- le LLM n'ecrit jamais directement en memoire
- les mutations passent toujours par les orchestrateurs
- les detecteurs de claims ne doivent pas voler le tour quand le message contient aussi une intention planning explicite

## Anti-patterns

- laisser le LLM choisir seul la seance du futur sans grounding
- parser toute la langue naturelle avec des regex
- muter le plan directement depuis une extraction LLM
- ecrire un signal utilisateur flou en memoire durable
- appliquer un side-effect DB avant que l'intention principale du tour soit arbitree
