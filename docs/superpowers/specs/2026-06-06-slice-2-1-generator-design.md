---
summary: design Slice 2.1 (le générateur) du moteur sport V0 — le LLM génère une semaine typée depuis le ContextPack, une boucle generate->verify la juge, template en filet. Tier 2 (anti-drop contrainte-aware). Offline, running-only, continuité, tout pending.
read_when:
  - coder le générateur Meso (generate_week, boucle generate->verify)
  - décider du cut LLM vs déterministe sur la génération de semaine
  - ajouter/modifier l'anti-drop contrainte-aware du vérificateur
  - préparer le câblage runtime coach-tool (Slice 3) ou l'éval offline 4-6 semaines
---

# Design — Moteur Sport V0, Slice 2.1 (le générateur)

Contexte : `docs/PLANNING-V0.md` (archi cible), `docs/superpowers/specs/2026-06-05-moteur-sport-plan.md`
(plan + décisions), `docs/superpowers/specs/2026-06-05-slice-2-0-voie-b-design.md`
(le ContextPack que ce slice consomme).

## Objectif

Le **générateur** : le LLM produit une **semaine typée** (`PlannedWeek`) depuis le
`ContextPack`, une **boucle `generate->verify`** la juge (vérificateur Slice 1), avec
un **template en filet** après échecs. C'est la première fois que le moteur **produit**
une semaine — Slice 2.0 n'a posé que le contrat d'entrée (le pack).

Doctrine : le **LLM génère et personnalise** ; le **vérificateur + la policy tiennent
l'autorité** ; tout Meso est **pending** (jamais d'auto-commit d'une semaine).

## Décisions arrêtées (forks tranchés)

1. **Tier 2** (scope) : générateur + boucle + **anti-drop contrainte-aware**. Hors :
   anti-gaming par mode déclaré + transition complète (**Tier 3, différés**) ; câblage
   runtime coach-tool (**Slice 3**).
2. **LLM-first** : le LLM génère toute la semaine ; le template n'intervient **qu'en
   fallback** (après ~3 échecs `generate->verify`). Suit la doctrine anti-réactive
   (le déterministe grossit sur preuve de dérive ; on découvre empiriquement où le LLM
   dérape avant d'ajouter des templates).
3. **Cold-start différé** : le générateur **exige un `target`** (continuité). Si
   `pack.target is None` (cold-start, aucune semaine typée avant), c'est **non-applicable**
   → le seed de la première semaine est différé (Slice 3 / dogfood). L'éval offline
   fournit toujours un seed `WeekActuals`.

## Non-objectifs (explicitement hors slice)

- Pas de **câblage runtime** (`propose_week` coach-callable, policy, audit) → Slice 3.
- Pas d'**anti-gaming par mode déclaré** ni de **mode transition** complet → Tier 3.
- Pas de **seed cold-start** (génération de la 1ère semaine sans actuals).
- Pas de **multi-sport** ni de **macro/périodisation**.
- Pas de **signals** consommés (slot resté vide en 2.0 ; consommation = sur preuve).

## Le générateur (`meso/generator.py`, nouveau)

Imports : `meso.model`, `meso.verifier`, `llm_clients.base` — tous **internes à
`runtime_v0`**, donc l'isolation tient (interdits inchangés :
`fitmas.decision/domain/llm/skills/tools/app`). Les **vrais providers**
(DeepSeek/Mistral/Grok) restent dans `scripts/v0_eval/` (hors core) ; le générateur
prend un `LLMClient` **injecté** (le `fake.py` sert les tests unitaires).

```python
EMIT_WEEK_TOOL: ToolSchema     # le LLM émet la semaine typée via les args de ce tool

@dataclass(frozen=True)
class WeekProposal:
    week: PlannedWeek
    verdict: WeekVerdict                       # toujours requires_pending=True
    source: Literal["llm", "template_fallback"]
    attempts: int

def generate_week(
    llm: LLMClient,
    pack: ContextPack,
    mode: Mode = "continuity",
    max_attempts: int = 3,
) -> WeekProposal
```

`generate_week` exige `pack.target is not None` (sinon `ValueError` — cold-start hors
scope). Le résultat est **toujours pending**.

## La boucle generate->verify

```
1. rendre le pack en prompt de génération (target: bande+key_type+phase ; actuals ;
   constraints typées) + consigne "émets la semaine via le tool emit_week".
2. pour chaque tentative (max_attempts, défaut 3) :
   a. llm.chat_with_tools(system, messages, [EMIT_WEEK_TOOL])
   b. parser les args du tool-call -> PlannedWeek :
        - prose / aucun tool-call  -> message contrat ("émets via emit_week, pas de
          prose") -> retry (réparation, jamais accepter une sortie invalide en silence)
        - args invalides (enum/typage) -> message d'erreur structuré -> retry
   c. verify_week(week, pack.target, pack.constraints, mode)
        - PASS -> return WeekProposal(week, verdict, "llm", tentative)
        - FAIL -> append LES violations structurées au fil de messages -> retry
3. après max_attempts -> template fallback : semaine running standard déterministe
   dérivée de pack.target (1 séance clé de target.key_type au milieu de la bande,
   footings faciles, respecte les contraintes actives) -> verify_week -> WeekProposal(
   week_template, verdict, "template_fallback", max_attempts).
```

- Feedback de boucle = **violations structurées** (le `Violation{code, detail, severity}`
  du vérif), pas du texte libre.
- Réparation prose : DeepSeek peut émettre de la prose après tool-use ; on **répare**
  (re-prompt une fois via le contrat), on n'accepte **jamais** une décision finale
  invalide en silence. (Même posture que `agent.py`.)
- Le **détail prose** des séances (`detail`) reste au LLM, **jamais lu** par le vérif.

## Sortie structurée (le typage du LLM)

`EMIT_WEEK_TOOL` expose un schéma : `sessions: [{date, type (enum SessionType),
duration_min (int), intensity (enum Intensity), detail (str libre)}]`. Le handler
construit les `TypedSession` -> `PlannedWeek`. C'est **le** point où la sortie LLM
devient typée (le truc qui rend la suite déterministe) — exactement le pattern des
proposal-tools de l'agent (`tools_proposal.py`), réutilisé.

## Anti-drop contrainte-aware (`meso/verifier.py`, modif ~15 LOC)

En **continuité**, si une **contrainte active restreint `intensity` ou `all`** (elle
interdit la séance clé dure), on **relâche** :
- `load_drop` (la chute de charge est **expliquée** par la contrainte, pas le bug app) ;
- les checks de clé (`key_session_count`, `key_type_drift`) — on ne peut pas prescrire
  une clé dure quand l'intensité est interdite ("enforce la structure de **ce qui
  reste**").

Restent **enforced** : `load_spike` (pas de sur-charge sous contrainte),
`hard_back_to_back`, `health_conflict`, et **pending**.

**Anti-gaming par construction** : la relaxation est pilotée par les contraintes **du
pack** — typées par le runtime **à l'ingestion**, **pas déclarées par le générateur**.
Le générateur ne peut donc pas fabriquer une contrainte pour esquiver l'anti-drop. Le
mode déclaré + sa validation déterministe (Tier 3) sont **inutiles ici** ; ils ne se
codent que quand la génération **déclarera** un mode (transition).

Implémentation : `_check_load_continuity` et `_check_key` reçoivent un booléen
`key_relaxed` calculé dans `verify_week` (`any(c.active and {"intensity","all"} &
set(c.restricts) for c in constraints)`). Si vrai : `load_drop` et les checks de clé
sont sautés. Aucune nouvelle entrée/sortie.

## Architecture / fichiers

```
backend/src/fitmas/runtime_v0/meso/generator.py        # nouveau (~140 LOC)
backend/src/fitmas/runtime_v0/meso/verifier.py         # modif (~15 LOC, relaxation)
backend/src/fitmas/runtime_v0/prompts/week_generation.py  # nouveau (~40 LOC, le prompt)
tests/runtime_v0/test_meso_generator.py                # nouveau (fake LLMClient)
tests/runtime_v0/test_meso_verifier.py                 # étendu (relaxation)
scripts/v0_eval/generate_weeks.py                      # nouveau, HORS core (vrai provider)
```

Contraintes : `meso/generator.py` n'importe que des modules **internes à `runtime_v0`**.
Le générateur est la partie qui **appelle le LLM** — il n'est plus "domaine pur" (c'est
attendu), mais reste isolé du produit legacy.

## Plan de test (la preuve du slice)

**Couche 1 — unitaire, déterministe (fake `LLMClient`)** `test_meso_generator.py` :
1. **PASS 1er coup** : le fake émet une semaine build saine -> `source="llm"`,
   `attempts=1`, `verdict.ok`.
2. **Échec puis PASS** : le fake émet une semaine `load_drop` puis une bonne ->
   `attempts=2`, `verdict.ok`, et la 2e tentative a bien reçu la violation.
3. **Max -> fallback** : le fake émet toujours une semaine invalide -> 3 tentatives ->
   `source="template_fallback"`, et le template vérifie.
4. **Prose-only -> réparation** : le fake émet de la prose sans tool-call -> message
   contrat ré-émis -> tentative suivante.
5. **Contrainte relâche** : pack avec contrainte `intensity` active + semaine sans clé
   et charge basse -> pas de `load_drop` ni de violation de clé (relaxation), mais
   `load_spike`/`health_conflict` toujours actifs si déclenchés.
6. `generate_week` avec `pack.target is None` -> `ValueError` (cold-start hors scope).

`test_meso_verifier.py` étendu : la relaxation contrainte-aware isolée (load bas +
contrainte intensity active -> `ok`, vs sans contrainte -> `load_drop`).

**Couche 2 — offline 4-6 semaines, vrai provider** `scripts/v0_eval/generate_weeks.py` :
seed `WeekActuals` -> `build_context_pack` -> `generate_week` (DeepSeek) -> verify ->
`actuals_from_week` -> répète sur 4-6 semaines. **Vérification à la main** de la
cohérence/progression, **comparée au vécu app** (le cas TSS qui chute). Exports non
committés (re-jouables). Rien n'est "done" sur un chiffre couche 1.

## Critère "Done"

- `pytest tests/runtime_v0` vert (aucune régression).
- La boucle est prouvée déterministe sur le fake (PASS / retry / fallback / réparation /
  relaxation).
- L'offline 4-6 semaines tourne sur un vrai provider et tient la cohérence à la main
  (couche 2), au moins à parité avec l'app sur les scénarios couverts, **fail-safe** là
  où l'app fail-dangerous (TSS qui chute).
- `meso/generator.py` n'importe aucune couche interdite ; tout Meso reste **pending**.
- Doc à jour ; budget LOC tranché (voir ci-dessous).

## Impact budget LOC (à trancher à l'implé)

~195 LOC core ajoutées -> ~3711 -> **~3906**, au-dessus du cap 3720. 2.1 est **le cœur**
du moteur (vraie croissance, pas du creep) -> le cap remontera franchement (~3950, à
fixer sur le compte réel mesuré). Gros saut **assumé et signalé d'avance**. Question
ouverte : le prompt en `.py` (~40 LOC) compte-t-il comme "core" ou comme contenu
exclu (comme `adapters/`) ? À trancher à l'implé.

## Règles dures (rappel)

- Le LLM génère / comprend ; le **vérificateur + la policy** tiennent l'autorité.
- Aucun regex/keyword sur texte user libre. Le vérif ne lit que des **champs typés**.
- Aucun write DB hors executor officiel ; aucune reply ne ment sur un write.
- `runtime_v0` reste isolé ; tout Meso reste **pending** (jamais d'auto-commit semaine).
