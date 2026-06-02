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

Verifie offline le 31 mai 2026 :

```text
tests/runtime_v0 + docs   : 160 passed
fake matrix               : 11/11
guard fallback rate       : 0 %
wrong_write               : 0
old_plan_date             : 0
wrong_correction_target   : 0
reply_claim_without_event : 0
```

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

Budget runtime core, hors tests et scripts :

```text
objectif sain: <= 2500 LOC
zone acceptable: 2500-3200 LOC
> 3200 LOC: justification obligatoire
> 4000 LOC: alerte architecture lourde
```

Mesure 2 juin 2026 : 3194 LOC (zone acceptable, plus dans l'objectif sain).

## Sport Core V0

`backend/src/fitmas/runtime_v0/sport_rules.py` centralise les premiers
garde-fous :

- source `done` protegee ;
- hard proche d'un hard/long bloque ;
- fact `health` actif bloque une creation de hard ;
- multi-operation demande confirmation ;
- seance `key` demande confirmation ;
- `swap` (restructuration du calendrier) demande confirmation.

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
