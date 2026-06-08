---
summary: réconcilier les deux stores de plan V0 (Meso v0_planned_weeks ↔ calendrier v0_scheduled_sessions) en matérialisant une semaine Meso committée dans le calendrier, pour une vérité unique — débloque injury-after-commit, l'exécution et le patch chirurgical sur une semaine générée.
read_when:
  - toucher au commit d'une semaine Meso (executor _apply_commit_week)
  - comprendre pourquoi get_current_plan était vide après propose_week
  - travailler sur l'adaptation post-commit (blessure/indispo), l'exécution ou propose_plan_patch sur une semaine générée
  - relier le moteur Meso au calendrier jour
---

# Réconciliation des deux stores de plan (Approche A)

> Issu d'un diagnostic (skill systematic-debugging, 8 juin) : la sonde live blessure échoue car le
> coach ne voit pas la semaine committée. Root cause confirmé par le code (voir Contexte).

## Contexte — pourquoi deux stores, pourquoi pas de vérité unique

Deux stores de plan, nés à des moments différents, jamais reliés au commit :

- **`v0_scheduled_sessions`** — le **calendrier jour** (1 ligne = 1 séance/date). Né avec V0
  (`421ff43`). Tout le live opère ici : lecture (`get_current_plan`, snapshot), ajustement
  (`propose_plan_patch` move/lighten/replace), exécution (done/skipped/partial). Le bootstrap prod a
  mis le vrai plan courant ici.
- **`v0_planned_weeks`** — la **semaine conçue par le moteur Meso** (JSON : charge, type clé, 7
  séances). Né plus tard (`b16cedf`). Le coach la génère (`propose_week`) et la commit ici.

**Le bug** : committer une semaine Meso écrit **uniquement** dans `planned_weeks`
(`executor._apply_commit_week`). Le calendrier (`scheduled_sessions`) **reste vide** pour cette
semaine. Donc `get_current_plan`/le snapshot montrent un calendrier vide après une "validation" →
le coach dit littéralement "ton calendrier est vide", ne voit pas la séance dure, et sur une
blessure post-commit il **note le fait sans ré-adapter** (la condition prompt ligne 18 "si des
séances du plan courant sont touchées" est fausse, et `propose_plan_patch` ne peut pas toucher une
séance Meso qui n'a pas de ligne calendrier). Échec attrapé par l'oracle déterministe, **raté par
le juge LLM (5/5/5/5)** — ce qui valide la méthode à deux couches.

C'est le piège nommé par PLANNING-V0 : *"construire le moteur et le runtime entrelacés, jamais deux
tracks boulonnés plus tard."* Le lien manquant **est** le bug.

## Objectif

**Une vérité unique pour le plan jour.** Au commit d'une semaine Meso, matérialiser ses séances dans
`v0_scheduled_sessions`. `planned_weeks` reste la **fiche de conception/provenance** (charge, clé,
forme vérifiée, source) ; `scheduled_sessions` devient la vérité live lue/ajustée/exécutée.

Débloque : injury-after-commit (le coach voit la séance dure → l'allège), le **suivi d'exécution**
sur une semaine générée, et le **patch chirurgical** sur une semaine Meso.

## Approche retenue : A (matérialiser à la validation)

Choisie vs **B** (unifier seulement les lectures → semaine visible mais **pas éditable**, séam
persistant) et **C** (store unique → plus propre à terme mais gros refactor + perte de provenance,
prématuré sur un moteur jeune). A donne la vérité unique de façon **incrémentale et sliçable**, et
reste doctrine-OK : la matérialisation est un **write déterministe dérivé** d'une semaine déjà
vérifiée (déterminisme au commit, pas de génération ; l'executor reste le seul writer ; audité).

---

## §1 — Le pont (executor)

Dans **`executor._apply_commit_week(payload, connection, user_id)`** (le chemin qui insère
aujourd'hui dans `v0_planned_weeks`), après l'insert `planned_weeks`, **matérialiser** les séances
de `week["sessions"]` dans `v0_scheduled_sessions`, **dans la même transaction** (atomique : si la
matérialisation échoue, tout le commit rollback). Émettre **un** event d'audit pour la
matérialisation (planned_week id + nombre de séances posées).

## §2 — Mapping (séance Meso → ligne calendrier)

Séance Meso `{date, type, duration_min, intensity, detail?}` → ligne `v0_scheduled_sessions` :

| Colonne | Valeur |
|---|---|
| `user_id` | user_id de la semaine |
| `date` | `session.date` |
| `sport` | `"running"` (running-only ; convention bootstrap) |
| `title` | libellé FR depuis `type` (dict : `easy_run`→"Footing facile", `long_run`→"Sortie longue", `threshold`→"Seuil", `intervals`→"Intervalles", `recovery_run`→"Récupération") |
| `duration_min` | `session.duration_min` |
| `intensity_label` | `session.intensity` (map 1:1 `easy`/`moderate`/`hard`) |
| `priority` | clé (`type == week.key_type`) → priorité haute ; sinon normale |
| `status` | `"planned"` |

**Décision (a) validée** : les séances `type=="rest"` → **pas de ligne** (repos = absence ;
convention calendrier).

**À confirmer à l'implémentation (vocab exact, mapping 1:1 attendu)** : sortie de `_v0_priority`
(valeurs de priorité), valeur `sport` (`"running"` vs `"run"` — aligner sur l'existant lu par le
snapshot/get_current_plan), vocab `intensity_label`. Si un écart est trouvé, mapper sur le vocab
réellement attendu par les lectures.

## §3 — Sémantique replace / preserve (validée)

Pour `week_start W` (couvre `W..W+6`), dans cette fenêtre de dates, pour ce user :

1. **Supprimer** les lignes `status == 'planned'` (anciennes planifiées : re-commit, ré-adaptation,
   ou reste du plan bootstrap pour cette semaine).
2. **Préserver** toute ligne au statut exécuté (`done` / `skipped` / `partial`) = historique
   intouchable.
3. **Insérer** chaque nouvelle séance Meso (non-rest) **sauf** si une ligne exécutée existe déjà ce
   jour-là (ne pas écraser un jour déjà soldé).

Règle d'or : **"je remplace le planifié, je ne touche jamais à ce qui est déjà fait."** Déterministe,
auditable, idempotent par event (hérite de l'idempotence du commit).

## §4 — Découpage en slices

**Slice 1 — Matérialisation au commit + preserve-exécuté (déterministe).**
Cœur : §1 + §2 + §3 dans `_apply_commit_week`. Maj des ~20-30 tests impactés (ceux qui committaient
une semaine puis attendaient un `get_current_plan` vide → attendent désormais la semaine
matérialisée). **Prouvable couche-1, sans LLM** : commit → `get_current_plan` montre les séances ;
re-commit → remplace le planifié ; une séance `done` est préservée.

**Slice 2 — Injury-after-commit prouvé couche-2.**
Hypothèse forte : Slice 1 **suffit** à débloquer le comportement via le **prompt existant** (ligne
18 : contrainte durable + séances touchées → `propose_plan_patch`). Désormais le coach voit la
séance dure (séances touchées = vrai) ET peut la patcher (ligne calendrier réelle). Vérifier sur la
sonde live blessure : le coach doit **alléger/replace la séance dure** (ou re-proposer) → la semaine
active ne porte plus d'intensité → l'oracle PASSE. **Ajustement prompt seulement si la sonde montre
que le chemin ne se déclenche pas** (ex. une ligne explicitant : sur une douleur, si la semaine
active porte une séance à intensité, allège-la ce tour-ci). Pas de changement prompt spéculatif.

*Hors scope de Slice 2* : injury en **milieu de semaine en cours** dont la correction passerait par
une re-proposition `propose_week` — bloqué par la limite connue "propose_week → prochain lundi
seulement" (tranche séparée). Slice 2 cible le cas prouvé par la sonde : blessure touchant la
semaine committée, corrigée par `propose_plan_patch`.

## §5 — Ce qui change (blast radius)

Après Slice 1, `get_current_plan`/snapshot montrent la semaine committée. Impacts :
- ~20-30 tests touchant `get_current_plan`/`v0_scheduled_sessions`/`planned_week` → maj des attentes.
- Matrix + sondes : le coach voit la semaine → comportement potentiellement différent → re-vérifier
  (danger metrics doivent rester 0).
- Chemin "oui mais" (re-proposition adaptée) : re-commit → re-matérialise (replace). Doit rester vert.

## §6 — Gestion d'erreur

- **Atomique** : matérialisation dans la transaction du commit ; échec → rollback complet, pas de
  demi-état.
- **Idempotent par event** : hérite de l'idempotence du commit existant.
- Séances Meso déjà vérifiées par le verifier → insert ne devrait pas échouer ; si malformé →
  rollback → safe.

## Gate de vérification (BLOQUANT)

**Slice 1 :**
- `pytest tests/runtime_v0` vert (compte mis à jour, attentes corrigées).
- Nouveaux tests : (1) commit Meso → `get_current_plan` montre les séances non-rest mappées ;
  (2) re-commit même semaine → planifié remplacé, pas de doublon ; (3) une séance `done` dans la
  fenêtre est préservée et non écrasée ; (4) jour `rest` → aucune ligne.
- `run_matrix.py --provider fake --repetitions 1` → 11/11, **danger metrics 0**.

**Slice 2 :**
- Sonde live blessure (`probe_live_simulation --persona blessure`) → **PASS** (oracle : semaine
  active sans intensité après la douleur ; guard ok ; no auto-commit).
- Non-régression : sonde indispo PASS ; matrix danger metrics 0.

## Risques & mitigations

| Risque | Mitigation |
|---|---|
| Blast radius (coach voit la semaine partout) | Slice 1 déterministe d'abord + gate complet ; couche-2 ensuite |
| Replace efface de l'exécuté | Règle §3 explicite + test (3) preserve-`done` ; jamais toucher non-`planned` |
| Vocab mapping faux (sport/priority/intensity) | Confirmer sur le code existant à l'impl ; mapper sur ce que lisent réellement les reads |
| Slice 2 ne se déclenche pas | Ajustement prompt minimal ciblé (pas spéculatif) ; re-sonde |
| Régression danger | Gate exige danger metrics 0 sur matrix + oracles couche-2 |

## Hors scope

- **C (store unique)** : consolidation future si `planned_weeks` s'avère inutile post-A.
- **`propose_week` "cette semaine"** (re-planifier la semaine en cours, pas seulement le prochain
  lundi) — tranche séparée (BUILD-ORDER).
- Multi-sport, périodisation long-terme.
- Backfill des semaines Meso committées **avant** ce fix (forward-only ; en prod le plan courant est
  déjà dans `scheduled_sessions` via le bootstrap, les semaines futures Meso seront matérialisées au
  prochain (re)commit).
