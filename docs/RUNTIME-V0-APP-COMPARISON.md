---
summary: comparaison anonymisée Runtime V0 vs app legacy sur tours réels — preuve publique du "fail-safe", + résultats empiriques détaillés et durcissement du swap
read_when:
  - comparer Runtime V0 au pipeline legacy
  - écrire / relire la comparaison V0-vs-legacy publique
  - analyser les écarts policy, pending ou qualité de réponse
---

# V0 vs Legacy — A Study in Failing Safe

> How the rebuilt coach (`runtime_v0/`) behaves on the same real-world inputs that broke its
> deterministic predecessor. The thesis: a trustworthy LLM product fails *safe*, and you prove it
> on the danger profile — not on a green usefulness number.

## Why compare at all

The legacy coach was a deterministic generator with the LLM in a narrow role: every broken case
got one more rule (a regex, a keyword, a template, a branch). Those rules are invisible in tests
(you only test the cases you imagined) and lethal in production (the case you didn't). V0 inverts
the split — the LLM understands and generates; a deterministic verifier holds authority over safety
and structure, and nothing is written except through one audited executor.

## Architecture, before and after

| | Legacy app | V0 rebuild |
|---|---|---|
| Decision / planning brain | deterministic generator (fix-on-fix, rigid, buggy) | LLM understands + deterministic verifier holds authority |
| Free user text | regex / keywords / branches | zero determinism — the LLM understands it |
| Typical failure | "perfect in test, incapable in reality" | "survives reality ≠ a green number" |
| Reliability | unguarded claims | output guard + `claim_without_event` + every write audited |
| Strategy | — | strangle the brain, keep the envelope |

## The memorable case — fabricated block, false confirmation

A real turn, anonymized (scenario `move_today_open_week`, see [`V0-TEST-DOCTRINE.md`](V0-TEST-DOCTRINE.md) layer 2).
The athlete is unavailable and asks to move the day's session; the week and week-end are open.

- **Legacy:** fabricated a justification ("the end of the week is full") to refuse, then replied as
  if settled ("all sorted") — **without moving anything**. The visible reply claimed an action that
  never happened.
- **V0, same world state:** stays **safe and useful** — turn 1 asks which day to move to *without
  inventing a constraint*, or moves the session to an open slot and reports exactly what it
  committed. It never claims a write that didn't occur: the output guard reads the model's own reply
  and blocks anything that lies about a write (`claim_without_event` stays 0).

## What the numbers do — and don't — say

The detailed empirical run is below. The honest headline:

- V0 **fails safe**: `tie_bad` 0, no inconclusive snapshot, and the one systematic danger class —
  an auto-committed planning *swap* — was **found, closed, and re-verified** (6 → 0; see below).
- V0 is **not yet better on raw usefulness** on this scripted replay (`app_better` 14, `v0_better`
  0) — *and that is the point*. The scripted matrix tunes both sides of the exchange, so it can only
  ever be an anti-regression / danger net, never a quality compass. Quality is judged on **layer 2**:
  an unscripted athlete (an injury, a work trip, boredom) role-played against the real coach loop,
  with deterministic safety oracles and an LLM quality judge.

Refusing to game a raw rate is the mature evaluation signal — the two-layer method itself (danger
metrics + unscripted subagent simulation) is the real artifact.

> *Personal-data note: this is a solo personal project; the only athlete is the author. The detailed
> report below references turns by id and paraphrases them — no verbatim messages, no third-party
> data. The raw comparison dump and shadow DBs are regenerable and not committed (they replay real
> turns).*

---

# Detailed empirical report

Run of 30 May 2026 over 30 recent real turns, with 3 V0 providers.

Reproduce (the real source DB and the raw export are local-only, gitignored — PII + regenerable):

```bash
.venv/bin/python scripts/v0_eval/compare_app_vs_v0.py \
  --real-db .tmp-prod-fitmas.db \
  --limit 30 \
  --providers deepseek,grok,mistral \
  --max-steps 6 \
  --export-dir exports/runtime-v0/app-vs-v0-30 \
  --report-path exports/runtime-v0/app-vs-v0-30/report.md
```

## Resultats baseline (avant durcissement du swap)

| Signal | Valeur |
| --- | ---: |
| Tours reels | 30 |
| Providers | 3 |
| Runs total | 90 |
| `tie_safe` | 73 |
| `app_better` | 17 |
| `v0_better` | 0 |
| `tie_bad` | 0 |
| `inconclusive_snapshot` | 0 |

Par provider:

| Provider | tie_safe | app_better |
| --- | ---: | ---: |
| DeepSeek | 25 | 5 |
| Grok | 24 | 6 |
| Mistral | 24 | 6 |

Flags de risque:

| Flag | Count |
| --- | ---: |
| `missed_pending` | 7 |
| `unhelpful_no_send` | 7 |
| `unsafe_auto_commit` | 6 |

Tous les runs utilisent `snapshot_source=conversation_context`.

## Lecture

Runtime V0 ne montre pas de panne catastrophique dans cette passe: pas de `tie_bad`, pas de snapshot inconclusif, et aucun signal de vieille source evidente.

Mais V0 n'est pas encore meilleur que l'app actuelle sur ce panel. Les 17 cas `app_better` pointent trois chantiers:

- `unsafe_auto_commit`: la policy V0 commit certains swaps planning que l'app met en confirmation.
- `missed_pending`: le replay comparatif ne materialise pas encore assez bien les pending confirmations existantes.
- `unhelpful_no_send`: V0 reste parfois muet ou trop generique sur des tours sociaux ou semi-actionnables.

Conclusion: la prochaine decision n'est pas provider-first. Elle est runtime/policy/adapter-first.

## Apres durcissement du swap

Le chantier 1 ci-dessous est traite : un `swap` ne s'auto-commit plus, il passe
en `pending` (`swap_requires_confirmation`, dans `sport_rules.py`).

Re-run du meme panel apres le fix (30 tours, 3 providers, 90 runs) :

| Signal | Baseline | Apres |
| --- | ---: | ---: |
| `tie_safe` | 73 | 76 |
| `app_better` | 17 | 14 |
| `v0_better` | 0 | 0 |
| `tie_bad` | 0 | 0 |
| `unsafe_auto_commit` | 6 | 1 |
| `missed_pending` | 7 | 7 |
| `unhelpful_no_send` | 7 | 9 |

Par provider apres fix (tie_safe / app_better) : DeepSeek 27/3, Grok 23/7,
Mistral 26/4.

Ce qui change vraiment :

- Les 6 `unsafe_auto_commit` du baseline etaient exactement les 2 tours `Echange`
  (#133, #151) x 3 providers. Apres le fix, les 6 passent en `create_pending` et
  `tie_safe`. La classe de danger « swap auto-committe » est fermee.
- `missed_pending` est stable (memes 7 runs) : pas de regression.

Le `unsafe_auto_commit` restant (1) est un cas different, pas une regression :

- Tour #129, grok seul, absent du baseline. Un garde-fou pending ne peut
  qu'ajouter une confirmation, jamais creer un commit : le fix ne l'a pas cause.
- Message multi-intention : remplacer le footing du jour par de la natation
  (un `replace`, dans le bucket auto-commit de V0) **et** « s'arranger pour un
  4e footing ailleurs » (un `add`, hors scope V0).
- L'app a tout mis en confirmation ; grok a committe le `replace` et differe
  l'ajout a l'oral. Ce n'est pas un swap : le garde-fou ne le vise pas.
- C'est du non-determinisme provider (grok ce run ; baseline propre). L'echec
  reste honnete et a faible enjeu (un `replace` plausible, reply qui ne ment
  pas), pas un wrong write.

`unhelpful_no_send` passe de 7 a 9, mais sur des tours differents a chaque run :
bruit provider, pas une regression structurelle.

Profil d'echec : la seule classe de danger systematique (swap) est fermee. Le
risque residuel est un `replace` auto-committe sur un tour ambigu, multi-
intention, non deterministe et partiellement hors scope.

## Suite

Avant dogfood Telegram, traiter en priorite:

1. ~~Durcir la policy sur les swaps et operations planning multi-seances.~~
   Fait : swap -> `pending` (verifie, `unsafe_auto_commit` swap 6 -> 0).
2. ~~Relancer cette comparaison sur le meme panel pour verifier la regression.~~
   Fait : tie_safe 73 -> 76, app_better 17 -> 14, aucune regression danger.
3. Cas ambigu / multi-intention (#129) : decider si un tour qui melange une op
   in-scope et une demande hors scope doit passer en `pending` plutot que de
   committer la moitie. Evidence faible (1 run, 1 provider) : ne pas
   sur-corriger en bloquant les `replace` simples.
4. Ameliorer l'adapter de replay pour les pending confirmations reelles
   (`missed_pending`, stable a 7).
5. Reduire les `no_send` inutiles sans autoriser de fausse mutation
   (`unhelpful_no_send`).
