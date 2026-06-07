---
summary: design Slice 3b — mécanisme général de résolution de pending (pending_resolution LLM-first) + premier handler de commit = la semaine typée (store v0_planned_weeks) + chaînage forward. Matérialisation vers le plan exécutable et handler de commit plan_patch différés.
read_when:
  - construire la résolution de pending (confirmation -> commit) dans le runtime V0
  - ajouter un type d'action pending_resolution / un tool resolve_pending
  - committer une semaine Meso typée et la chaîner en forward
  - comprendre pourquoi un pending V0 était create-only (payload_json write-only)
---

# Design — Slice 3b : résolution de pending + commit semaine

Contexte : `docs/PLANNING-V0.md` (archi moteur), `docs/BUILD-ORDER.md` (Slice 3b =
confirmation -> commit -> store typé -> chaînage), `docs/superpowers/specs/2026-06-06-slice-3a-propose-week-design.md`
(propose_week, qui s'arrête à `answer_only` faute de résolution), `docs/V0-DOGFOOD-SCOPE.md`
(tout Meso reste pending). Doctrine dure (`AGENTS.md`) : les réponses à un pending
(`oui`/`non`/"oui mais…") sont interprétées par le LLM via un `pending_resolution`
structuré — jamais de regex sur le texte.

## Découverte qui motive le slice

La **résolution de pending n'existe pas encore**. Le runtime sait *créer* un pending
(swap / clé / multi-op → `create_pending`, `payload_json` complet stocké), mais :

- **aucun code ne relit `payload_json`** (write-only) ;
- **aucun type `pending_resolution`**, aucun tool de confirmation, aucune branche policy
  qui prend une réponse utilisateur + le pending ouvert → commit ;
- le snapshot **montre** le pending au LLM (`pending: <id> <summary>`) mais le tour
  suivant ne peut rien committer.

Conséquence : un « oui » à un swap proposé ne commit rien (trou dogfood latent), et c'est
pourquoi `propose_week` (3a) s'arrête à `answer_only`. 3b construit donc le **mécanisme
général**, dont la semaine est le **premier payload committable**.

## Décisions (tranchées en brainstorm, 7 juin 2026)

1. **Mécanisme général** `pending_resolution` + **un** handler de commit : la semaine.
   Le rejeu plan_patch (swap/clé/multi-op) bénéficiera du même mécanisme mais son handler
   de commit est **différé** (executor fail-loud sur ce type pour l'instant).
2. **Store typé seul** : commit écrit la semaine dans une nouvelle table `v0_planned_weeks`
   (source Meso : chaînage forward + audit). **Pas** de matérialisation vers
   `v0_scheduled_sessions` dans ce slice → zéro dual-write, zéro migration du plan exécutable.
   Trou assumé : la semaine validée n'apparaît pas encore dans le plan exécutable
   (`get_current_plan`). Matérialisation = follow-up dédié.
3. **accept / reject seulement**. Un « oui mais… » est lu par le LLM comme reject +
   nouvelle proposition fraîche (ex : re-`propose_week` avec seed ajusté). Pas de surface
   `modify` (cible floue sur une semaine non-matérialisée).
4. **Commit lean, pas de re-verify au commit** : la semaine committée est celle vérifiée
   au tour 1 (fenêtre d'expiry courte). Re-vérifier contre les contraintes courantes au
   moment de l'accept = **follow-up sécurité** (voir Non-Goals).

## Le flux

```
Tour 1  propose_week → policy CREATE_PENDING (type=week_proposal,
        payload_json = proposal_to_dict, summary = résumé semaine)   ← change 3a
        reply (ton asking) "je te propose X, je cale ?"
Tour 2  user "oui" / "non"
        coach voit `pending: <id>` dans le header
        → emet pending_resolution{pending_id, decision: accept|reject}
        policy grounde pending_id vs snapshot.active_pending.id
            (sinon ask_clarification)
        → ResolvePendingConfirmationCommand(pending_id, decision, note)
        executor:
            accept → charge le pending, dispatch par type :
                     week_proposal → insert v0_planned_weeks + pending status='accepted'
                     autre (plan_patch) → fail loud (handler différé)
            reject → pending status='rejected', zéro write métier
        reply: accept → ton confirming porté par la semaine committée
               reject → accusé d'annulation
```

`resolve_pending` est exposé dans le catalogue **uniquement quand `snapshot.active_pending`
est non nul**, et **coexiste** avec le toolset complet : le LLM choisit librement entre
résoudre, démarrer une autre action, ou re-proposer. Aucun branchement déterministe sur le
texte « oui ».

## Composants

LOC indicatif entre parenthèses.

1. **proposals.py** (~20) — `ActionProposal.type` gagne `"pending_resolution"` ;
   `PendingResolutionDraft{pending_id: int, decision: Literal["accept","reject"], note: str = ""}` ;
   champ `pending_resolution` + (dé)sérialisation `_pending_resolution_from_dict`.
2. **tools_proposal.py** (~15) — `resolve_pending(ctx, pending_id, decision, note="")`
   → `ActionProposal(type="pending_resolution", ...)`, `is_proposal=True`, `_record`/`_trace`.
3. **tool_catalog.py** (~15) — schéma `resolve_pending` (`pending_id:int`, `decision:enum[accept,reject]`,
   `note:str`), ajouté à la tuple **si `snapshot.active_pending is not None`**.
4. **policy.py** (~25) — branche `_pending_resolution(proposal, snapshot)` :
   - draft None → `block` ;
   - grounding : `snapshot.active_pending is None or draft.pending_id != snapshot.active_pending.id`
     → `ask_clarification` ("De quelle proposition tu parles ?") ;
   - decision accept/reject → `allow_commit` avec `ResolvePendingConfirmationCommand` ;
   - reply_facts = accusé court (résumé du pending / note).
   **+** la branche `week_proposal` passe de `answer_only` → `create_pending`
   (`CreatePendingConfirmationCommand(type="week_proposal", summary=<résumé>,
   payload_json=proposal_to_dict(proposal), expires_at=now+24h)`), comme plan_patch.
5. **executor.py** (~40) — `ResolvePendingConfirmationCommand` + `_apply_resolve_pending` :
   charge la ligne pending (open, user) ou raise ; reject → `status='rejected'` ;
   accept → parse `payload_json`, dispatch par `pending["type"]` :
   `week_proposal` → `_apply_commit_week` (insert `v0_planned_weeks`) + `status='accepted'` ;
   type non câblé → raise `pending_commit_not_supported_for_type:<type>` (fail loud).
   `_target` → `("pending", str(pending_id))`.
6. **db.py** (~15) — table `v0_planned_weeks` :
   `{id, user_id, week_start TEXT, source TEXT, week_load REAL, key_type TEXT,
   sessions_json TEXT, status TEXT DEFAULT 'committed', created_at}` ; ajout à `V0_TABLES`.
   `sessions_json` = la semaine typée (liste `{date,type,duration_min,intensity,detail}`) →
   permet de reconstruire le `PlannedWeek` ; `week_load`+`key_type` = les actuals réduits
   (chaînage direct sans relire toutes les séances).
7. **snapshot.py** (~12) — charge la **dernière semaine committée** de `v0_planned_weeks`
   → champ `last_planned_week: WeekActuals | None` (`week_load`→`total_load`, `key_type`).
   **Pas** de ligne dans le header (le coach n'en a pas besoin en texte → protège le ratchet).
8. **meso/runtime_tool.py** (~8) — `propose_week` **préfère** `snapshot.last_planned_week`
   comme actuals (chaînage forward) ; le seed LLM-déclaré (`last_week_load`, `key_type`)
   devient le **fallback cold-start** (comportement 3a quand aucune semaine committée).
9. **reply.py** (~10) — `pending_resolution` accept → ton `confirming` porté par la semaine
   committée ; reject → accusé d'annulation. Le `week_proposal` (désormais pending) réutilise
   le chemin reply pending existant (`_pending_confirmation`).

Total ~160 LOC. Le cap `test_import_boundaries` monte **au landing** (~4250), justifié par
capacité prouvée (la note du test prévoit déjà ce bump pour 3b).

## Data flow & autorité

- **Le LLM** comprend la réponse au pending et émet `pending_resolution` structuré.
- **La policy** tient l'autorité : grounde l'id contre la vérité DB, autorise accept/reject.
- **L'executor** applique : charge le payload stocké, dispatch le commit par type, écrit le
  store, marque le pending. Détermine le commit côté tractable (rejeu d'un artefact déjà
  vérifié), jamais de la génération.
- **Le guard** : sur accept, un event métier existe (ligne semaine créée) → la reply peut
  dire « validé ». Sur reject / sur le tour propose→pending, aucun write métier → la reply
  ne peut pas mentir « c'est fait ».

## Erreurs & sécurité

- **Grounding** : `pending_id` LLM validé vs `snapshot.active_pending.id`. Le snapshot ne
  charge que les pending `open` non-expirés (`expires_at > now`, limit 1). Faux id / pending
  déjà résolu / expiré → `ask_clarification`. Calqué sur `fact_resolution`.
- **Idempotence** : re-accept dans le même tour → dédup `_load_existing_event`
  (`UNIQUE(turn_id, command_type, target_id)`). Re-accept cross-tour d'un pending non-`open`
  → grounding échoue (snapshot ne le charge plus) → `ask_clarification`. Pas de double-write.
- **Reject = honnêteté** : aucun event métier ; la reply accuse l'annulation sans rien
  affirmer de committé.

## Tests

Couche 1 (filet mécanique) :

- store : write/read `v0_planned_weeks` ;
- executor : accept (semaine) → ligne store + pending `accepted` ; reject → pending
  `rejected`, zéro ligne store ; accept d'un type non supporté → fail loud ;
- policy : grounding `pending_resolution` (mauvais id → clarification) ;
  `week_proposal` → `create_pending` (changé depuis `answer_only`) ;
- catalog : `resolve_pending` exposé ssi pending ouvert ;
- **chaînage** : commit semaine A → `propose_week` seede depuis A (forward) ;
- fake matrix : nouveau scénario propose→oui→commit (anti-régression).

Couche 2 (la vraie barre, DeepSeek) : sonde « fais-moi ma semaine prochaine » → « oui »
→ semaine committée, reply honnête (« c'est calé », jamais « c'est fait » au tour 1).
Sonde miroir « non » → annulation propre, zéro write.

## Non-Goals (différés, accommodés mais pas codés)

- **Matérialisation** de la semaine committée vers `v0_scheduled_sessions` (plan exécutable).
  Décision dédiée plus tard (question source-unique vs dual-write, leçon legacy).
- **Handler de commit plan_patch** (rejeu d'un swap/clé/multi-op confirmé). Le mécanisme le
  porte ; l'executor fail-loud sur ce type jusqu'à câblage.
- **Re-verify au commit** : si un fait santé bloquant apparaît entre propose et accept, la
  semaine vérifiée au tour 1 est committée telle quelle. Follow-up sécurité (re-run
  `verify_week` contre les contraintes courantes sur accept → block + re-propose).
- **decision=modify** ("oui mais…" capturé en un tour).
- **Multi-pending simultanés** : V0 traite un pending ouvert à la fois (snapshot limit 1).

## Règles dures respectées

- LLM comprend la réponse au pending → artefact structuré ; backend valide/commit/audite.
- Aucun regex/keyword sur « oui »/« non ».
- Aucun write DB hors executor ; aucune reply ne ment sur un write.
- Determinisme = grounding/validation/commit/audit, jamais compréhension ni génération.
- Tout Meso reste pending (commit uniquement sur confirmation explicite).
