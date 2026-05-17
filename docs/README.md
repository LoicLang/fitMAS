---
summary: point d'entree documentaire du projet
read_when:
  - commencer a travailler sur le projet
  - chercher un document
---

# Docs

## Set documentaire actuel

| Document | Contenu |
|----------|---------|
| `DECISION-RUNTIME-REFACTOR.md` | Nouveau canon architecture : FitMAS Decision Runtime, boucle unique event -> understanding -> outcome -> reply ; etat Phase 8O inclus |
| `DECISION-RUNTIME-LEGACY-KILL-LIST.md` | Phase 8 : inventaire des surfaces legacy a couper avant activation complete du runtime |
| `BUILD-ORDER.md` | Source de verite sur l'etat reel, les priorites et la suite immediate |
| `API-DOGFOOD-RELIABILITY-2026-05-12.md` | Dogfood API reel du 12 mai : tests, conclusions DeepSeek/gateway, plan de remediation |
| `LLM-FIRST-CONVERSATION.md` | Doctrine zero determinisme sur texte utilisateur libre + plan de migration conversation |
| `ARCHITECTURE.md` | Stack, principes de harness, modele de donnees, flux techniques |
| `SYSTEM-MAP.md` | Carte du systeme : flux, frontieres LLM/tools/skills, points d'extension |
| `PRODUCT.md` | Vision, wedge multisport, scope, parcours utilisateur |
| `COACH-COHERENCE-REFACTOR.md` | Gouvernance etat : verite runtime unique, writer unique, bundle partage, gates |
| `SPORT-QUALITY-REVIEW.md` | Doctrine Phase A+ : reviewer sportif non-writer, coherence semaine, policy runtime, prescription/progression future |
| `PLANNING.md` | Contrat produit + moteur V2 de la planification adaptative |
| `CONVERSATION.md` | Grounding conversationnel, doctrine LLM-first, dette active des anciens extracteurs |
| `MEMORY-V2.md` | Architecture memoire : profile vs working vs patterns, regles et migration |
| `RUNTIME-TOOLS.md` | Contrat des tools runtime multi-tool bornes, registre read-only/candidate/validation, limites et metriques |
| `PROMPT-CONTEXT-REFACTOR.md` | Etat du chantier prompt/contexte : PromptContract, context diet, snapshots, `decide_none`, dettes restantes |
| `ADAPTATION-CANDIDATE-PIPELINE.md` | Adaptation par candidats : refs backend, evaluator, policy, pending choice, reviewer LLM borne |
| `PLANNING-SNAPSHOT-ADAPTATION-REFACTOR.md` | Refactor adaptation : snapshot semaine complet, proposition LLM, compilation PlanPatch et invariants repos/charge |
| `APP-UX.md` | Contrat UX de la webapp : calendrier, today, performance |
| `SOUL.md` | Voix FitMAS, heartbeat, messagerie, ton |
| `RUNBOOK.md` | Commandes, flux a tester, debug, deploiement, mapping du code |
| `TESTER-GUIDE.md` | Guide d'onboarding pour les testeurs alpha |
| `CONVERSATION-AUDIT-2026-04-17.md` | Audit architecture conversation + contexte post-passe de fiabilite |
| `COACH-AUTONOMY-REFACTOR.md` | Refonte coach : suppression court-circuits, tools de lecture brute, skill replan validé, posture "DÉCIDE" |
| `COACH-AUTONOMY-AUDIT.md` | Inventaire system prompts + court-circuits du pipeline coach (sortie du Chantier 0) |

## Plans Decision Runtime recents

- `superpowers/plans/2026-05-14-decision-runtime-phase-8f-command-extraction.md` — Phase 8F : extraction des writes memoire/execution vers `CommandBus`.
- `superpowers/plans/2026-05-14-decision-runtime-phase-8g-pending-resolution.md` — Phase 8G : extraction de `pending_resolution` vers le bridge pending.
- `superpowers/plans/2026-05-15-decision-runtime-phase-8h-pending-reply-cleanup.md` — Phase 8H : replies pending non commitantes via `DecisionOutcome -> DecisionReplyComposer`.
- `superpowers/plans/2026-05-15-decision-runtime-phase-8i-canonical-flag-dogfood.md` — Phase 8I : dogfood des flags canoniques Understanding/commands/pending.
- `superpowers/plans/2026-05-15-decision-runtime-phase-8j-canonical-planning-cutover.md` — Phase 8J : dogfood strict du planning cutover canonique.
- `superpowers/plans/2026-05-15-decision-runtime-phase-8k-canonical-default-lanes.md` — Phase 8K : default-enable controle des lanes canoniques commands/pending.
- `superpowers/plans/2026-05-15-decision-runtime-phase-8l-decide-authority-shrink.md` — Phase 8L : shrink de l'autorite runtime de `decide()`.
- `superpowers/plans/2026-05-16-decision-runtime-phase-8m-decision-legacy-split.md` — Phase 8M : split interne de `llm/decision_legacy.py`.
- `superpowers/plans/2026-05-17-decision-runtime-phase-8n-provider-tool-loop-extraction.md` — Phase 8N : extraction provider, schema repair et tool-loop de `llm/decision_legacy.py`.
- `superpowers/plans/2026-05-17-decision-runtime-phase-8o-coachdecision-artifact-boundary.md` — Phase 8O : frontiere artifact entre `CoachDecision` legacy et runtime conversation.

## Canon actuel

`DECISION-RUNTIME-REFACTOR.md` devient le document d'architecture cible pour
le refactor massif.

Les anciens documents de refactor restent lisibles comme contexte historique,
mais ils sont temporairement **legacy** pour les decisions d'architecture :

- `COACH-COHERENCE-REFACTOR.md`
- `COACH-RELIABILITY-REFACTOR.md`
- `COACH-AUTONOMY-REFACTOR.md`
- `COACH-AUTONOMY-AUDIT.md`
- `ADAPTATION-CANDIDATE-PIPELINE.md`
- `PLANNING-SNAPSHOT-ADAPTATION-REFACTOR.md`
- `PROMPT-CONTEXT-REFACTOR.md`
- les plans dans `docs/superpowers/plans/`

Ils peuvent contenir des briques utiles. Ils ne tranchent plus la cible.

## Hierarchie de verite

Quand plusieurs docs semblent raconter des choses differentes :

1. `DECISION-RUNTIME-REFACTOR.md` gagne pour l'architecture cible du refactor
2. `DECISION-RUNTIME-LEGACY-KILL-LIST.md` gagne pour l'inventaire Phase 8 des surfaces legacy a supprimer
3. `BUILD-ORDER.md` gagne pour l'etat reel du code et les priorites factuelles
4. `LLM-FIRST-CONVERSATION.md` gagne sur la doctrine zero determinisme tant qu'elle ne contredit pas le nouveau runtime
5. `PRODUCT.md` gagne pour la promesse produit et le scope
6. `ARCHITECTURE.md` reste contexte technique legacy jusqu'a mise a jour
7. les docs domaine restent utiles pour leur contrat local, sauf contradiction avec le nouveau runtime

## Ordre de lecture

Pour un nouvel agent :

1. `DECISION-RUNTIME-REFACTOR.md` — architecture cible du refactor massif
2. `DECISION-RUNTIME-LEGACY-KILL-LIST.md` — surfaces legacy restantes et ordre de suppression
3. `BUILD-ORDER.md` — etat reel du code et priorites factuelles
4. `LLM-FIRST-CONVERSATION.md` — doctrine zero determinisme sur texte user
5. `SYSTEM-MAP.md` — carte d'ensemble actuelle a verifier contre le nouveau runtime
6. `RUNBOOK.md` — ops, smokes, debug prod
7. `PRODUCT.md` — vision et scope
8. `ARCHITECTURE.md` — contexte technique legacy
9. Docs domaine selon besoin, en gardant le nouveau runtime comme arbitre

## Raccourcis

| Question | Doc |
|----------|-----|
| Quelle est l'architecture cible du gros refactor ? | `DECISION-RUNTIME-REFACTOR.md` |
| Quelles surfaces legacy doit-on couper en Phase 8 ? | `DECISION-RUNTIME-LEGACY-KILL-LIST.md` |
| Ou en est le repo et que construit-on ensuite ? | `BUILD-ORDER.md` |
| Qu'a montre le dogfood API reel du 12 mai et quelle est la remediation ? | `API-DOGFOOD-RELIABILITY-2026-05-12.md` |
| Quelle est la doctrine conversation LLM-first ? | `LLM-FIRST-CONVERSATION.md` |
| Comment fonctionne FitMAS dans son ensemble ? | `SYSTEM-MAP.md` |
| Quel contrat produit ? | `PRODUCT.md` |
| Quelle fondation technique ? | `ARCHITECTURE.md` |
| Comment retablir une verite unique coach/app/planning ? | `DECISION-RUNTIME-REFACTOR.md` |
| Comment eviter les plans valides mais mauvais sportivement ? | `SPORT-QUALITY-REVIEW.md` |
| Qui tranche entre coach, reviewer sportif, runtime et writer ? | `SPORT-QUALITY-REVIEW.md` |
| Comment evoluer le planner ? | `PLANNING.md` |
| Pourquoi le coach se trompe sur le reel, le temps ou l'intention ? | `CONVERSATION.md` |
| Comment evoluer la memoire sans fourre-tout ? | `MEMORY-V2.md` |
| Comment brancher des tools runtime ? | `RUNTIME-TOOLS.md` |
| Comment reduire les prompts et supprimer les prompts defensifs ? | `DECISION-RUNTIME-REFACTOR.md` |
| Comment laisser le LLM proposer une adaptation sans lui donner le commit ? | `DECISION-RUNTIME-REFACTOR.md` |
| Comment redonner au LLM une vue planning propre avant arbitrage ? | `DECISION-RUNTIME-REFACTOR.md` |
| Quelle est la prochaine tranche avant dogfood ? | `BUILD-ORDER.md` |
| Comment l'app doit se comporter ? | `APP-UX.md` |
| Ou lire l'historique des anciens refactors coach ? | `COACH-AUTONOMY-REFACTOR.md` legacy |

## Regles

- Chaque doc a un front matter `summary` + `read_when`
- Quand le comportement change, mettre a jour le doc concerne
- Pas de doc jetable

## Archive

Les anciens documents (cadrage v1, docs absorbes, journaux de refactor termines) sont dans `docs/archive/`.
