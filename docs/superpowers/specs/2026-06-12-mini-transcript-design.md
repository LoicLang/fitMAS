---
summary: design mémoire court terme conversationnelle — mini-transcript verbatim (4 derniers échanges, ≤48h) injecté dans le SnapshotHeader, reconstruit en lecture seule depuis v0_input_events × v0_turns, + métrique guard non bloquante warn:confirmation_without_pending. Ferme le trou « chaque tour est amnésique » prouvé en dogfood le 12 juin (proposition → préférence → « c'est bien ça oui » → « je n'ai pas d'info »).
read_when:
  - toucher la continuité cross-tour (snapshot, ConversationState, pendings)
  - modifier le SnapshotHeader ou son budget de mots
  - ajouter une raison ou une métrique au OutputGuard
  - arbitrer mémoire court / moyen / long terme du coach
---

# Design — mini-transcript conversationnel + métrique confirmation_without_pending

Contexte : dogfood réel du 12 juin 2026. Conversation Telegram : « déplace ma séance
d'hier à demain » → le coach propose un fractionné en voix pure (« Tu me confirmes ? »)
sans déposer de pending → « j'aurais préféré un footing » → broderie → « C'est bien ça
oui » → « Je n'ai encore aucune information sous la main ». Le fil meurt à chaque tour.

Doctrine dure (`AGENTS.md`) : aucun regex/keyword sur texte user ; le LLM comprend, le
backend valide/commit/audite ; aucune reply ne ment sur un write. Le guard lit la sortie
du modèle, jamais le texte user.

## Cause racine (vérifiée code)

`WorldSnapshot` (`runtime_v0/snapshot.py`) ne contient **aucun historique de
conversation** — ni le message user précédent, ni la dernière reply du coach.
`InputEvent.text` = message courant seul. La continuité cross-tour repose à 100 % sur
3 artefacts typés : `active_pending` (1 max), `last_unresolved_intent`,
`last_execution_event`.

L'hypothèse « les artefacts typés suffisent » est falsifiée par le dogfood : il suffit
d'une proposition restée en voix (`answer_only`, aucun pending créé — la « reply qui
sur-promet » déjà notée en slice 1.6) pour que le tour suivant parte amnésique. Une
confirmation anaphorique (« c'est bien ça oui ») ou un tour social (« top merci ! »)
devient littéralement vide de sens pour l'agent.

Trou secondaire : le guard bloque « c'est fait » sans write (`claim_without_event`)
mais rien n'instrumente « tu me confirmes ? » sans pending — la promesse fantôme passe
sans friction. Miroir du `event_without_claim` déjà noté en faille ouverte.

## Architecture mémoire (doctrine posée par cette spec)

| Horizon | Mécanisme | Statut |
|---------|-----------|--------|
| Court (ce fil) | transcript verbatim 4 échanges | cette tranche |
| Moyen (cette semaine) | facts typés, pendings, planned weeks | existe |
| Long | contexte en couches, distillation | chantier dédié, après moteur V0 |

Décision explicite : **pas de résumé roulant** des messages plus anciens. Un résumé =
2e appel LLM par tour (latence + coût), nouveau mode d'échec non gardé (un résumé qui
déforme entre dans le contexte sans guard), duplication de la couche facts, et
préemption du chantier contexte dédié (décision Loïc 5 juin : rework profond APRÈS le
moteur V0). Si une info dite il y a 10 messages compte encore, c'est un fait durable →
elle doit devenir un fact typé ; un raté est un bug d'ingestion de facts, pas un
problème de taille de fenêtre.

Verbatim donné au LLM = du contexte, pas du parsing déterministe — conforme doctrine.
Le clip par message est de la troncature budget, pas de la compréhension.

## 1. Transcript — données et rendu

- **Source** : jointure read-only `v0_input_events` (texte user, `occurred_at`,
  filtre `type='user_message'`, `user_id`) × `v0_turns` (reply finale réellement vue
  par l'user, via `event_id`). Aucune nouvelle table, aucun nouveau write path.
- **Fenêtre** : 4 derniers échanges (8 messages max), `occurred_at` ≤ 48 h, **tour
  courant exclu** (son texte est déjà le message du tour ; exclusion par `event_id`).
- **Nouveau champ** : `recent_transcript` sur `WorldSnapshot` + `SnapshotHeader`
  (tuple d'entrées typées role/text/at). Rendu chronologique (plus ancien d'abord)
  dans `to_prompt_text()` :

  ```text
  recent_conversation:
  - [12/06 11:18] user: Mince j'ai loupé ma séance de hier...
  - [12/06 11:18] coach: Salut, rien de calé encore...
  ```

- **Clip** : 300 chars par message, suffixe `…` si tronqué.
- **Budget header** : l'assert `<= 500` mots de `to_prompt_text()` passe à **900**
  (8 messages × ~50 mots). Seul relâchement du budget.
- **Consommateurs** : `agent.py` et le reply LLM reçoivent déjà le header → les deux
  voient le fil, zéro câblage supplémentaire.
- Un tour sans reply persistée (crash avant audit) rend une entrée user seule —
  acceptable, le LLM voit le trou via les timestamps.

## 2. Métrique `warn:confirmation_without_pending` (non bloquante)

- Dans `OutputGuard.verify` : si la reply du modèle **demande une confirmation**
  (patterns sur la sortie modèle — doctrine ok, même statut que `english_leak`) ET
  qu'aucun pending n'est ouvert ni créé ce tour → raison
  `warn:confirmation_without_pending` ajoutée aux reasons **sans bloquer** (`ok`
  reste true, pas de fallback).
- Persistance via `guard_reasons_json` existant ; le préfixe `warn:` garde la forme
  flate actuelle, la matrix compte les warnings par préfixe, séparés des bloquants.
- Le guard a besoin de savoir « pending ouvert ou créé ce tour » : passé via
  `RuntimeResult` (events committés) + l'état pending du snapshot — détail au plan.
- Ne devient bloquante que sur preuve dogfood (récidive malgré le transcript) —
  anti-réactif. Le transcript rend déjà la promesse fantôme non-fatale : le coach
  revoit sa propre proposition au tour suivant et peut la convertir en pending.
- Garde-fou existant rappelé : ne pas laisser grossir la liste de patterns du guard
  (`BUILD-ORDER.md`, failles ouvertes) — si friction répétée, repenser, pas empiler.

## 3. Preuve

Couche 1 :

- builder : fenêtre 4 échanges, coupure 48 h, clip 300 chars, exclusion du tour
  courant, ordre chronologique, user sans reply ;
- rendu header : section `recent_conversation` présente/absente, budget 900 mots ;
- guard : warning émis (demande de confirmation, zéro pending), pas émis (pending
  ouvert ce tour ou créé ce tour), jamais bloquant ;
- matrix fake 11/11 inchangée ; `followup_planning_turn2` (tour de continuation
  existant) doit en profiter.

Couche 2 :

- rejouer la conversation du 12 juin en sonde live non scriptée
  (`probe_live_simulation`, persona « fil de proposition » : proposition → préférence
  → « c'est bien ça oui ») ;
- PASS = le tour 3 est interprété comme la confirmation du fil (pending créé/résolu
  ou clarification ancrée sur la proposition), jamais « je n'ai pas d'info » ;
- danger metrics à 0, guard fallback stable.

## 4. Budget

Cap `test_import_boundaries` 4496 → ~4580 (≈ +80 LOC : requête transcript + rendu +
warning guard). Justification de capacité au landing : « mémoire court terme
conversationnelle, prouvée couche 2 ». Capacité gagnée, pas du creep.

## Hors scope (différé, observé en dogfood)

- Chemin « séance passée manquée » (le mis-aim du tour 1 : « déplace ma séance d'hier »
  → réponse sur aujourd'hui) — observer si le transcript suffit avant de toucher le
  header (`recent_training` est étiqueté week-planning seed).
- Résumé roulant / contexte en couches — chantier dédié après moteur V0.
- Voix / présence (#5 BUILD-ORDER) — le « top merci ! » qui meurt reste un symptôme
  voix, le transcript ne fait que lui donner le contexte.
