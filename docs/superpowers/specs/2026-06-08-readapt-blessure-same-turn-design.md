---
summary: design tranche #1 — ré-adaptation same-turn sous blessure. Sur un « oui mais [douleur/blessure] » répondu à une semaine proposée, le coach note le fait santé ET re-propose dans le MÊME tour une semaine sans intensité, via un param typé déclaré (intensity_restricted) sur propose_week + supersede de l'ancien pending. Indispo/availability et modify hors scope (tranches #2/#3).
read_when:
  - fermer le gap « safe mais pas encore ré-adapté » sous blessure
  - ajouter un param de contrainte déclarée à propose_week / au moteur Meso
  - faire superseder un pending week_proposal par un nouveau
  - réécrire la règle « oui mais » du prompt coach
---

# Design — ré-adaptation same-turn sous blessure (tranche #1)

Contexte : `docs/BUILD-ORDER.md` (tranche #1 = « oui mais [contrainte] » re-propose
proactivement ; état net = *safe, mais pas encore ré-adapté*), `docs/PLANNING-V0.md`
(le LLM génère/déclare, le vérificateur tient l'autorité ; réduction-sous-contrainte),
`docs/superpowers/specs/2026-06-07-slice-3b-pending-resolution-design.md` (le pending +
la résolution ; décision #3 imaginait déjà « oui mais » = reject + proposition fraîche),
`docs/V0-CODE-MAP.md` §9 (flux semaine + comportement « okay mais » actuel). Doctrine dure
(`AGENTS.md`) : aucun regex/keyword sur texte user ; le LLM comprend et émet des artefacts
typés ; le backend valide / commit / audite ; aucune reply ne ment sur un write.

## Découverte qui motive la tranche

Le prompt coach **dit déjà** de re-proposer une semaine adaptée « au tour suivant »
(`prompts/coach_system.py`). Mais en couche 2 live ça **n'arrive jamais** : sur blessure
le coach conseille le repos et ne relance pas ; sur indispo il part en `no_send`. État
net : **safe, mais pas ré-adapté**.

Trois causes mécaniques, vérifiées dans le code :

1. **Snapshot stale (cause racine).** `propose_week` lit `constraints_from_snapshot(snapshot)`
   et le snapshot est construit en **début de tour** (`runtime.py`, `SnapshotBuilder.build`),
   **avant** que le fait blessure noté ce tour-ci soit committé. Une re-proposition same-turn
   génèrerait donc la semaine **dure** (= le danger). C'est ce qui a forcé le choix « N+1 »
   dans la doc : un contournement, pas un choix UX.
2. **Pending non fermé.** Le « oui mais » ne résout pas le pending (correct : ce n'est pas un
   accept), mais il le laisse **OPEN** (`v0_pending_confirmations.status` ∈ open/accepted/
   rejected, pas d'état « held »). Au tour N+1 il reste un pending dur périmé ; re-proposer en
   crée un 2e → 2 pendings ouverts, `snapshot.active_pending` n'en montre qu'un → ambiguïté.
3. **Pas de proactivité réelle.** `heartbeat_tick` → `no_send` en V0 (pas de scheduler core).
   « Proactif au tour N+1 » = en réalité « au prochain message user ». Le trigger est flaky —
   exactement le profil qui meurt en réel.

La cause racine (1) est **solvable** sans heartbeat ni dépendance à un tour suivant. On corrige
à la racine plutôt que de fiabiliser un trigger flaky.

## Décision structurante (brainstorm, 8 juin 2026)

**Same-turn, empathie d'abord.** Sur un « oui mais [douleur/blessure] » répondu à une semaine
proposée, le coach — dans le **même tour** — note le fait santé ET re-propose une semaine sans
intensité, voix empathique (« le genou d'abord, je te cale une version douce, ça te va ? »). On
abandonne la cible « N+1 » : elle contournait une limite au lieu de la corriger, et son trigger
proactif est intrinsèquement flaky.

Sous-décisions tranchées :

1. **Param minimal `intensity_restricted: bool`** (pas un type générique). L'indispo viendra avec
   son propre param de contrainte fenêtre-jours en tranche #2.
2. **Anti-gaming différé.** On n'ajoute **pas** le cross-check « restriction adossée à un fait
   santé ». La restriction ne fait que *réduire* la semaine (sens sûr) et le plancher non-vide du
   vérif borne la baisse ; un faux `intensity_restricted` produit au pire une semaine trop facile,
   jamais dangereuse. Doctrine V0 : le déterminisme grandit **sur preuve de dérive**. Follow-up si
   une sonde montre du gaming. (Esprit V0 : faire ses preuves, pas la perfection.)
3. **Capacité, pas branche forcée.** On *enseigne* la re-proposition same-turn ; le coach **juge**.
   Si la blessure impose clairement le repos seul, il ne propose pas de semaine. Jamais de branche
   déterministe sur le texte.

## Le flux cible

```
Tour N (pending week_proposal OUVERT)  user : « ok mais j'ai mal au genou »
  coach (LLM, comprend le texte) émet, dans le même tour :
    - rider  propose_memory_update(kind="health", text="douleur genou")   ← fait santé
    - action propose_week(..., intensity_restricted=true)                  ← semaine adaptée
  propose_week :
    constraints = constraints_from_snapshot(snapshot)
                ∪ {TypedConstraint(restricts=("intensity",))} si intensity_restricted
    generate_week → verify_week (drop séance clé + plancher relâché + rejet vide)  ← déjà codé
    → ActionProposal(type=week_proposal, week sans intensité)
  policy : create_pending (nouvelle semaine adaptée)
  executor :
    - UpsertMemoryFact (le fait santé)
    - CreatePendingConfirmation(week_proposal)  → marque l'ANCIEN pending week_proposal
      ouvert en "superseded"  (un seul pending vivant)
  reply : empathie + « je te propose une version sans intensité, je cale ? »  (pending → asking)

Tour N+1  user : « oui »
  coach → resolve_pending(accept) sur le pending adapté (mécanisme 3b inchangé)
```

## Composants

### A. `propose_week` apprend une contrainte déclarée
- `meso/runtime_tool.py` : signature gagne `intensity_restricted: bool = False`. Quand `True`,
  fusionner un `TypedConstraint(severity="moderate", restricts=("intensity",), active=True)` avec
  `constraints_from_snapshot(snapshot)` avant de construire le `ContextPack` (dédup si un fait santé
  actif produit déjà la même contrainte).
- `tool_catalog.py` : ajouter le param au `ToolSchema` de `propose_week`, description orientée
  intention — « mets à true quand l'utilisateur vient de signaler une douleur/blessure ce tour-ci
  que le plan de départ ne reflète pas encore ; le moteur supprimera l'intensité ».
- Doctrine : le LLM **déclare** une contrainte typée qu'il a comprise (pas du parsing) ; le moteur la
  consomme ; le **vérificateur** tient l'autorité (réduction-sous-contrainte déjà prouvée,
  `probe_constrained_week` 4/4). Déterminisme = vérif, jamais compréhension.

### B. Un nouveau pending `week_proposal` supersede l'ancien
- `executor.py` : dans le `_apply_*` de `CreatePendingConfirmationCommand`, quand `type=week_proposal`,
  marquer tout pending `week_proposal` ouvert du même user en **`superseded`** avant d'insérer le neuf.
- `db.py` : `superseded` rejoint open/accepted/rejected (commentaire schéma ; pas de migration de
  données nécessaire, c'est une valeur de `status`).
- Règle déterministe **sur artefact** (autorisé). Tue proprement la semaine dangereuse et garantit un
  seul pending vivant. Le first-action-wins de l'agent interdit de faire reject+propose en un tour →
  le supersede **doit** être automatique côté backend, pas une 2e action coach.

### C. Prompt coach — réécriture de la règle « oui mais »
- Aujourd'hui : « note + ne committe pas + tu re-proposeras **au tour suivant** » (ne se déclenche
  jamais).
- Cible : sur « oui mais [douleur/blessure] » → note le fait santé **et, même tour**, appelle
  `propose_week(intensity_restricted=true)` pour offrir une semaine sans intensité, voix empathique.
- Inchangé : jamais `resolve_pending(accept)` sur un « oui mais » ; jamais affirmer une adaptation non
  faite. **Capacité, pas obligation** : si le repos seul s'impose, le coach ne propose pas de semaine.
- **Indispo / availability inchangé** : note + tient ; `no_send` bénin reste acceptable jusqu'à ce
  que l'availability soit typée (tranche #2). Ne pas toucher.

### D. Voix / honnêteté
- Reply : empathie + semaine adaptée présentée comme **proposition** (pending), demande de
  confirmation. Le guard bloque déjà « c'est fait » sur pending ouvert (`pending_action_claim`) →
  **aucun guard neuf**. On vérifie que le contrat reply (`must_not_claim`) reste honnête sur ce tour
  (note fait + proposition, zéro write de plan).

## Error handling / cas limites
- **Générateur échoue** sous restriction → `_template_week` filet (déjà sizé constraint-aware). La
  semaine proposée reste sans intensité.
- **Pas de pending ouvert** au moment du « oui mais » (cas dégénéré) : flux normal `propose_week`,
  pas de supersede (rien à superseder).
- **Blessure + repos clair** : le coach peut ne pas appeler `propose_week` (capacité, pas branche) →
  comportement actuel (note + repos) préservé, c'est valide.
- **Faux `intensity_restricted`** (gaming) : non gardé (décision 2). Borné par le plancher non-vide ;
  un faux fait santé reste un problème d'honnêteté audité, pas de sécurité sportive.

## Tests / preuve

### Couche 1 (filet mécanique, anti-régression)
- Scénario fake : pending `week_proposal` ouvert + tour « oui mais blessure » →
  - fait santé noté (UpsertMemoryFact) ;
  - **nouveau** pending `week_proposal` (semaine **sans séance clé/dure/seuil**) ;
  - ancien pending → `superseded` ;
  - **0 commit** (aucune semaine écrite dans `v0_planned_weeks` ce tour).
- Test unitaire `meso/runtime_tool` : `intensity_restricted=true` → context-pack contient la
  contrainte intensité ; semaine vérifiée sans intensité.
- Les 248 tests restent verts ; fake matrix `11/11` ; danger metrics `0`.

### Couche 2 (où la qualité se juge — DeepSeek)
- Durcir l'oracle de la persona **`blessure`** dans `scripts/v0_eval/probe_live_simulation.py` :
  attendu = une semaine adaptée **proposée** (sans intensité) **dans le tour** du « oui mais »,
  ancienne non committée, guard ok à chaque tour. La barre monte : blessure **re-adapte** au lieu de
  seulement *fail-safe*.
- Personas `indispo` et `fun` : oracle inchangé (toujours fail-safe ; pas de régression).

## Scope / Non-Goals
- **Scope** : blessure / douleur (contrainte santé déjà typée), running-only, toujours `pending`.
- **Hors scope** (tranches suivantes) : availability typée (#2), chemin modify/préférence (#3),
  matérialisation semaine → `v0_scheduled_sessions`, handler commit `plan_patch`, heartbeat proactif,
  anti-gaming cross-check.

## Risques / follow-ups
- **Budget LOC** : core ~4306 / cap 4320 = **14 LOC libres**. A+B+param ≈ 15-25 LOC. Risque de toucher
  le cap → trim au moment du plan, sinon mini re-baseline justifiée et loggée (`RUNTIME-V0.md` Budget).
  À vérifier en premier dans le plan d'implémentation.
- **Anti-gaming** : différé (décision 2), à coder sur preuve de dérive.
- **Tone même-tour** : surveiller en couche 2 que la re-proposition immédiate ne paraisse pas
  expédier la douleur ; le prompt mène par l'empathie. Ajuster la voix si la sonde le montre.
