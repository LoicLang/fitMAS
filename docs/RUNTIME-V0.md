---
summary: reference courte du prototype Runtime V0 et de ses preuves actuelles
read_when:
  - modifier backend/src/fitmas/runtime_v0
  - lancer la matrix provider V0
  - comparer le prototype au scope dogfood
  - verifier les limites d'isolation du noyau V0
---

# Runtime V0

## Role

`backend/src/fitmas/runtime_v0/` est le noyau experimental qui a valide la
troisieme voie :

```text
LLM propose
backend valide
executor commit
audit prouve
guard protege la reply
```

Il reste un laboratoire stable tant que l'integration produit n'est pas prouvee.
Le scope produit vit dans `docs/V0-DOGFOOD-SCOPE.md`.
La migration vit dans `docs/RUNTIME-MIGRATION-PLAN.md`.

L'ancienne spec longue est archivee :

```text
docs/archive/runtime-v0-implementation-spec-2026-05-24.md
```

## Boucle

```text
InputEvent
-> WorldSnapshot
-> CoachAgent
-> ActionProposal
-> RuntimePolicy
-> CommandExecutor
-> RuntimeResult
-> ReplyComposer
-> OutputGuard
-> Audit
```

## Voix Et Garde

Le partage est strict : la voix vit dans le reply LLM, la verite dans le guard.

`ReplyComposer` fait passer tous les cas par le LLM — confirmation, question,
blocage, reponse plan, commit d'execution. Les templates ne servent plus de
reponse par defaut. Ils restent seulement :

- comme filet `_fallback` quand le LLM echoue ou se tait. Le filet rend la
  meilleure verite disponible (mutation resumable, puis pending, blocage,
  clarification, plan), jamais le message technique sec tant qu'on a mieux. Il
  ignore les commandes de bookkeeping (etat conversation, creation de pending)
  qui n'ont pas de resume utilisateur ;
- pour reformuler une reponse plan qui omet une seance lue (re-prompt une fois) ;
- pour garantir qu'un commit reel enonce son fait porteur (`_commit_summary`).

Le commit d'execution suit la meme doctrine que le plan : on ne verifie plus un
verbe template ("note", "corrige") mais le **fait qui porte la verite** du
commit — la duree (nombre), le jour cible (jour de semaine) ou le sport. Si la
voix du LLM enonce ce fait, on la garde telle quelle. Sinon on re-prompte une
fois, puis on retombe sur le resume deterministe. Quand aucun fait robuste n'est
exigible (un `skipped` sans duree), on fait confiance a la voix : le guard reste
seul juge qu'elle ne ment pas sur le commit.

`OutputGuard` lit la sortie du modele, jamais le texte utilisateur, et rend un
oui/non. Sur non, il bloque et retombe sur `_safe_reply`. Raisons actuelles :

```text
claim_without_event     reply annonce un write alors que committed_events vide
pending_action_claim    reply dit "c'est fait" sur un simple pending
internal_jargon          fuite policy/backend/runtime ou nom de tool (get_/propose_)
meta_opening             fuite "l'utilisateur"/"the user" (debut ou milieu)
english_leak             fuite anglaise (let me, your session, i'll...)
raw_json_visible         accolades ou cles machine visibles
technical_id_visible     session_id/source_ref visibles
truncated_reply          reply coupee net (finit par avec/et/pour/:)
unsupported_date         date hors read_facts sur un answer_only
old_plan_date            date > 7 jours dans le passe et hors read_facts
```

`guard fallback rate` est une gate dogfood (< 15 %) : il mesure le cout de la
verite sur le naturel. Sur la fake matrix il reste a 0 %.

## Isolation

Le noyau V0 ne doit pas importer :

```text
fitmas.decision
fitmas.domain
fitmas.llm
fitmas.skills
fitmas.tools
fitmas.app
```

Adapters vers le produit existant doivent vivre a part.
Ils peuvent dependre de l'existant, mais le noyau doit rester testable offline.

## Scenarios Actuels

```text
current_plan
tomorrow
skipped_yesterday
execution_correction
followup_planning_turn1
key_session_pending
explicit_lighten
replace_by_easy_bike
hard_unsafe_block
partial_yesterday
undo_wrong_status
```

`followup_planning_turn2` existe aussi comme tour de continuation, hors matrix
par defaut (lancer via `--scenario followup_planning_turn2`).

Scenarios couche 2 (hors matrix, juges par sonde live + etat DB) :
`move_today_open_week` (indispo + deplacement) et `health_resolution` (douleur
passee -> resolution de fact).

Commandes :

```bash
pytest tests/runtime_v0

python3 scripts/v0_eval/run_matrix.py \
  --provider fake \
  --repetitions 1 \
  --export-dir exports/runtime-v0/stability-fake-final

python3 scripts/v0_eval/run_matrix.py \
  --repetitions 5 \
  --export-dir exports/runtime-v0/stability-providers-5x
```

## Derniere Preuve

Verifie offline le 5 juin 2026 :

```text
tests/runtime_v0 + docs   : 201 passed
fake matrix               : 11/11
guard fallback rate       : 0 %
wrong_write               : 0
old_plan_date             : 0
wrong_correction_target   : 0
reply_claim_without_event : 0
```

Construit depuis le 31 mai : moteur Meso (`meso/`, voir plus bas), resolution de
fact (`propose_fact_resolution` -> `resolved_at`, retracte une douleur passee),
fact-rider (un tour note un fait durable ET agit). Couche 2 : indispo enfin notee,
note+act prouve sur la douleur, resolution 4/4 (DeepSeek).

Sonde DeepSeek 1x (voix libre, 31 mai 2026) : les commits d'execution passent
desormais par la voix du LLM (`execution_correction`, `undo_wrong_status`,
`partial_yesterday` rendus chaleureux et porteurs du fait ; `skipped` parfois
terse, choix du modele et non override). Aucun write dangereux, aucun
`claim_without_event` sur les sondes. Un bug de filet a ete corrige : sur un
tour pending/clarification, un echec du reply LLM tombait sur le message
technique sec a cause de la commande de bookkeeping committee ; le filet rend
maintenant la confirmation pending ou la clarification (`sanitized_fallback`
2 -> 0). En 1x DeepSeek reste non-deterministe sur quelques tours
(`skipped_yesterday`, `followup_planning_turn1`) : il echoue alors en **under-
action sure** (`no_send`/`answer` au lieu d'une mutation), jamais en write
errone. Pour un chiffre de correctness stable, lancer la matrix en 5x.

Provider matrix : le chiffre historique `114/120` vient d'une run a
6 scenarios (4 providers x 6 x 5 reps = 120). La matrix par defaut compte
aujourd'hui 11 scenarios x 3 providers cibles (165 runs en 5x). Gemini reste
disponible en opt-in manuel, mais n'est plus lance par defaut tant que le
credit API est absent. L'export
`exports/runtime-v0/stability-providers-5x/` n'est pas committe. A rejouer
pour un chiffre provider a jour :

```bash
python3 scripts/v0_eval/run_matrix.py --repetitions 5 \
  --export-dir exports/runtime-v0/stability-providers-5x
```

Les echecs provider restants observes etaient surtout des artifacts manquants
ou replies hors contrat, pas des writes dangereux.

Real-turn spike : `scripts/v0_eval/spike_real_turn.py` reconstruit maintenant
les sessions depuis les lignes de grounding capturees dans
`conversation_turns.context_json` quand elles existent. Cela evite de juger un
provider sur `scheduled_sessions` deja mute apres le tour. Les facts, sessions
et activites crees apres `as_of` sont exclus. Si aucun grounding capture n'est
disponible, le spike retombe sur `current_state` et ce resultat ne doit pas
servir a blamer un provider.

Cas #151 (`Echange aujourd'hui et demain`) : avec le contexte capture, DeepSeek,
Grok et Mistral produisent tous un `plan_patch`. L'ancien diagnostic
`planning_date_not_resolved` venait du banc de replay, pas des modeles. La
difference de policy restante — V0 auto-committait le swap simple alors que
l'app demandait confirmation — est corrigee : un `swap` passe maintenant en
`pending` (`swap_requires_confirmation`). Verifie sur les tours `Echange`
#133/#151 x 3 providers : `unsafe_auto_commit` 6 -> 0, tous `tie_safe`.

Comparaison app-vs-V0 :

```bash
python3 scripts/v0_eval/compare_app_vs_v0.py \
  --real-db .tmp-prod-fitmas.db \
  --turn-ids 151 \
  --providers deepseek,grok,mistral \
  --max-steps 6 \
  --export-dir exports/runtime-v0/app-vs-v0
```

Le rapport classe chaque run en `v0_better`, `app_better`, `tie_safe`,
`tie_bad` ou `inconclusive_snapshot`. Il ne considere pas l'app legacy comme
oracle absolu : il compare les risques (`unsafe_auto_commit`,
`app_claim_without_event`, `unhelpful_no_send`, etc.) sur le meme snapshot
capture.

## Evaluation

La doctrine de test (deux couches) vit dans `docs/V0-TEST-DOCTRINE.md` : la
matrix est le filet mecanique (couche 1), la simulation sous-agent juge la
qualite reelle (couche 2). Ci-dessous le detail du scoring matrix.

La matrix separe deux niveaux :

```text
correctness = proposal, policy, commands, dates finales et danger metrics
reply quality = wording visible attendu ou interdit
```

Le wording visible ne fait plus echouer la correctness.
Il alimente les compteurs `reply_quality_issue_count`,
`reply_missing_expected_text_count` et `reply_contains_forbidden_text_count`.
Les claims dangereux restent bloquants, par exemple une reply qui annonce une
mutation sans event committe.

Depuis la liberation de la voix, les oracles de wording ciblent le **fait
porteur** (la duree, le jour, le sport) en `must_include` et un jeu d'accuses de
reception en `any_include`, pas le verbe template ("corrige", "partiel"). Exiger
un mot que la voix libre n'emploie plus reviendrait a tester un artefact mort.
Les garde-fous dangereux (`nouvelle seance`, `ajoute`) restent en
`must_not_contain`.

## Budget

Budget runtime core (hors `adapters/`, tests et scripts). Le budget est un
**filet de danger contre le creep, pas une boussole** : il bloque l'accumulation
de regles, jamais une capacite gagnee et prouvee.

Re-baseline 7 juin 2026 (decision Loic). Le `<= 2500` historique visait le
**noyau conversationnel nu**. Depuis, le **moteur Meso** (semaine typee +
verificateur + generateur + `propose_week`) est une **seconde enveloppe
deliberee** qui co-evolue avec le runtime (`PLANNING-V0.md`). Ces LOC sont
**acquises, pas du creep** ; on ne les gratte pas. La passe de simplification
prevue avant Slice 3b est resolue **en re-baseline** : `meso/` + cablage sont deja
serres (chaque piece est utilisee ou est un seam documente pour 3b / 2.1 / Macro).

```text
noyau conversationnel V0 (boucle, hors meso/): cible ~2500, garder la pression
moteur Meso (meso/ + cablage week_proposal): enveloppe dediee, acquise
cap dur (test_import_boundaries): 4337
> cap: justification de CAPACITE obligatoire (jamais du creep), bump au landing
```

Mesure 7 juin 2026 (Slice 3b landing) : ~4273 LOC. Discipline maintenue : le cap
ne monte que sur capacite prouvee, justification loggee dans `test_import_boundaries`.
Slice 3b (pending_resolution, resolve_pending tool, v0_planned_weeks store, week
commit handler, forward chaining) = capacite prouvee, pas du creep.

4320 -> 4337 (8 juin 2026) : ré-adaptation same-turn sous blessure (tranche #1) —
`propose_week` gagne le param declare `intensity_restricted: bool` (le LLM declare la
contrainte ; le verif tient l'autorite) + supersede du pending ouvert
(`executor._apply_create_pending`, status `superseded`). 253 tests, matrix 11/11, danger 0.
Couche 2 (`probe_live_simulation --persona blessure`) confirmee : PASS, juge LLM 5/5/5/5. Spec :
`docs/superpowers/specs/2026-06-08-readapt-blessure-same-turn-design.md`.

## Sport Core V0

`backend/src/fitmas/runtime_v0/sport_rules.py` centralise les premiers
garde-fous :

- source `done` protegee ;
- hard proche d'un hard/long bloque ;
- fact `health` actif bloque une creation de hard ;
- multi-operation demande confirmation ;
- seance `key` demande confirmation ;
- `swap` (restructuration du calendrier) demande confirmation.

## Moteur Meso (Slice 0/1/2.0)

`backend/src/fitmas/runtime_v0/meso/` co-evolue avec le runtime (doctrine et
ordre : `docs/PLANNING-V0.md`, `docs/BUILD-ORDER.md`). Le LLM genere/personnalise,
un verificateur deterministe tient l'autorite ; tout Meso reste `pending`.

- `model.py` : modele type d'une semaine (`TypedSession` / `PlannedWeek` /
  `WeekTarget` / `WeekActuals` / `TypedConstraint`), charge ponderee
  (duree x intensite), derivation de cible continuite depuis la semaine passee.
- `verifier.py` : `verify_week` deterministe, 5 proprietes (type-cle, anti-TSS-drop,
  ramp borne, espacement, sante) ; modes continuite / transition (hook), anti-drop
  contrainte-aware a venir en 2.1.
- `context.py` : bridge `fact -> TypedConstraint` (sante toujours incluse,
  conservateur d'abord). Seam du context-pack (Slice 2.0).

Pur domaine (pas de DB/LLM), prouve en fixtures dont le rejeu du "TSS qui chute"
de l'app. Suite : context-pack en couches (2.0) puis generateur `propose_week`
(2.1, ou se reglent note+act indispo + sur-promesse + TSS-vs-contrainte).

## Prochaine Evolution Autorisee

Dans le noyau V0 :

- scenarios dogfood proches ;
- guards/retry si prouves par matrix ;
- pas d'API Telegram directe.

Hors noyau V0 :

- adapters DB actuelle ;
- adapters executor vers writers existants ;
- endpoint/Telegram sous flag.

## Regle De Decision

Ne pas optimiser le style du runtime tant que les gates produit ne passent pas.
Chaque changement doit servir un scenario, une safety metric ou un adapter de
dogfood.
