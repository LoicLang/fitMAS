# FitMAS

Coach IA multisport proactif qui ajuste l'entrainement selon la vraie vie.

## Statut — 8 juin 2026 (soir) — V0 LIVE EN PROD

**V0 est le coach Telegram de Loïc depuis le soir du 8 juin 2026.**
`scripts/dogfood_telegram.py` remplace le legacy bot dans `scripts/start-prod`.
Legacy bot retraite. V0 store (`v0_*` sur le volume Fly) = source de verite du coaching.

Decision :

```text
repo actuel = enveloppe produit
runtime_v0 = noyau live (prod)
ancien pipeline = legacy retraite
```

La migration par etapes est **partiellement depassee** : l'adapteur de lecture
(`materialize_v0_db`) a ete utilise en one-shot pour le bootstrap ; la coexistence
write-adapter est devenue inutile puisque le legacy est retraite. FastAPI/webapp
tournent encore mais leurs donnees ne sont plus la verite du coaching.

## Cap Actuel

Phrase guide :

```text
Maintenir le plus petit coach Telegram fiable sur lequel Loïc s'appuie.
```

Le V0 dogfoodable doit :

- lire le bon plan ;
- noter et corriger l'execution ;
- adapter des seances simples ;
- demander confirmation pour les seances cles ;
- bloquer les mutations sportivement douteuses ;
- auditer chaque write ;
- rester LLM-first sur le texte utilisateur.

Ne pas ouvrir Phase B progression/prescription sans demande explicite.

## Preuve Runtime V0

Verifie offline puis deploye live le 8 juin 2026 :

```text
tests/runtime_v0 : 273 passed
fake matrix      : 11/11
danger metrics   : 0 wrong_write, 0 old_plan, 0 wrong_correction_target,
                   0 claim_without_event
core             : ~4496 LOC (cap 4496 ; noyau + moteur Meso + pont de plan —
                   enveloppe acquise (re-baseline), voir docs/RUNTIME-V0.md Budget)
```

Construit depuis : moteur Meso de bout en bout (`runtime_v0/meso/` — modele type +
verificateur deterministe constraint-aware, generateur LLM-first generate->verify,
context-pack), le tool coach `propose_week` (3a), et la **resolution de pending +
commit semaine** (3b : `pending_resolution`, store type `v0_planned_weeks`, chainage
forward). Le coach est enseigne qu'un « oui mais [contrainte] » n'est pas un accept.
**Tranche #1 livree + prouvee couche 2** : sur « oui mais [douleur/blessure] », le
coach note le fait sante ET re-propose une semaine sans intensite dans le **meme tour**
(probe DeepSeek : PASS, juge LLM 5/5/5/5).
**Tranche #2 livree + prouvee couche 2** : sur « oui mais [indispo jours] », le
coach note le fait availability ET re-propose une semaine avec REST sur les jours bloques
dans le **meme tour** (`blocked_days` declares, verificateur `_check_blocked_days`,
probe DeepSeek : PASS, juge LLM 5/5/5/5).
**`get_planned_week`** (read tool, relit la semaine committee).
**Reconciliation des 2 stores de plan + injury-after-commit (8 juin, soir)** : au commit d'une
semaine Meso, `_materialize_week_sessions` la pose sur le calendrier (`v0_scheduled_sessions` ;
replace planifie / preserve execute / saute rest) -> une seule verite du plan jour, le coach voit
enfin la semaine committee. Sur une **blessure signalee APRES commit**, il re-propose une semaine
sans intensite (sonde forced-ordering `probe_injury_after_commit` : PASS x2). Debloque l'execution
et le patch chirurgical sur une semaine generee. Root cause via systematic-debugging (le juge LLM
notait 5/5/5/5 un tour que l'oracle deterministe attrapait). Spec :
`2026-06-08-plan-store-reconciliation-design.md`.
**Deploy live prod (8 juin, soir)** : `scripts/dogfood_telegram.py` remplace le legacy
bot ; store bootstrap depuis les donnees reelles (`materialize_v0_db` : remap user_id,
faits legacy jetes, plan futur legacy supprime) ; Strava->V0 sync active
(`runtime_v0/adapters/strava_v0_sync.py`, job 900 s, verifie live ~100 activites).
**Lacunes connues** : run<->session non matchees auto ; voix terse ; propose_week ->
prochain lundi seulement ; proactivite off ; solo.
**Prouve couche 2** (DeepSeek) : propose->confirme->commit + reject, semaine sous
contrainte 4/4, simulation live multi-tour (blessure same-turn 5/5/5/5, indispo 5/5/5/5,
**injury-after-commit forced-ordering 2/2**).
Detail : `docs/V0-CODE-MAP.md`, `docs/PLANNING-V0.md`, `docs/BUILD-ORDER.md`,
`docs/superpowers/specs/2026-06-*`.

Provider matrix : le `114/120` historique vient d'une run a 6 scenarios
(4 providers x 6 x 5 reps = 120). La matrix par defaut compte aujourd'hui
11 scenarios x 3 providers cibles (165 runs en 5x) et l'export n'est pas committe. A rejouer
avant de citer un chiffre provider a jour.

Providers cibles :

```text
DeepSeek
Mistral
Grok
```

Gemini reste disponible en opt-in manuel, mais n'est plus dans la matrix par
defaut tant que le credit API est absent.

## Architecture De Travail

Le runtime valide suit :

```text
InputEvent
-> WorldSnapshot
-> CoachAgent
-> ActionProposal
-> Policy
-> Executor
-> RuntimeResult
-> Reply
-> Guard
-> Audit
```

Live en prod — lacunes actives :

```text
run <-> session matching (LLM-first, pas encore auto)
voix terse (a rechauffer)
propose_week -> prochain lundi seulement
proactivite (briefings, revue hebdo) off
solo (legacy_user=1 hardcode dans strava_v0_sync)
```

## Ordre De Lecture

1. `AGENTS.md`
2. `PROJECT.md`
3. `docs/README.md`
4. `docs/BUILD-ORDER.md`
5. `docs/V0-DOGFOOD-SCOPE.md`
6. `docs/RUNTIME-V0.md`
7. `docs/V0-CODE-MAP.md`
8. `docs/RUNTIME-MIGRATION-PLAN.md`
9. `docs/RUNBOOK.md`

## Commandes

```bash
./scripts/docs:list
pytest tests/runtime_v0
python3 scripts/v0_eval/run_matrix.py --provider fake --repetitions 1
python3 scripts/v0_eval/run_matrix.py --repetitions 5
```

## Principes

- Pas de regex/keywords sur texte utilisateur libre.
- Pas de write DB hors executor/writer officiel.
- Pas de reply visible qui affirme une mutation sans event committe.
- Pas de fallback metier improvise.
- Pas de big-bang migration.
- Pas de sophistication sportive avant fiabilite dogfood.
