---
summary: refactor planning snapshot pour redonner au LLM une vue semaine complete avant compilation PlanPatch
read_when:
  - refactorer l'adaptation planning conversationnelle
  - corriger un coach qui bricole avec move/swap sans vision globale
  - diagnostiquer repos actif, TSS, charge ou incoherence planning
  - modifier le pipeline plan_mutation ou adaptation candidates
---

# Planning Snapshot Adaptation Refactor

## Diagnostic

Le probleme observe le 13 mai n'est pas seulement une erreur de prompt.

Sur le scenario :

```text
courbatures + seance du jour
-> demande deplacement vendredi
-> proposition running demain + piscine vendredi
-> correction "indispo aujourd'hui mais dispo demain"
```

FitMAS donne encore au LLM une realite trop morcelee :

- tools de lecture separes ;
- candidats `move/swap/lighten/replace` produits trop tot ;
- memoire disponibilite ancienne encore active ;
- distinction floue entre `repos total`, `repos actif`, recovery et seance non scoree ;
- validation qui raisonne parfois sur sport/type, parfois sur charge, parfois sur texte.

Un LLM qui recoit directement un planning propre + une indisponibilite sait
souvent proposer une adaptation raisonnable. FitMAS casse cette latitude quand
il lui demande de reconstruire la semaine par tools, de choisir des operations,
de respecter le JSON final, puis de parler comme coach dans le meme tour.

## Decision d'architecture

Restaurer l'ordre naturel :

```text
TurnPlan type
-> PlanningSnapshot complet
-> LLM AdaptationProposal sans tools d'ecriture
-> backend compiler Proposal -> PlanPatch
-> validation / simulation / policy
-> confirmation ou commit
-> final reply factuelle
```

Les tools `move_session`, `swap_sessions`, `replace_session`, `lighten_day`
restent utiles, mais ils deviennent un langage d'execution/compilation, pas le
support principal du raisonnement sportif.

## Frontieres

### LLM

Le LLM peut :

- lire un snapshot complet ;
- arbitrer sportivement ;
- proposer un compromis ;
- expliciter ses hypotheses ;
- demander une clarification ciblee si une information bloque vraiment.

Le LLM ne peut pas :

- commit en DB ;
- inventer des IDs ;
- produire une reponse finale avant validation ;
- choisir depuis le texte libre par regex ou mots-cles ;
- contourner la validation backend.

### Backend

Le backend doit :

- assembler la verite planning/memoire dans un snapshot unique ;
- compiler les operations proposees vers des IDs reels ;
- valider coherence, conflits, repos, charge et disponibilite ;
- creer pending/commit/event ;
- composer une reponse qui ne claim que ce qui est reellement applique ou propose.

## Artefact 1 — PlanningSnapshot

Objectif : donner au LLM une semaine lisible, complete et non contradictoire.

Contrat cible :

```json
{
  "snapshot_id": "plan_123:v7:2026-05-13T18:00:00+02:00",
  "user_timezone": "Europe/Paris",
  "horizon": {
    "start": "2026-05-13",
    "end": "2026-05-19"
  },
  "week_mission": {
    "goal": "garder la regularite sans cramer la recuperation",
    "protected_sessions": ["session:run_long_sunday"],
    "minimum_success": "2 footings + 1 natation technique"
  },
  "days": [
    {
      "date": "2026-05-15",
      "day_kind": "active_recovery",
      "is_full_rest": false,
      "load_score": 8,
      "load_kind": "scored_low",
      "items": [
        {
          "ref": "session:15",
          "session_id": 15,
          "sport_type": "mobility",
          "session_type": "recovery",
          "role": "recovery",
          "title": "Repos actif",
          "duration_min": 25,
          "load_score": 8,
          "load_kind": "scored_low",
          "details": "mobilite + marche legere",
          "status": "planned",
          "movability": "flexible"
        }
      ]
    }
  ],
  "active_constraints": [
    {
      "kind": "availability_unavailable",
      "scope": "general",
      "starts_on": "2026-05-13",
      "ends_on": "2026-05-13",
      "status": "open",
      "freshness": "confirmed"
    }
  ],
  "health": [],
  "recent_events": []
}
```

Principes :

- le snapshot est assemble par le backend depuis la DB et les artefacts LLM deja
  types ;
- aucune comprehension deterministe du texte utilisateur ;
- les refs exposees au LLM sont stables pour le tour ;
- le snapshot contient assez d'information pour raisonner sans rappeler 8 tools.

## Invariant repos / charge

Le bug `repos actif sans TSS mais avec detail` doit devenir impossible ou
explicite.

Regles domaine :

- `rest_total` : pas de detail seance, pas de duree, charge 0 ;
- `active_recovery` : detail autorise, duree autorisee, charge faible ;
- `unscored_recovery` : autorise seulement avec `load_kind="unscored_recovery"`
  et raison machine explicite ;
- toute seance sportive avec duree/intensite doit avoir soit une charge, soit
  une raison machine de non-score ;
- les validators raisonnent sur `day_kind` / `load_kind`, pas sur le label
  texte "repos".

## Artefact 2 — AdaptationProposal

Le LLM ne produit pas directement le `PlanPatch` final sur les demandes larges.
Il produit une intention structurée de planning.

Contrat cible :

```json
{
  "response_type": "adaptation_proposal",
  "summary": "ne pas forcer aujourd'hui, deplacer le running a demain, garder la piscine vendredi",
  "operations": [
    {
      "op": "move",
      "source_ref": "session:13",
      "target_date": "2026-05-14",
      "target_slot": "any",
      "reason": "courbatures aujourd'hui, disponibilite confirmee demain"
    },
    {
      "op": "move",
      "source_ref": "session:14",
      "target_date": "2026-05-15",
      "target_slot": "any",
      "reason": "liberer jeudi pour le running et garder une charge faible"
    },
    {
      "op": "keep",
      "source_ref": "session:16",
      "reason": "preserver le repos total samedi"
    }
  ],
  "protected": [
    {
      "source_ref": "session:17",
      "reason": "garder le footing long de dimanche si la recuperation tient"
    }
  ],
  "assumptions": [
    "demain est disponible",
    "les courbatures restent legeres"
  ],
  "clarification_question": null,
  "requires_confirmation": true,
  "confidence": 0.82
}
```

Le LLM peut demander une clarification, mais seulement si elle bloque vraiment :

```json
{
  "response_type": "needs_clarification",
  "clarification_question": "Tu confirmes que demain est bien disponible ?",
  "missing": ["availability:2026-05-14"]
}
```

Le pipeline ne doit plus avoir besoin de blacklister des phrases comme :

```text
Je te fais une proposition plus tard.
Je te dis vite.
On verra apres.
```

Le bon garde-fou n'est pas une liste de formulations interdites. C'est le
contrat de sortie : une demande large produit soit `AdaptationProposal`, soit
`needs_clarification`. La reponse visible est ensuite composee depuis une
proposition, une pending ou un event reel. Si aucun artefact n'existe, le coach
ne doit pas parler comme si un travail asynchrone etait lance.

## Artefact 3 — ProposalCompiler

Le compiler backend transforme `AdaptationProposal` en operations reelles :

```text
source_ref -> ScheduledSession.id
target_date -> date locale valide
op move/swap/keep/replace/lighten -> PlanPatch
PlanPatch -> simulation -> policy
```

Si une operation est impossible :

- le compiler retourne une erreur structuree ;
- le coach explique le blocage reel ;
- il ne transforme pas l'echec en menu ouvert.

Exemples :

```text
UNKNOWN_REF
TARGET_DATE_UNAVAILABLE
SESSION_ALREADY_DONE
WOULD_BREAK_FULL_REST
WOULD_OVERLOAD_WEEK
```

## Pipeline conversation cible

### Cas simple explicite

```text
"echange mardi et mercredi"
-> TurnPlan type
-> PlanningSnapshot court
-> direct compiler swap
-> validation
-> pending/commit
```

### Cas large / imprevu

```text
"je suis courbature, on adapte la semaine ?"
-> TurnPlan type health + plan_mutation
-> memoire sante action-only
-> PlanningSnapshot complet
-> AdaptationProposal LLM
-> ProposalCompiler
-> validation/policy
-> confirmation
```

### Cas disponibilite corrigee

```text
"non j'etais indispo aujourd'hui mais demain je suis dispo"
-> TurnPlan availability_constraint type
-> memory action: available demain
-> memory service resolve old overlapping unavailable
-> snapshot refresh
-> reprise de la proposition pending/proposed si elle existe
```

## Comportement cible sur le scenario du 13 mai

Apres correction, la conversation doit converger vers :

```text
running demain
piscine vendredi
repos total samedi preserve
running dimanche conserve si recuperation OK
```

Le coach doit :

- ne pas forcer aujourd'hui ;
- ne pas utiliser une ancienne indispo "aujourd'hui et demain" apres correction ;
- ne pas affirmer un move sans event/pending ;
- ne pas promettre une proposition asynchrone inexistante ;
- demander au maximum une clarification ciblee : "tu confirmes demain dispo ?"

## Migration par tranches

### Tranche 0 — Stabilisation dogfood restante

But : fermer les regressions vues avant le refactor lourd.

- memory hygiene : `available` resolve les `unavailable` ouverts qui overlap ;
- retirer l'autorite disponibilite de l'ancien extracteur legacy ;
- claim guard minimal : pas de mutation annoncee sans event/pending ;
- plan lookup composer applique meme si `CoachDecision.response_type="reply"`.

Etat 13 mai 2026 :

- `available` resout maintenant les indisponibilites ouvertes qui overlapent la
  fenetre confirme disponible ;
- l'ancien `extract_facts` legacy ne peut plus ecrire `category=availability` ;
- pas de hard guard textuel "promesse async" ajoute : le probleme doit etre
  resolu par le contrat `AdaptationProposal | needs_clarification`, pas par
  blacklist de formulations.

### Tranche 1 — Snapshot builder

Creer un module pur :

```text
planning_snapshot.py
```

Responsabilites :

- lire `ScheduledSession`, facts actifs, working memory, events recents ;
- normaliser `day_kind`, `load_kind`, `role`, `movability` ;
- exposer des refs stables ;
- produire un diagnostic si repos/charge est incoherent.

Ajouter un endpoint/debug CLI pour dumper le snapshot d'un user/date.

Etat 13 mai 2026 :

- module `planning_snapshot.py` ajoute ;
- `PlanningSnapshot` expose les jours, items, contraintes disponibilite actives,
  diagnostics et refs `session:*` ;
- un `rest/rest` avec detail ou duree et charge 0 sort comme
  `active_recovery` + `load_kind=unscored_recovery`, avec diagnostic
  `REST_WITH_SESSION_CONTENT`.

### Tranche 2 — Invariants repos / charge

Durcir generation et cleanup :

- aucun `rest_total` avec detail de seance ;
- `active_recovery` score faible ou `unscored_recovery` explicite ;
- tests sur generated week ;
- migration/cleanup des rows existantes incoherentes.

### Tranche 3 — AdaptationProposal compiler LLM

Ajouter un appel JSON-only sans tools :

```text
snapshot + TurnPlan + user message
-> AdaptationProposal
```

Ce compiler remplace le raisonnement par tools pour les demandes larges.

Etat 13 mai 2026 :

- module `adaptation_proposal.py` ajoute ;
- `generate_adaptation_proposal()` appelle le LLM en JSON-only avec le snapshot ;
- la gateway preserve les schemas custom `AdaptationProposal` au lieu de les
  normaliser en `CoachDecision` ;
- le pipeline conversation epingle ce mini-compiler sur `deepseek-v4-flash` :
  l'artefact est borne, puis compile/valide par le backend, donc le modele fort
  n'est pas necessaire ici et s'est montre plus lent/plus vide en replay ;
- le `schema_hint` est maintenant un schema `AdaptationProposal` explicite, pas
  seulement le nom du schema ;
- `summary` peut etre reconstruit depuis les raisons d'operations quand le LLM
  fournit des operations valides mais oublie le champ.

### Tranche 4 — ProposalCompiler backend

Transformer `AdaptationProposal.operations` en `PlanPatch`.

Reutiliser :

- `PlanMutationService` ;
- `plan_patch_candidate_evaluator` ;
- `week_coherence` ;
- pending confirmation existant.

Etat 13 mai 2026 :

- `compile_adaptation_proposal()` compile `move`, `swap`, `keep` vers
  `PlanPatch` ;
- les refs inconnues bloquent sans guessing ;
- les moves de recovery non scoree encodee en `rest/rest` sont ignores pour ne
  pas bloquer les operations sportives principales tant que `active_recovery`
  n'est pas first-class ;
- une chaine `move A -> jour de B` + `move B -> autre jour` est compilee en
  `swap(A,B)` + `move(B, autre jour)`, ce qui evite un faux blocage sur l'etat
  initial ;
- un `move A -> jour occupe par B` sans operation explicite pour B devient un
  `swap(A,B)`. Le LLM garde donc la latitude sportive, et la validation/policy
  decide ensuite si ce swap doit etre confirme ou bloque ;
- l'evaluator preserve les metadonnees d'un patch unique (`coach_message`,
  `confirmation_reason`) au lieu de les remplacer par le wrapper candidate.

### Tranche 5 — Brancher `plan_mutation`

Routage :

- demande explicite simple -> compiler direct possible ;
- demande large / imprevu / "readapte" -> snapshot proposal flow ;
- ancienne candidate-flow gardee fallback puis retiree si smokes OK.

Etat 13 mai 2026 :

- la conversation tente maintenant le flow snapshot apres les exits typed
  existants (`empty target`, `no affected sport session`) et avant l'ancien
  generator candidate ;
- `health_signal` en intention secondaire ne bloque plus le snapshot-flow
  pre-`decide()` quand `primary_intent=plan_mutation` ;
- si le snapshot LLM ne produit rien ou compile mal, l'ancien candidate-flow
  reste fallback ;
- replay API cible "running demain et piscine vendredi" : le snapshot-flow
  prend la main, compile 2 operations, et cree une pending confirmation sans
  passer par le legacy generator ;
- `pending_resolution=ignore` garde maintenant la pending active. Un follow-up
  du style "donc je force ?" peut etre traite comme question/clarification sans
  supprimer la proposition en attente ;
- les facts fournis au composer final incluent les operations et dates DB
  (`swap_sessions session:13 running/easy 2026-05-13 <-> session:14 ...`) pour
  limiter les derives de jours relatifs dans la reponse visible.

### Tranche 6 — Replays reels

Scenarios minimum :

- courbatures + move vendredi + running demain/piscine vendredi ;
- indispo natation 2 semaines avec seances swimming ;
- indispo natation 2 semaines sans seance swimming ;
- "echange mardi et mercredi" ;
- "j'ai fait la seance aujourd'hui" ;
- "la douleur est passee" ;
- generation semaine avec repos actif et charge coherente.

## Tool / skill decomposition

Deterministe et reutilisable :

- `build_planning_snapshot(user_id, start, end)` : module partage + futur
  read-only tool ;
- `compile_adaptation_proposal(proposal, snapshot)` : module domaine pur ;
- `validate_snapshot(snapshot)` : diagnostic charge/repos/memoire.

Workflow multi-step :

- `adapt_plan_from_snapshot` : skill/pipeline orchestration
  `TurnPlan -> Snapshot -> Proposal -> Compiler -> Validation -> Pending`.

Centralisation :

- API, Telegram, CLI et tests doivent consommer le meme snapshot ;
- pas de snapshot recompose differemment dans le prompt, le tool runtime et la
  final reply.

## Risques

| Risque | Mitigation |
|--------|------------|
| Snapshot trop gros | horizon 7-10 jours par defaut, details compresses, refs stables |
| LLM propose operation impossible | compiler retourne erreur structuree, pas de commit |
| Refactor trop large | garder candidate-flow fallback jusqu'aux replays OK |
| Duplication avec Phase B | rester sur adaptation Phase A, pas prescription/progression |
| Memoire stale | freshness/valid_until visibles dans snapshot + hygiene avant snapshot |

## Definition of Done

- Le scenario du 13 mai converge sans timeout.
- Le coach propose un patch concret ou une clarification unique.
- Aucune phrase ne claim une mutation sans `pending` ou `plan_mutation_event`.
- Les anciennes indispos resolues ne polluent plus le raisonnement.
- Le repos actif est represente comme charge faible ou recovery non scoree
  explicite, jamais comme repos total ambigu.
- Les tests backend passent et les replays API reels documentent le resultat.

## Replays reels du 13 mai

Setup : fausse DB, `FITMAS_OVERRIDE_NOW_ISO=2026-05-13T18:46:00+02:00`,
vrais appels LLM DeepSeek via `TestClient`.

Resultats observes apres les raffinements :

- premier tour courbatures + demande deplacement vendredi :
  `response_mode=plan_adaptation_pending_confirmation`,
  `planning_snapshot_flow.proposal=compiled`, `operation_count=1`, pending
  creee sans legacy generator ;
- la reponse propose un swap confirme, sans claim de commit ;
- la pending garde un resume humain base sur l'intention LLM, pas un warning
  technique de validator ;
- un follow-up "Donc je force pour la mettre aujourd'hui ?" repond clairement
  que non. Quand le LLM sort `pending_resolution=ignore`, la pending reste
  active au lieu d'etre supersedee par le cleanup final.

Point restant observe : la formulation visible peut encore etre perfectible
("plusieurs seances de natation possibles") selon le run. Structurellement le
tour est maintenant stable : artefact compile, validation, pending, pas de
mutation annoncee sans event.
