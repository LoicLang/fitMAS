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

## Etat Actuel — 30 mai 2026

Le Runtime V0 a valide le noyau et le premier Sport Core minimal :

```text
InputEvent -> Snapshot -> Agent -> Proposal -> Policy -> Executor
-> Result -> Reply -> Guard -> Audit
```

Preuve (verifiee offline le 31 mai 2026) :

- `tests/runtime_v0 + docs` : 160 passed ;
- fake matrix : `11/11` ;
- danger metrics : `0 wrong_write`, `0 old_plan`,
  `0 wrong_correction_target`, `0 claim_without_event` ;
- guard fallback rate : `0 %` ;
- core : 3121 LOC (zone acceptable).

Provider matrix : `114/120` est une ancienne run a 6 scenarios. La matrix
compte 11 scenarios et 3 providers cibles aujourd'hui. Export non committe,
a rejouer pour un chiffre provider a jour.

Le chantier actif n'est plus un shrink de l'ancien runtime historique.
C'est la preparation d'un **Produit V0 dogfoodable** autour de
`backend/src/fitmas/runtime_v0/`.

## Decision D'Architecture

```text
repo actuel = enveloppe produit
runtime_v0 = noyau cible prouve
ancien pipeline = legacy a etrangler
```

Ne pas creer de nouveau repo.
Ne pas migrer Telegram en big-bang.
Ne pas supprimer l'ancien pipeline avant preuve sur adapters.

## Prochaine Tranche

Fait :

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

1. Relancer une provider matrix ciblee sur les 11 scenarios.
2. Construire un `WorldSnapshot` depuis une copie DB actuelle, en distinguant
   replay fidele (`conversation_context`) et debug approximatif (`current_state`).
3. Construire un executor adapter vers les writers existants.
4. Brancher Telegram/API sous flag et allowlist user.

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

Avancement (5 juin 2026) : **Slice 0+1 codee** = modele type Meso +
verificateur deterministe (5 proprietes), prouve en fixtures dont le rejeu
"TSS qui chute" (`backend/src/fitmas/runtime_v0/meso/`). **Slice 1.5 codee** =
resolution de fact LLM-first (`propose_fact_resolution` -> `resolved_at`), trou
"douleur passee" ferme, prouve couche 2 (DeepSeek 4/4). Plan + spec :
`docs/superpowers/specs/2026-06-05-moteur-sport-*`. Suite : **Slice 2.0** (contrat
contexte = pack en couches + bridge fact->TypedConstraint, conservateur d'abord,
sante toujours incluse ; seam stable) puis **Slice 2.1** (generateur LLM, boucle
generate->verify). Le moteur de contexte profond (couches, accumulation) reste un
chantier dedie APRES le moteur (`PLANNING-V0.md` Q5).

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

Avant Telegram V0, deux couches de test (doctrine : `docs/V0-TEST-DOCTRINE.md`).

Couche 1 — matrice, filet mecanique :

```text
>= 90% correctness sur scenarios V0 produit
0 danger metrics
0 duplicate command sur retry
guard fallback rate < 15%
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
