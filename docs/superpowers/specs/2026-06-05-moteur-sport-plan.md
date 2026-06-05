---
summary: plan du chantier moteur sport V0 (Meso semaine) — slices, doctrine, décisions, gates de preuve. Guide de la journée du 5 juin 2026.
read_when:
  - démarrer le chantier moteur sport V0
  - savoir quel slice on construit et dans quel ordre
  - retrouver les décisions arrêtées et les questions ouvertes
  - vérifier qu'un travail moteur respecte la doctrine LLM-génère / vérif-tient-l'autorité
---

# Plan Chantier Moteur Sport V0 — Guide Du Jour (5 juin 2026)

Guide de travail pour la journée. L'architecture cible durable est dans
`docs/PLANNING-V0.md` (on ne la rouvre pas). Ce doc = la **découpe en slices** et
les **décisions** qui en découlent.

## North Star

Le plus petit coach Telegram fiable pour 1-2 semaines de dogfood. Le moteur sport
fait passer V0 du niveau **séance** (déjà prouvé) au niveau **semaine** (Meso).

## Doctrine (non rouvrable)

- Le **LLM génère** et personnalise. Un **vérificateur déterministe tient l'autorité**.
- Le moteur = des **tools coach-callables**, **co-évolue** avec le runtime. Jamais
  deux chantiers séparés. On grandit **un tool à la fois**, chacun prouvé en couche 2.
- **Running-only** d'abord. **Meso continuité** seulement. **Tout Meso en pending**
  (jamais d'auto-commit d'une semaine).
- Le **cut LLM↔déterministe se découvre empiriquement** : démarrer ~100% LLM + un
  vérif sécurité **minimal** ; le déterministe ne grossit que **sur preuve de dérive**.
- L'usine planning de l'app est **à strangler, pas à brancher** (rigide / buggée).

## La Distinction Qui Débloque : vérifier ≠ juger le contenu

Le vérificateur ne lit **jamais** le contenu libre d'une séance. Il check un
**squelette typé** (nombres + enums). Le détail prose (échauffement, sensations,
42 vs 45 min) reste **au LLM, non vérifié** (faible enjeu).

Le truc qui rend ça déterministe : **on type la sortie du LLM**. Chaque séance =
`{type: enum, durée: int, charge: number, is_key/is_hard/is_impact: bool, detail: prose}`.
Le vérif lit les champs typés, jamais la prose.

Carte d'autorité :

```
LLM                  → génère + personnalise (tout sauf le squelette à enjeu)
Vérificateur det.    → SÉCURITÉ + STRUCTURE (nombres, enums) — gate dur
Humain @ pending     → QUALITÉ / pertinence — le dernier mot (tout Meso est pending)
```

**LLM-as-judge comme autorité = interdit** : ça ne fait que déplacer l'aléatoire du
générateur vers le juge. Au mieux, plus tard, un critic LLM = feedback advisory dans
la boucle de régénération, **jamais** le gate.

## Santé — comment c'est déterministe

- À l'**ingestion** (le runtime comprend le texte user), le fact santé est **typé** :
  `{severity, restricts: [intensity|impact|all], expires_at}`. Le LLM comprend
  "tendinite genou" → `severe, restricts=[impact,intensity]`.
- Chaque séance porte des attributs typés (`is_hard`, `is_impact`).
- Vérif = **intersection sur champs typés** (`restricts` ∩ attrs séance). Sévérité
  décide : `severe → block`, sinon `pending/flag`.
- **Plancher ambiguïté** : typage incertain → **pending**, jamais "allow" silencieux.
- L'autorité tient parce que le fact est typé **à l'ingestion, séparément de la
  génération** : le générateur ne peut pas le ré-adoucir.
- En Meso, **tout est pending** → la santé n'a pas à adjuger parfaitement : bloquer
  les red-flags + faire remonter le conflit. L'humain tranche.

### Trou identifié (5 juin) : pas de rétractation de fact

`runtime_v0` sait **créer** un fact santé (`propose_memory_update` → INSERT dans
`v0_facts`) et l'**expirer dans le temps** (`expires_at`, posé à la création). Mais
**aucun chemin de rétractation** : `_apply_upsert_memory_fact` est un INSERT pur (le
nom `UpsertMemoryFactCommand` ment). "C'est bon, douleur passée" ne peut qu'ajouter
un fact contradictoire ; l'ancien reste **actif** jusqu'à son `expires_at`. Le vérif
continuerait de bloquer sur une blessure résolue. → **Slice 1.5** (tool de résolution
LLM-first + `resolved_at`). Indépendant du moteur (bug latent du runtime), ramassé au
passage. Ne bloque pas le vérif (testé en fixtures).

**Statut : FAIT (5 juin 2026).** `propose_fact_resolution(fact_id, reason)` →
`ResolveMemoryFactCommand` → `resolved_at` ; le snapshot droppe les facts résolus ; la
policy ground l'id contre les facts actifs (`ask_clarification` si inconnu). Prouvé
couche 2 (DeepSeek ×4 formulations) : 4/4 résolus, 0 fact contradictoire empilé,
`guard_ok`, replies justes.

## Le Socle : le modèle typé partagé

Vérif **et** context-pack consomment le même modèle. Donc on pose **le modèle typé
d'abord** (Slice 0). Quatre types : `WeekTarget`, `TypedSession`, `TypedConstraint`,
`WeekActuals`. Détail dans la spec Slice 0+1.

## Les Slices (chacun prouvé avant le suivant)

| Slice | Quoi | Preuve (gate) |
|---|---|---|
| **0 — Socle** ✅ | modèle typé Meso + dérivation de cible (continuité). Pur, pas de LLM, pas de DB. | tests unitaires modèle + dérivation |
| **1 — Vérificateur** ✅ | les 5 propriétés (anti-TSS-drop, type-clé, ramp borné, espacement, santé). Déterministe, maigre. | fixtures écrites main **+ rejeu de la semaine "TSS qui chute" de l'app → doit l'attraper** |
| **1.5 — Résolution de fact** ✅ | tool `resolve` LLM-first + colonne `resolved_at`. Prérequis dogfood, pas le vérif. | sonde : "c'est bon douleur passée" → fact cesse d'être actif, audité |
| **2 — Context-pack + générateur** | distillation snapshot→pack, LLM génère semaine typée, boucle generate→verify (max ~3, filet template). | **générer 4-6 semaines offline → vérif à la main de la progression vs app** |
| **3 — Tool runtime** | `propose_week` coach-callable → moteur → vérif → policy → **pending**. | **couche 2** live sous-agent |

Fait le 5 juin : **Slice 0, 1, 1.5** (specs `2026-06-05-moteur-sport-*`). Suite : Slice 2.

## Décisions Arrêtées (defaults V0, révisables empiriquement)

1. **Charge running** (vérifiable à la main, pas le vrai TSS) :
   `load = Σ(durée_min × poids_intensité)`, poids `easy=1.0 / moderate=1.5 / hard=2.0`.
   Le vrai TSS (allure/FC) = plus tard.
2. **Source de cible** : en **continuité**, la cible se **dérive de la semaine passée
   réelle** (porte le `key_type`, rampe la charge dans une bande). Pas besoin de Macro.
   Le LLM ne **déclare** qu'une **transition** (changement de phase) → mode transition
   + pending.
3. **Vérif d'abord** (Slice 0→1 avant le contexte) = premier chantier.

## Questions Ouvertes (à trancher EMPIRIQUEMENT)

- Résolution de fact (Slice 1.5) : **auto-commit + accusé** (penchant) ou pending ?
- Jusqu'où le contexte seul porte la cohérence sur 6 semaines avant un ancrage
  déterministe sur la charge **cumulée** ? (`PLANNING-V0.md` Q1)
- Mix génération templates-vs-LLM par type de séance. (Q2)
- Localisation exacte du cut (découverte par le test 4-6 semaines). (Q3)

## Gates De Preuve

- **Couche 1** (filet mécanique) : fixtures vérificateur vertes, dont le rejeu app.
- **Couche 2** (le juge) : une vraie conversation non scriptée tient. Rien n'est
  "done" sur un chiffre de matrice.

## Règles Dures (rappel)

- LLM comprend / génère ; backend valide, autorise, commit, audite.
- Pas de regex/keyword sur texte user libre (y compris "c'est bon"/"passé").
- Aucun write DB hors executor officiel. Aucune reply ne ment sur un write.
- `runtime_v0` reste isolé.
