---
summary: design Slice 3a — câbler le générateur Meso dans le runtime comme tool coach-callable propose_week qui MONTRE une semaine vérifiée (preview non-committante). Cold-start via seed LLM-déclaré, budget tokens dédié. Pas de commit/store (= 3b).
read_when:
  - câbler propose_week dans le runtime (tool_catalog, proposals, policy, reply)
  - décider comment la génération obtient son budget tokens dans le runtime
  - traiter le cold-start (seed déclaré par le LLM depuis le réel)
  - préparer Slice 3b (confirmation -> commit -> store typé -> chaînage)
---

# Design — Slice 3a : `propose_week` câblé (montrer en pending)

Contexte : `docs/PLANNING-V0.md` (archi cible), `docs/superpowers/specs/2026-06-06-slice-2-1-generator-design.md`
(le générateur que ce slice appelle), `docs/BUILD-ORDER.md` (Slice 3 = tool runtime
`propose_week`). Couche-2 de 2.1 a relevé le **budget tokens** (la génération a besoin
de >> 1024) — repris ici.

## Objectif

Brancher la voiture au moteur : le coach appelle `propose_week`, le moteur **génère une
semaine dans le runtime** (boucle generate→verify de 2.1) et la semaine vérifiée est
**montrée** à l'utilisateur. Premier bout prouvable de Slice 3 ; le commit/stockage =
3b.

## Découpe (décidé)

Slice 3 force d'un coup le **cold-start**, le **stockage des semaines typées**, le
**budget tokens runtime** et le câblage tool→pending→commit. Trop pour un slice. Découpe :

- **3a (ce slice)** : `propose_week` câblé → génère → **montre** la semaine (preview
  non-committante). Pas de commit, pas de store, pas de confirmation→write.
- **3b (suivant)** : confirmation « oui » → **commit** la semaine dans le plan + **store
  typé** + **chaînage forward** (`actuals_from_week` sur la semaine committée).

3a est prouvable seul : il est bloqué par le cold-start (résolu ci-dessous) mais **pas**
par le stockage.

## Décisions arrêtées (forks tranchés)

1. **3a montre, ne commit pas.** En 3a la policy renvoie une décision **« montrer »**
   (pas de commande, pas de write). On **ne crée pas de pending formel** (on ne saurait
   pas le résoudre — confirmation→commit = 3b). La doctrine « tout Meso en pending » est
   respectée au sens fort : 3a **n'auto-commit jamais** (il ne commit pas du tout).
2. **Cold-start = seed déclaré par le LLM depuis le réel.** Le coach lit l'entraînement
   récent réel (read tools existants) et **déclare** `last_week_load` + `key_type` en args
   de `propose_week`. Le LLM fait le typage approximatif du legacy (sa force : comprendre
   du messy) ; le **vérificateur tient l'autorité** sur la semaine générée ; tout est
   montré, l'humain juge. Zéro adapter déterministe sur le legacy.
3. **Budget tokens dédié.** La génération tourne dans le handler avec un **client séparé**
   (`generation_llm`, max_tokens 4096). Le `coach_llm` reste à 1024.

## Non-objectifs (différés)

- **Commit** d'une semaine, **store typé**, **chaînage forward** → 3b.
- **Confirmation→write** (résoudre un « oui » en commit) → 3b.
- **Pending formel** d'une semaine → 3b.
- Mode **transition**, **multi-sport**, **macro/périodisation**, **signals** consommés.

## Le tool `propose_week` (coach-callable)

Nouveau proposal-tool. Le coach **lit d'abord** le réel, puis appelle :

```
propose_week(last_week_load: number, key_type: SessionType, phase: Phase = "build")
```

Handler (dans `meso/runtime_tool.py`, nouveau ; le seul module meso qui voit le snapshot
runtime + le générateur) :

1. `actuals = WeekActuals(total_load=last_week_load, key_type=key_type)` (seed déclaré).
2. `pack = ContextPack(target=derive_continuity_target(actuals, phase),
   last_week_actuals=actuals, constraints=constraints_from_snapshot(snapshot), signals=())`.
3. `week_start` = **lundi prochain** calculé depuis `snapshot.today` (déterministe, pas
   d'LLM sur les dates).
4. `proposal = generate_week(generation_llm, pack, week_start)` (WeekProposal).
5. retourne `ActionProposal(type="week_proposal", week_proposal=WeekProposalDraft(...))`.

Le `generation_llm` et le `snapshot` arrivent par le `ToolContext`.

## Budget tokens dans le runtime

`RuntimeDeps` gagne `generation_llm: LLMClient` (un client à **max_tokens 4096**). Il est
threadé dans `ToolContext` (à côté de `db_path`, `snapshot`, `scratchpad`) pour que le
handler `propose_week` l'utilise. Le `coach_llm` (boucle de conversation) reste à 1024 —
inchangé, zéro régression sur le reste du runtime. C'est le **premier tool-handler qui
appelle un LLM** — assumé : le moteur EST une boîte à outils coach-callable (intention
haut niveau → moteur → proposition typée).

## Câblage proposal → policy → reply

- `proposals.py` : `ActionProposal.type` gagne `"week_proposal"` ; nouveau
  `WeekProposalDraft{week: PlannedWeek-jsonable, source: str, week_load: float,
  band: tuple, key_type: str}` (forme sérialisable ; on n'embarque pas le verdict objet,
  juste ce que la reply doit montrer). Sérialisation dans `proposal_to_dict`/`_from_dict`.
- `policy.py` : branche `week_proposal` → décision **« montrer »**. Réutilise
  `answer_only` (pas de commande, `reply_facts` = le résumé de la semaine) — aucun write.
  *(3b remplacera ça par `create_pending` + confirmation→commit.)*
- `reply.py` / `result.py` : rendre la semaine (jours / type / durée) + « je te la
  propose, je l'applique ? ». **Honnête** : c'est une proposition, jamais « j'ai créé ».
- `guard.py` : rien de neuf — aucun write annoncé, donc pas de `claim_without_event`.

## Plan de test

**Couche 1 — déterministe (fake `generation_llm`)** :
- le coach appelle `propose_week(last_week_load, key_type)` (réponse coach scriptée via
  `FakeLLMClient`), le handler génère (fake generation_llm émet une bonne semaine) →
  `ActionProposal.type == "week_proposal"` → policy `answer_only` (0 commande) → reply
  contient les séances, **0 write**, guard ok.
- sérialisation : `proposal_to_dict`/`proposal_from_dict` round-trip un `week_proposal`.
- le `generation_llm` (4096) est bien celui passé au générateur, pas le `coach_llm`.

**Couche 2 — vrai provider** :
- « fais-moi ma semaine prochaine » sur un snapshot avec entraînement récent réel → le
  coach lit le réel, déclare un seed plausible, **montre une semaine cohérente in-band**.
  Honnêteté : la reply ne ment pas sur un write. Comparer au vécu app.

## Architecture / fichiers

```
backend/src/fitmas/runtime_v0/meso/runtime_tool.py   # nouveau : handler propose_week
backend/src/fitmas/runtime_v0/tool_catalog.py        # enregistrer propose_week
backend/src/fitmas/runtime_v0/proposals.py           # type week_proposal + WeekProposalDraft
backend/src/fitmas/runtime_v0/policy.py              # branche week_proposal -> answer_only
backend/src/fitmas/runtime_v0/reply.py | result.py   # rendu de la semaine
backend/src/fitmas/runtime_v0/runtime.py             # RuntimeDeps.generation_llm
backend/src/fitmas/runtime_v0/tools_read.py          # ToolContext porte generation_llm
tests/runtime_v0/test_propose_week.py                # couche 1
```

Contraintes : tout reste **dans `runtime_v0`** (le coach dépend désormais de `meso/` —
voulu, le moteur devient coach-callable). Isolation inchangée : aucun import
`fitmas.decision/domain/llm/skills/tools/app`.

## Critère "Done"

- `pytest tests/runtime_v0` vert (aucune régression).
- Couche 1 : `propose_week` → `week_proposal` → `answer_only` (0 commande) → reply montre
  la semaine, guard ok, round-trip sérialisation ok.
- Couche 2 : « fais-moi ma semaine » tient sur un vrai tour (semaine cohérente montrée,
  reply honnête, 0 `claim_without_event`).
- `runtime_v0` isolé ; **aucun write** déclenché par `propose_week` en 3a.
- Budget LOC tranché (voir ci-dessous).

## Impact budget LOC (à trancher à l'implé)

~80 LOC core → ~3941 → **~4020**, au-dessus du cap 3960. Câblage d'une vraie capacité
(le moteur entre dans le produit) → bump assumé (~4050, sur le compte réel mesuré). Le
ratchet reste surveillé (cible saine 2500 ; on documente le saut).

## Règles dures (rappel)

- Le LLM comprend / déclare le seed ; le **vérificateur + la policy** tiennent l'autorité.
- Aucun regex/keyword sur texte user libre (le coach décide d'appeler `propose_week`).
- Aucun write DB hors executor officiel ; **3a ne committe rien** ; aucune reply ne ment
  sur un write.
- `runtime_v0` reste isolé ; tout Meso reste **pending / non-committé** (3a ne commit pas).
