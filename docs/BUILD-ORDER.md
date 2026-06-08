---
summary: source de verite courte sur l'etat actuel et le prochain chantier
read_when:
  - commencer un chantier
  - verifier la suite immediate
  - recadrer le scope avant de coder
---

# Build Order

## Phrase Guide

```text
Le plus petit coach Telegram fiable pour 1 a 2 semaines de dogfood.
```

## Etat Actuel — 8 juin 2026 (soir) — V0 LIVE EN PROD

**V0 est le coach Telegram de Loïc depuis le soir du 8 juin 2026.** Le runner
`scripts/dogfood_telegram.py` remplace le legacy bot dans `scripts/start-prod`. Le bot
legacy est retraite ; ses jobs automatiques (cron Strava, briefing matin, revue
hebdomadaire) sont eteints.

```text
InputEvent -> Snapshot -> Agent -> Proposal -> Policy -> Executor
-> Result -> Reply -> Guard -> Audit
```

Preuve (verifiee offline puis deploye) :

- `tests/runtime_v0` : 262 passed ;
- fake matrix : `11/11` ;
- danger metrics : `0 wrong_write`, `0 old_plan`,
  `0 wrong_correction_target`, `0 claim_without_event` ;
- guard fallback rate : `0 %` ;
- core : ~4440 LOC (cap 4440 ; noyau conversationnel + moteur Meso — enveloppe acquise,
  re-baseline 7 juin). Cible ~2500 = ratchet du noyau conversationnel nu ; le cap ne
  monte que sur capacite prouvee. Detail : `docs/RUNTIME-V0.md` Budget.

**Deploiement prod (8 juin, soir)** :

- Runner `scripts/dogfood_telegram.py` = entrypoint bot en prod (via `start-prod`).
- Store propre : `FITMAS_V0_DB_PATH` -> `/data/fitmas_v0_dogfood.db` (volume Fly).
  Tables `v0_*` = source de verite live. Allowlist : `FITMAS_V0_DOGFOOD_CHAT_IDS`
  (secret Fly) = chat_id Telegram de Loïc.
- **Bootstrap depuis les donnees reelles** via `materialize_v0_db`
  (`runtime_v0/adapters/current_db_snapshot.py`) : plan courant -> `v0_scheduled_sessions`,
  activites -> `v0_activities`, faits -> `v0_facts`. Deux points critiques du bootstrap :
  (1) **remap user_id** : le legacy a `users.id = 1` ; le runner V0 cle sur
  `telegram_chat_id` -> remap necessaire a l'injection ; (2) **faits legacy jetes** :
  le `user_facts` legacy avait accumule du bruit (un "9.3" orphelin, doublons,
  meta-instructions au coach) — exactement l'accumulation de regles que V0 est concu pour
  eviter ; V0 demarre avec des faits propres. Le plan FUTUR legacy (au-dela de la semaine
  en cours) a egalement ete supprime : V0 planifie l'avenir lui-meme.
- **Strava -> V0 sync LIVE** : `runtime_v0/adapters/strava_v0_sync.py`
  (`sync_strava_to_v0`) tire les activites Strava recentes via le token legacy
  (`strava_connections`) et upserte dans `v0_activities`, dedoublon par Strava activity
  id. Job periodique dans le runner (`FITMAS_V0_STRAVA_SYNC_SECONDS`, defaut 900 s).
  Import paresseux pour que le runner demarre meme si le legacy importe. Verifie live
  (job actif, HTTP 200 Strava, ~100 activites syncees).
- **Net** : plan running courant reel, runs Strava auto-syncees toutes les 15 min,
  faits propres. Le cadrage "dogfoodable offline / runner local / store isole" est
  **depasse** : V0 est le coach live sur donnees reelles.

**Lacunes connues (pas du bug, travaux suivants)** :

- Run <-> session : pas de matching automatique. Le coach *voit* les activites recentes
  et peut marquer une seance done sur la demande de l'utilisateur (chemin LLM-first
  prevu), mais aucun auto-mark depuis la sync Strava.
- Presence / voix : pas qu'un ton terse. Sur un tour NON-actionnable (social / motivation,
  ex « il pleut mais je vais la faire ! ») V0 repond a cote (« je n'ai pas d'info fraiche…
  raconte-moi ta seance ») — erreur de categorie + zero chaleur + confond intention/bilan.
  Et il n'a PAS de personnalite : le *soul* legacy (« ClawCoach, pote encourageant », table
  `users`) n'a pas ete migre -> voix d'assistant generique. Detail + chantier : Ordre #5.
- `propose_week` cible toujours le prochain lundi ; pas de "cette semaine" en cours.
- Proactivite (briefings, revue hebdo que le legacy faisait) : eteinte.
- Solo uniquement : `sync_strava_to_v0` hardcode `legacy_user=1`.

Provider matrix : `114/120` est une ancienne run a 6 scenarios. La matrix
compte 11 scenarios et 3 providers cibles aujourd'hui. Export non committe,
a rejouer pour un chiffre provider a jour.

Le plan de migration par etapes (`RUNTIME-MIGRATION-PLAN.md`) est
**partiellement depasse** : l'adapteur de lecture (`materialize_v0_db`) a ete utilise
en one-shot pour le bootstrap ; la phase coexistence / write-adapter est devenue
inutile puisque le legacy est retraite. Le plan reste utile comme reference pour les
adapters techniques.

## Decision D'Architecture

```text
repo actuel = enveloppe produit
runtime_v0 = noyau live + source de verite
ancien pipeline = legacy retraite (FastAPI/webapp toujours UP mais donnees ignorees)
```

Ne pas creer de nouveau repo.
Le bot legacy est eteint ; ses donnees ne sont plus la source de verite.
`runtime_v0` + store v0_* = la realite du coaching de Loïc.

## Prochaine Tranche

Fait :

- ré-adaptation same-turn sous blessure (8 juin 2026, tranche #1) : sur « oui mais
  [douleur/blessure] », le coach note le fait sante ET re-propose une semaine sans
  intensite **dans le meme tour** (`propose_week(intensity_restricted=true)`, supersede
  du pending precedent). Offline : 253 tests, matrix 11/11, danger 0, cap 4320->4337.
  Couche 2 (`probe_live_simulation --persona blessure`) prouvee : PASS, juge LLM 5/5/5/5.
  Spec : `docs/superpowers/specs/2026-06-08-readapt-blessure-same-turn-design.md`.

- **#2 availability typee + dogfood V0** (8 juin 2026) : sur « oui mais [indispo jours] »,
  le coach note le fait availability ET appelle `propose_week(blocked_days=[...])` **dans
  le meme tour** — la semaine re-proposee place REST sur les jours bloques, cle sur un
  jour disponible. Mecanisme : `TypedConstraint.blocked_days` + verificateur
  `_check_blocked_days` (rejette toute seance sur un jour bloque, tous modes) + plancher
  de charge relache (garde la cle). Generateur et template blocked-days-aware.
  `get_planned_week` (read tool) : relit la semaine committee sur un tour ulterieur.
  Runner dogfood Telegram standalone `scripts/dogfood_telegram.py` (poll -> handle_event
  -> reply, store v0_*, DeepSeek, allowlist).
  Offline : 262 tests, cap 4440. Couche 2 (`probe_live_simulation --persona indispo`) :
  PASS, juge LLM 5/5/5/5. Spec : `docs/superpowers/specs/2026-06-08-v0-dogfood-wiring-design.md`.

- **Deploy live prod** (8 juin 2026, soir) : V0 remplace le legacy bot dans
  `scripts/start-prod`. Store bootstrap depuis les donnees reelles via
  `materialize_v0_db` (remap user_id `1 -> chat_id` ; plan futur legacy supprime ;
  faits legacy jetes). Strava->V0 sync (`runtime_v0/adapters/strava_v0_sync.py`,
  `FITMAS_V0_STRAVA_SYNC_SECONDS=900`) verifie live (HTTP 200, ~100 activites). V0
  store = source de verite du coaching de Loïc. Legacy bot retraite.

- liberation de la voix : la reply layer ne sert plus de template sur le chemin
  nominal (pending, blocage, clarification passent par le LLM). Les templates
  restent en filet `_fallback` seulement. Guard durci en parallele
  (`english_leak`, fuite de noms de tools, meta mid-phrase). Doctrine ecrite
  dans `LLM-FIRST-CONVERSATION.md` (Voix Vs Verite). Fake matrix toujours
  `11/11`, guard fallback `0 %`.
- comparaison app-vs-V0 sur 30 tours reels x 3 providers (`compare_app_vs_v0.py`).
  Resultat clef : V0 auto-committait un `swap` la ou l'app demandait
  confirmation. Corrige : le `swap` passe maintenant en `pending`
  (`swap_requires_confirmation`). Re-run panel : `tie_safe` 73 -> 76,
  `app_better` 17 -> 14, et la classe swap (#133/#151) passe de 6
  `unsafe_auto_commit` a 0. Reste 1 unsafe residuel non-swap (#129, tour
  multi-intention, non deterministe), detaille dans
  `RUNTIME-V0-APP-COMPARISON.md`.
- liberation des commits d'execution (skipped/partial/done/correction). Le
  verrou par verbe template (`_commit_summary`) est remplace par un gate sur le
  **fait porteur** (duree, jour, sport) : la voix libre passe si elle enonce le
  fait, sinon re-prompt une fois, sinon filet deterministe. Sonde DeepSeek :
  `execution_correction`, `undo_wrong_status`, `partial_yesterday` rendus
  chaleureux et porteurs du fait, `0 claim_without_event`, `0 wrong_write`. Bug
  de filet corrige au passage : un echec du reply LLM sur un tour
  pending/clarification tombait sur le message technique sec (la commande de
  bookkeeping committee masquait la confirmation) ; le filet rend desormais la
  meilleure verite disponible (`sanitized_fallback` 2 -> 0). Oracles de wording
  re-cibles sur le fait + accuses de reception, plus sur le verbe mort.

Ordre recommande :

1. ~~Blessure re-adapte same-turn~~ **FAIT** (8 juin 2026, tranche #1 — `propose_week(intensity_restricted=true)` + supersede pending ; spec `2026-06-08-readapt-blessure-same-turn-design.md`).
2. ~~**Typer l'availability**~~ **FAIT** (8 juin 2026, tranche #2 — `blocked_days` declares,
   repos sur jours bloques, juge LLM 5/5/5/5 ; spec `2026-06-08-v0-dogfood-wiring-design.md`).
3. ~~**Dogfood deploy live**~~ **FAIT** (8 juin 2026, soir) : runner remplace legacy bot,
   store bootstrap depuis donnees reelles (materialize + remap user_id + faits propres),
   Strava->V0 sync active (900 s, verifie live).
4. **Run <-> session matching** : chemin LLM-first — enseigner au coach a marquer
   une seance done quand il voit une activite Strava qui matche clairement
   (`propose_execution_update` + `recent_activities` + `current_plan` dans le snapshot) ;
   proactivite complete (heartbeat auto-reconcile) differee a la tranche heartbeat.
5. **Presence / Voix — PRIORITE (frontiere actuelle).** Le data est regle ; ce qui manque,
   c'est *etre* le coach, pas seulement *faire*. Revele en dogfood reel (8 juin) : sur
   « il pleut mais je vais la faire ! » (social + motivation + intention future), V0 a
   repondu « je n'ai pas d'info fraiche a te partager… raconte-moi ta seance… on ajuste »
   — pas de faute, mais pas naturel. Quatre volets :
   (a) **mode reponse non-actionnable** : un tour social / motivation / « j'y vais » ne
       demande AUCUN tool -> presence + encouragement bref, sans machinerie d'action
       (aujourd'hui V0 retombe sur une reponse creuse cadree donnees/execution) ;
   (b) **porter le soul/personnalite** : recuperer (profil legacy `users` : ClawCoach,
       « direct, humain, encourageant, comme un vrai pote ») ou redeclarer la voix — V0
       parle generique, pas comme *son* coach (le soul n'a pas ete migre) ;
   (c) **bannir le reflexe « je n'ai pas d'info »** quand rien n'est demande ;
   (d) **gerer intention vs bilan** (« je vais faire » != « j'ai fait » -> pas de saut
       premature vers le log d'execution).
   Garde-fou doctrine : c'est du prompt/voix LLM-first, JAMAIS du determinisme sur le texte
   user (pas de regex/keyword pour detecter « social » vs « action »). Le run<->session
   matching (#4) est *differe* (decision Loic : ok pour dogfood en l'etat) ; cette frontiere
   passe devant.
6. **`propose_week` "cette semaine"** : ajouter un param permettant de cibler la
   semaine en cours (pas seulement le prochain lundi).
7. **Persistance cross-tour availability** (stocker les jours bloques sur le fait,
   ingestion typee).
8. **Chemin modify/preference** (« fais plus varie »).
9. **Heartbeat / proactivite** : briefing matin, revue hebdo, reconciliation
   run<->session automatique (tout ce que le legacy faisait, V0 va l'acquerir).
10. **Hygiene/robustesse** : museler les logs httpx INFO (token dans les logs Fly) ;
    `sync_strava_to_v0` hardcode `legacy_user=1` (solo-only, a parametriser si multi-user) ;
    dedup run<->session a confirmer sur volume reel.

## Chantier Moteur Sport (co-evolue avec le runtime)

Doctrine : le moteur sport et le runtime se construisent **imbriques**, jamais en
deux chantiers separes (`docs/PLANNING-V0.md`). Le moteur = des **tools
coach-callables** (intention -> moteur deterministe -> proposition typee -> policy),
grandis **un tool a la fois**, chacun prouve en couche 2.

Principe : le LLM genere et personnalise ; un **verificateur deterministe tient
l'autorite**. La coherence (progression, arc long-terme) est portee par la
**gestion de contexte**, pas par un generateur deterministe.

Premier livrable : le **context-pack running minimal + le verificateur** (mode
continuite, hook transition). Test : generer 4-6 semaines running -> verif a la
main de la coherence/progression -> comparer au vecu app (cas TSS qui chute). Spec
a produire en premier : les 4-5 proprietes d'une semaine running saine, dont
l'anti-TSS-drop.

Avancement (6 juin 2026) : **Slice 0+1 codee** = modele type Meso +
verificateur deterministe (5 proprietes), prouve en fixtures dont le rejeu
"TSS qui chute" (`backend/src/fitmas/runtime_v0/meso/`). **Slice 1.5 codee** =
resolution de fact LLM-first (`propose_fact_resolution` -> `resolved_at`), trou
"douleur passee" ferme, prouve couche 2 (DeepSeek 4/4). Plan + spec :
`docs/superpowers/specs/2026-06-05-moteur-sport-*`. **Bridge fact->TypedConstraint
codé** (Slice 2.0, conservateur). **Slice 1.6 codée** = ingestion fiable des facts +
fact-rider (noter un fait durable + agir dans le même tour) ; couche 2 : indispo
enfin **notée**, note+act prouvé sur la douleur. Deux follow-ups ouverts (note+act
inconsistant sur l'indispo ; reply qui sur-promet) — voir
`2026-06-05-fact-ingestion-slice-1-6-spec.md`. **Slice 2.0 codée** = le **context-pack
en couches** `ContextPack{target, last_week_actuals, constraints[], signals[]}` + son
builder `build_context_pack`. `last_week_actuals` via **voie (b) forward-only**
(`actuals_from_week` réduit une semaine déjà typée ; cold-start = `None` ; typage du
legacy différé — `2026-06-05-moteur-sport-plan.md` Decisions #4). `signals` = slot typé
laissé **vide** (rempli en 2.1, quand le générateur le consomme). Design :
`docs/superpowers/specs/2026-06-05-slice-2-0-voie-b-design.md`. **Slice 2.1 codée** =
générateur LLM-first + boucle generate→verify (max 3) + template filet + anti-drop
contrainte-aware (Tier 2), offline. Harness couche 2 :
`scripts/v0_eval/generate_weeks.py`. Spec :
`docs/superpowers/specs/2026-06-06-slice-2-1-generator-design.md`.
**Couche 2 prouvee (6 juin, DeepSeek v4-pro)** : 5/5 semaines generees par le LLM,
progression saine et in-band, sereine cle seuil portee ; filet rattrape proprement
quand le LLM echoue. Deux releves : (1) la generation a besoin d'un budget tokens
>> 1024 (un modele a raisonnement crame 1024 avant le tool-call -> `finish_reason=length`
-> 0/5 ; 2048 marginal 3/5 ; **4096 robuste 5/5**) -> `max_tokens` rendu configurable
(`provider_clients`, defaut 1024 inchange ; harness a 4096). **A reprendre en Slice 3** :
le runtime conversationnel utilise le meme client a 1024, donc `propose_week` y tronquera
si on ne donne pas a la generation son propre budget. (2) le LLM met la cle seuil en
`moderate` (pas `hard`) pour charger en volume : le verif ne gate pas l'intensite de la
cle -> **observation qualite, pas encore preuve de derive**, a surveiller (pas de regle
reactive). **Slice 3a codee** (6 juin) : `propose_week` coach-callable cable dans le
runtime — seed LLM-declare depuis le reel, generation avec budget tokens dedie
(`generation_llm` 4096), la semaine verifiee est **montree** (preview, zero write,
`answer_only`). Design `2026-06-06-slice-3a-propose-week-design.md`.
**Couche 2 prouvee (6 juin, DeepSeek v4-pro, `scripts/v0_eval/probe_propose_week.py`)** :
sur « fais-moi ma semaine prochaine », le coach declenche `propose_week`, **ancre le seed
dans le reel** (calcule last_week_load=350 pondere depuis recent_training, key=threshold),
le moteur sort une semaine coherente in-band, `answer_only` (zero write), guard ok, reply
honnete (« je te propose », jamais « j'ai cree »). Trois fiabilisations requises et faites :
(1) **enseigner `propose_week` au coach** (prompt) — sinon il ne le declenche pas ;
(2) **surfacer `recent_training` dans le header** — sinon le coach ne peut pas ancrer le
seed ; (3) **budget reply >1024** (un modele a raisonnement tronque le rendu de la semaine
a 1024) — config du `reply_llm` cote wiring (Slice 4), pas un changement core.

**Slice 3b codee** (7 juin) : mecanisme `pending_resolution` general (LLM-first, ancre) —
`week_proposal` cree un pending, l'utilisateur accepte/rejette au tour suivant via
`resolve_pending`, l'executor commit dans `v0_planned_weeks` (accept) ou marque rejected
(reject), le chainage forward expose `resolve_pending` uniquement quand un pending est
ouvert. **Couche 1 prouvee** (245 tests runtime_v0 ; e2e propose->confirm->commit +
reject passent offline). **Couche 2 prouvee (7 juin, DeepSeek,
`scripts/v0_eval/probe_resolve_pending.py`)** : 2/2 sur un vrai tour non scripte —
ACCEPT (« oui, valide ») commit 1 semaine (`pending=accepted`, reply « la semaine du
15 juin est calee »), REJECT (« non, pas cette semaine ») 0 commit (`pending=rejected`,
reply « j'annule la semaine du 15 juin »), guard ok partout. Point de vigilance leve :
sur reject le LLM honore bien l'annulation (pas de faux « c'est fait » malgre l'event
d'audit).

**Couche 2 sous contrainte (7 juin, DeepSeek, `scripts/v0_eval/probe_constrained_week.py`)** :
fait sante actif (intensite restreinte) -> la semaine proposee ET committee ne contient
aucune seance dure/seuil/fractionne. La sonde a debusque deux trous, tous deux corriges :
(1) le prompt de generation se contredisait (« garde le seuil » + « pas d'intensite ») ->
le LLM echouait toujours, repli template 3/3 (sur, mais generique) ; le prompt est rendu
**constraint-aware** (la cle prescrite saute sous restriction, comme le fait deja le verif).
(2) une semaine **vide** passait le verif relache (cle + plancher de charge tous deux
relaxes) ; le verif rejette desormais une semaine degeneree (vide/tout-repos) dans **tous
les modes**. Re-probe : **4/4, source=llm** a chaque rep, contrainte respectee, commit ok.

**Couche 2 live multi-tour (7 juin, DeepSeek, `scripts/v0_eval/probe_live_simulation.py`)** :
un LLM joue un athlete non scripte (indispo / blessure / lassitude) face au vrai coach.
Trois reels : (1) **danger** — sur « oui mais [blessure] » le coach committait la semaine
**dure inchangee** (seuil) sous blessure = profil d'echec de l'app ; (2) **malhonnetete** —
sur « oui mais [indispo] » il committait inchange en pretendant « avec les ajustements » ;
(3) **inutilite** — une demande de variete partait en non-sequitur. **Fix P1** (prompt coach,
LLM-first) : une reponse a un pending qui souleve une nouvelle contrainte/objection n'est
**pas un accept** — noter le fait, ne pas committer la semaine inchangee, ne jamais
affirmer une adaptation non faite. Re-probe : blessure et indispo echouent desormais
**safe** (note + hold, zero commit dangereux/menteur).

**Comportement sur « okay mais [contrainte] » (etat courant)** :

- **Blessure / douleur** (8 juin 2026, tranche #1 livree) : le coach note le fait sante
  ET appelle `propose_week(intensity_restricted=true)` **dans le meme tour** — le LLM
  declare la contrainte qu'il a comprise ce tour ; le verificateur tient l'autorite
  (reduction-sous-contrainte deja codee). Un nouveau pending `week_proposal` **supersede**
  l'ancien ouvert (`executor._apply_create_pending`, status `superseded`) — un seul pending
  vit. Le fact-rider committe la note sante en parallele. Etat net : **blessure re-adaptee
  same-turn**. Spec : `docs/superpowers/specs/2026-06-08-readapt-blessure-same-turn-design.md`.
  Couche 2 (`probe_live_simulation --persona blessure`) **prouvee** (8 juin) : PASS, juge LLM 5/5/5/5 — same-turn re-adaptation confirmee en live non scripte (semaine sans intensite proposee puis committee, guard ok).

- **Indispo** (8 juin 2026, tranche #2 livree) : same-turn note availability +
  `propose_week(blocked_days=[...])` -> semaine avec REST sur les jours bloques ;
  verificateur `_check_blocked_days` + plancher relache (garde la cle) ; prouve couche 2
  (indispo, juge LLM 5/5/5/5). Residuel : persistance cross-tour des jours bloques (differee).

**Residuels (follow-ups)** :
- run <-> session matching LLM-first — ouvert ;
- voix terse — ouvert ;
- `propose_week` "cette semaine" — ouvert ;
- persistance cross-tour de l'availability (stocker les jours bloques sur le fait, ingestion typee) — differee ;
- **chemin preference/modify** (« fais plus varie ») — tranche #3 ;
- materialisation semaine->plan executable (`v0_scheduled_sessions`) — Slice 3b follow-up ;
- handler commit `plan_patch` — Slice 3b follow-up ;
- heartbeat / proactivite (briefings, revue hebdo, auto-reconcile) — phase 2 ;
- suivi d'execution (phase 2).

La passe de simplification pre-3b est resolue **en re-baseline** (7 juin,
`RUNTIME-V0.md` Budget : moteur Meso = enveloppe acquise, pas du creep ;
`meso/`+cablage deja serres). Le moteur de contexte profond (couches, accumulation)
reste un chantier dedie APRES le moteur (`PLANNING-V0.md` Q5).

Contraintes : running-only d'abord ; tout Meso en `pending` ; le cut
LLM<->deterministe se decouvre empiriquement ; l'usine planning de l'app est a
**strangler, pas a brancher**. Questions ouvertes listees dans `docs/PLANNING-V0.md`.

## Scope Actif

Lire :

- `docs/V0-DOGFOOD-SCOPE.md` pour le produit V0 ;
- `docs/RUNTIME-V0.md` pour le noyau actuel ;
- `docs/RUNTIME-MIGRATION-PLAN.md` pour l'integration ;
- `docs/LLM-FIRST-CONVERSATION.md` pour la doctrine texte utilisateur ;
- `docs/PLANNING-V0.md` pour l'architecture moteur sport co-evolue.

Le V0 couvre :

- plan actuel / aujourd'hui / demain ;
- execution `done`, `skipped`, `partial` ;
- correction d'execution ;
- move/lighten/replace simple en place (auto-commit si cible claire) ;
- pending pour seance cle, swap ou multi-operation ;
- block pour risque sportif clair ;
- heartbeat read-only ou question courte seulement.

## Hors Scope

Ne pas ouvrir sans demande explicite :

- Phase B progression/prescription ;
- replan complet long terme ;
- periodisation multi-mois ;
- nutrition ;
- multi-agent ;
- memoire vectorielle/reflexive ;
- heartbeat qui auto-commit une mutation ;
- UI de decision complexe.

## Providers

Providers a tester en V0 :

```text
DeepSeek
Mistral
Grok
```

Gemini reste disponible en opt-in manuel, mais n'est plus dans la matrix par
defaut tant que le credit API est absent.

## Gates Dogfood

**Gates franchies (8 juin 2026)** — V0 est desormais live en prod. Les gates
restent la reference pour les nouvelles tranches.

Couche 1 — matrice, filet mecanique :

```text
>= 90% correctness sur scenarios V0 produit   [atteint]
0 danger metrics                               [atteint]
0 duplicate command sur retry                  [atteint]
guard fallback rate < 15%                      [atteint — 0%]
```

Couche 2 — simulation live sous-agent : une vraie conversation non scriptee
tient sur les scenarios dogfood. Un chiffre matrice ne suffit pas a ouvrir le
dogfood.

La latence est mesuree, mais ne bloque pas le dogfood tant que la reponse est
fiable.

## Verification Minimale

```bash
./scripts/docs:list
pytest tests/runtime_v0
python3 scripts/v0_eval/run_matrix.py --provider fake --repetitions 1
python3 scripts/v0_eval/run_matrix.py --repetitions 5
python3 scripts/v0_eval/compare_app_vs_v0.py --turn-ids 151 --dry-run
```

Exports utiles :

```text
exports/runtime-v0/stability-fake-final
exports/runtime-v0/stability-providers-5x
```

## Regles Dures

- Le LLM comprend le texte utilisateur et produit des artefacts structures.
- Le backend valide, autorise, commit et audite.
- Aucun regex/keyword sur texte utilisateur libre.
- Aucun write DB hors executor/writer officiel.
- Aucune reply visible ne doit mentir sur un write.
- `runtime_v0` reste isole tant que les adapters ne sont pas prouves.
