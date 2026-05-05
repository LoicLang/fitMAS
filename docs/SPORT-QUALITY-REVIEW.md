---
summary: doctrine et architecture Phase A+ pour review sportive, coherence semaine, prescription seance et progression par stimulus
read_when:
  - lancer Phase A+ Weekly Coherence Review
  - ajouter validate_week_coherence
  - modifier PlanMutationService autour d un PlanPatch
  - reviewer une semaine generee avant commit
  - concevoir SessionPrescriptionEngine ou SessionQualityReviewer
  - travailler sur progression, zones, VMA, FTP ou CSS
---

# Sport Quality Review

## Role canonique

Ce document fixe la doctrine FitMAS pour la qualite sportive des plans.

Objectif :

```text
Eviter les plans techniquement valides mais sportivement mediocres.
```

Doctrine cible :

```text
Le coach propose.
Le reviewer sportif challenge.
La policy backend tranche.
Le writer applique.
Le coach explique.
```

Traduction en responsabilites :

```text
Reviewer = autorite sportive.
Runtime = autorite systeme.
PlanMutationService = effet DB.
Coach = relation + explication.
```

Cette couche est Phase A+. Elle ne lance pas Phase B prescription/progression
complete. Elle ajoute une gate sportive entre `PlanPatch` et commit.

## Pourquoi maintenant

Phase A a rendu le coach conversationnel plus libre :

- il comprend le user via `CoachDecision` ;
- il lit des tools read-only / validation-only ;
- il propose des `PlanPatch` ;
- le heartbeat peut proposer un patch proactif en pending confirmation ;
- `ScheduledSession` est maintenant la verite runtime.

La validation actuelle repond a une question runtime :

```text
Ce patch est-il applicable, auditable et legal ?
```

Elle ne repond pas a la question sportive :

```text
Si on applique ce patch, est-ce encore une bonne semaine d entrainement ?
```

Une semaine peut respecter les regles deterministes et rester mauvaise :

- bon nombre de hard sessions, mais mauvais stimulus au mauvais moment ;
- TSS plausible, mais seance cle videe de son sens ;
- recuperation minimale presente, mais mal placee ;
- sport remplace par une charge non equivalente ;
- semaine propre sur le papier, mais mission diluee ;
- fatigue recente ou douleur mal integree ;
- patch local utile, mais compromis global faible.

Donc le deterministe doit produire les faits. Le LLM reviewer juge le compromis.

## Interdits

Ne pas creer un second coach.

Le reviewer sportif ne doit jamais :

- parler directement au user ;
- ecrire en DB ;
- commit une mutation ;
- resoudre une confirmation ;
- modifier la memoire ;
- choisir des tools libres en V1 ;
- debattre avec le coach dans une boucle ouverte ;
- supprimer un hard block deterministe ;
- inventer des allures hors zones ;
- modifier VMA, FTP, CSS ou FCmax.

Le backend ne doit jamais :

- bypasser la review sportive sur un `PlanPatch` significatif ;
- accepter un JSON reviewer invalide silencieusement ;
- laisser un callsite commit un patch sans repasser la gate ;
- transformer un `suggested_adjustment` vague en write DB libre.

## Verites d entree

Toute review runtime raisonne sur :

- `ScheduledSession` comme verite planning live ;
- `Activity` / execution evidence comme verite execution ;
- facts actifs bornes, avec TTL / categories ;
- `PlanPatch` comme langage de changement ;
- `PlanPatchValidation` comme hard gate runtime ;
- `CoachStateBundle` quand disponible.

`WeeklyPlan` et `DayPlan` restent template/onboarding/admin/compat. Ils ne sont
pas une source de verite runtime pour cette couche.

## Flux conversationnel cible

```text
User
  -> Coach LLM
     - comprend le message
     - lit via tools autorises
     - produit CoachDecision / PlanPatch
  -> Runtime orchestrator
     - parse schema
     - charge ScheduledSession / activities / facts / bundle
     - validate_plan_patch()
     - simulate_plan_patch()
     - build_week_coherence_context()
     - appelle WeekCoherenceReviewer
     - aggregate_week_coherence_policy()
  -> PlanMutationService
     - commit uniquement si autorise
     - cree PlanMutationEvent
  -> FinalReplyContext
     - explique le resultat reel
```

Le coach ne repasse pas automatiquement apres la review. Le coach a deja fait
son job : transformer le besoin humain en patch structure.

## Flux heartbeat cible

Le heartbeat est proactif, mais il ne commit pas seul.

```text
Heartbeat LLM
  -> lit plan / activites / contraintes / charge
  -> propose candidate PlanPatch
  -> validate_plan_patch
  -> WeekCoherenceReviewer obligatoire
  -> pending confirmation si valid/confirmable
  -> NO_SEND si rien d utile ou patch fragile
```

Un patch heartbeat est significatif par defaut. Il doit passer la review
sportive avant d etre stocke en pending confirmation.

## Couche deterministic facts

Le deterministe calcule les faits objectifs et les hard gates.

Il calcule notamment :

- `hard_sessions_before` / `hard_sessions_after` ;
- `min_hard_gap_hours_after` ;
- `recovery_sessions_before` / `recovery_sessions_after` ;
- `recovery_after_hard_preserved` ;
- `key_session_ids_touched` ;
- `completed_session_ids_touched` ;
- `weekly_duration_delta_min` ;
- `estimated_tss_delta` ;
- `change_budget_remaining_before` / `after` ;
- `primary_sport_sessions_delta` ;
- `constraints_touched` ;
- flags factuels.

Il ne conclut pas :

```text
Cette semaine est bonne.
```

La conclusion sportive appartient au reviewer.

## WeekCoherenceReviewer

Le `WeekCoherenceReviewer` est un reviewer LLM specialise.

Il recoit :

- le `PlanPatch` original ;
- la validation runtime ;
- la semaine before / after simulee ;
- le diff ;
- les checks deterministes ;
- planning contract ;
- week mission ;
- session policies ;
- recent reality ;
- contraintes actives.

Il retourne uniquement un JSON type.

Il est l autorite sportive sur le patch courant, mais pas l autorite systeme.
Cela veut dire :

```text
Il dit si le patch est sportivement bon, fragile, a confirmer ou bloque.
Il recommande la policy.
Il peut proposer une correction structuree.
Il n applique rien.
```

## Policy runtime

Le runtime agrege :

- `PlanPatchValidation` ;
- `WeekCoherenceReview` ;
- permissions ;
- confirmation deja acceptee ou non ;
- budget / source / pipeline.

Regle d autorite :

```text
Hard block deterministe > reviewer.
Reviewer peut augmenter la prudence.
Reviewer ne peut jamais supprimer un hard block.
```

La policy finale renvoie :

```text
valid | requires_confirmation | blocked
```

## Smoke API reel

La gate A+ doit etre verifiee par tests unitaires ET par smoke HTTP reel.

Commande canonique :

```bash
set -a; source .env; set +a
FITMAS_USE_DEEPSEEK_OPENAI_STRUCTURED=1 \
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-$DEEPSEEK_API_KEY}" \
./scripts/smoke-a-plus-api
```

Le script :

- lance `fitmas.main:app` en HTTP local, pas un `TestClient` ;
- utilise une DB SQLite temporaire isolee ;
- seed directement la verite runtime `ScheduledSession` ;
- appelle le vrai endpoint `/api/v0/messages` avec le vrai provider LLM ;
- inspecte ensuite les artefacts DB.

Invariants verrouilles :

- un patch sportif risque ne peut pas creer de `plan_mutation_event` ;
- une confirmation attendue doit etre stockee en `pending_mutation_confirmations`
  avec `mutation_type="plan_patch"` ;
- une preference memoire ne doit pas creer de write planning ;
- une phrase qui claim un move/remplacement sans event/pending est un fail ;
- un placeholder coach type `[jour]` est signale en warning de qualite.

Ce smoke ne remplace pas la gate backend. Il prouve que le chemin conversationnel
HTTP reel ne la bypass plus.

## Contrats Phase A+ V1

Premier module recommande :

```text
backend/src/fitmas/week_coherence.py
```

Contrats :

```python
@dataclass(frozen=True, slots=True)
class WeekSnapshot:
    week_start: date
    sessions: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class WeekPatchDiff:
    changed_sessions: tuple[dict[str, Any], ...]
    created_sessions: tuple[dict[str, Any], ...]
    removed_or_lightened_sessions: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class DeterministicWeekChecks:
    hard_sessions_before: int
    hard_sessions_after: int
    min_hard_gap_hours_after: int | None
    recovery_sessions_before: int
    recovery_sessions_after: int
    key_session_ids_touched: tuple[int, ...]
    completed_session_ids_touched: tuple[int, ...]
    weekly_duration_delta_min: int
    estimated_tss_delta: float | None
    change_budget_remaining_before: int | None
    change_budget_remaining_after: int | None
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class WeekCoherenceFinding:
    code: str
    severity: Literal["info", "warning", "requires_confirmation", "blocked"]
    detail: str
    target_session_ids: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class WeekCoherenceReview:
    status: Literal["valid", "warning", "requires_confirmation", "blocked"]
    sport_quality: Literal["good", "acceptable", "fragile", "poor"]
    confidence: float
    summary: str
    findings: tuple[WeekCoherenceFinding, ...]
    suggested_adjustments: tuple[dict[str, Any], ...]
    recommended_policy: Literal[
        "commit_original",
        "confirm_original",
        "block_original",
        "retry_with_revised_patch",
        "confirm_revised",
    ]
    revised_patch: PlanPatch | None = None


@dataclass(frozen=True, slots=True)
class WeekCoherenceContext:
    patch: PlanPatch
    validation: PlanPatchValidation
    before_week: WeekSnapshot
    after_week: WeekSnapshot
    diff: WeekPatchDiff
    deterministic_checks: DeterministicWeekChecks
    planning_contract: dict[str, Any] | None
    week_mission: dict[str, Any] | None
    session_policies: tuple[dict[str, Any], ...]
    recent_reality: dict[str, Any] | None
    active_constraints: tuple[dict[str, Any], ...]
```

V1 garde `revised_patch` comme champ optionnel pour debug / futur. Le runtime
ne l applique pas automatiquement au debut.

## Fonctions Phase A+ V1

```python
def simulate_plan_patch(
    scheduled_sessions: Sequence[Any],
    patch: PlanPatch,
    *,
    timezone_name: str | None,
) -> tuple[WeekSnapshot, WeekSnapshot, WeekPatchDiff]:
    """Pure simulation. No DB write."""


def build_week_coherence_context(
    *,
    patch: PlanPatch,
    validation: PlanPatchValidation,
    scheduled_sessions: Sequence[Any],
    coach_state_bundle: CoachStateBundle | None,
    activities: Sequence[Any],
    active_facts: Sequence[Any],
    timezone_name: str | None,
) -> WeekCoherenceContext:
    ...


def evaluate_week_invariants(context: WeekCoherenceContext) -> DeterministicWeekChecks:
    ...


def review_week_coherence_with_llm(
    context: WeekCoherenceContext,
    *,
    request_json_fn: Callable[..., Any],
) -> WeekCoherenceReview:
    ...


def aggregate_week_coherence_policy(
    *,
    patch_validation: PlanPatchValidation,
    week_review: WeekCoherenceReview | None,
    deterministic_checks: DeterministicWeekChecks,
    allow_requires_confirmation: bool,
) -> Literal["valid", "requires_confirmation", "blocked"]:
    ...
```

## Finding codes initiaux

Supporter au minimum :

```text
key_session_lost
key_session_moved
key_session_sport_changed
key_session_shortened_below_minimum
recovery_session_lost
recovery_after_hard_lost
hard_sessions_too_close
too_many_hard_sessions
change_budget_exhausted
mission_diluted
stimulus_mismatch
weekly_load_delta_high
health_constraint_requires_review
multi_session_patch
patch_sportively_good
mission_preserved
recovery_preserved
```

Ces codes doivent rester machine-friendly. Les details peuvent etre humains,
mais jamais utilises comme source de write.

## Quand appeler le reviewer

Appel quasi systematique sur tout `PlanPatch` sportivement significatif.

Appeler pour :

- `move_session` ;
- `swap_sessions` ;
- `replace_session` ;
- `update_session` si sport, type, duree, intensite ou description change ;
- `lighten_day` ;
- `create_session` ;
- patch multi-operations ;
- patch heartbeat proactif ;
- changement sport / duree / intensite ;
- seance key / support / recovery touchee ;
- fatigue, douleur, maladie ou contrainte active dans le contexte ;
- validation runtime `warning` ou `requires_confirmation`.

Pas obligatoire pour :

- `complete_session` ;
- `skip_session` ;
- reponse conversationnelle pure ;
- lookup plan ;
- memoire sans mutation planning ;
- clarification ;
- accept/reject pending deja reviewe, si patch inchange et review encore
  valide.

Pour le dogfood, privilegier trop reviewer plutot que pas assez. Le cout est
controle par un contexte compact, pas par une gate rare.

## Qui dit quoi faire au final

Le reviewer n est pas juste un critique.

Il ne dit pas :

```text
Coach, voici mon feedback, repropose quelque chose.
```

Il dit :

```text
Sportivement, ce patch est valid / fragile / a confirmer / bloque.
La meilleure action recommandee est commit / confirmer / bloquer / reparer.
```

Le runtime decide ensuite :

```text
Au vu de validate_plan_patch + review + permissions, on commit / pending / block.
```

Le coach final explique :

```text
Voici ce qui se passe, en langage humain, depuis le resultat reel.
```

## Policy V1

V1 doit rester robuste et sans boucle agentique.

Mapping :

```text
commit_original -> commit si validation runtime valid
confirm_original -> pending confirmation
block_original -> no commit
retry_with_revised_patch -> traiter comme block + proposer direction
confirm_revised -> traiter comme block + proposer direction
```

Donc :

```text
Coach PlanPatch
  -> validate_plan_patch
  -> WeekCoherenceReviewer
  -> valid: commit
  -> requires_confirmation: pending
  -> blocked: no commit, final reply explique + propose direction
```

Le reviewer peut fournir `suggested_adjustments`, mais V1 ne transforme pas ces
suggestions en writes automatiques.

Exemple :

```text
Le move est possible, mais il densifie trop la fin de semaine avant la sortie
longue. La direction propre serait de garder le move et d alleger le support
derriere. Tu confirmes ?
```

## Policy V2

V2 peut permettre un seul repair structure.

Flux :

```text
Coach PlanPatch
  -> validate_plan_patch(original)
  -> review_week_coherence(original)
  -> reviewer returns revised_patch
  -> validate_plan_patch(revised_patch)
  -> review_week_coherence(revised_patch)
  -> commit / pending / block
```

Contraintes :

- max 1 repair pass ;
- `revised_patch` complet ;
- `revised_patch` reste dans l intention utilisateur ;
- `revised_patch` repasse `validate_plan_patch` ;
- `revised_patch` repasse `WeekCoherenceReviewer` ;
- si encore warning/block : pending ou block ;
- pas de boucle `CoachAgent <-> SportReviewer`.

Le repair V2 est orchestre par le runtime, pas par un debat entre agents.

## Integration PlanMutationService

Point d insertion : `apply_patch_for_user()`, apres `validate_plan_patch()` et
avant tout commit.

Pseudo :

```python
validation = validate_plan_patch(...)

if validation.status == "blocked":
    return PlanPatchServiceResult(validation=validation)

week_gate = review_plan_patch_week_coherence(
    db=db,
    user=user,
    patch=patch,
    validation=validation,
    scheduled_sessions=scheduled_sessions,
    activities=repo.get_recent_activities(...),
    active_facts=repo.get_active_memory_items(...),
)

if week_gate.status == "blocked":
    return PlanPatchServiceResult(
        validation=validation,
        week_gate=week_gate,
    )

if week_gate.status == "requires_confirmation" and not allow_requires_confirmation:
    return PlanPatchServiceResult(
        validation=validation,
        week_gate=week_gate,
    )

# commit
```

`PlanPatchServiceResult` devra porter le `week_gate` / `week_review` pour que les
call sites construisent des pending et replies coherentes.

Ne pas laisser les callsites bypasser cette gate. Le tool
`validate_week_coherence` aide le LLM, mais le backend re-run toujours la gate
avant commit.

## Pending confirmations

Quand une pending confirmation contient un `PlanPatch` deja reviewe, stocker :

- patch hash ;
- review status ;
- recommended policy ;
- review summary ;
- review findings ;
- review version.

Accept pending :

```text
Si patch hash inchange + review version actuelle:
  revalider runtime, puis commit si autorise.
Sinon:
  re-run WeekCoherenceReviewer avant commit.
```

Une confirmation acceptee ne doit pas permettre de commit un patch dont le
contexte sportif est devenu obsolete.

## Runtime tool validate_week_coherence

Ajouter un tool validation-only :

```text
validate_week_coherence
```

Role :

```text
Permet au coach LLM de tester la coherence sportive d un PlanPatch avant sa
decision finale.
```

Regles :

- allowed pipelines : `conversation`, `planning`, `heartbeat` ;
- input : `PlanPatch` complet ;
- output : `WeekCoherenceReview` + deterministic checks ;
- jamais de write ;
- budget borne comme les autres tools ;
- le backend re-run la review avant commit.

Ne pas remplacer les tools atomiques existants. Le coach doit encore pouvoir lire
plan, charge, contraintes, activites, puis appeler `validate_week_coherence` sur
son patch.

## Prompt reviewer

Le prompt reviewer doit etre strict :

- tu es un reviewer sportif subordonne ;
- tu ne parles jamais au user ;
- tu ne commit rien ;
- tu juges le patch courant, pas une strategie libre ;
- tu dois respecter les hard blocks ;
- tu peux augmenter la prudence ;
- tu ne peux pas inventer de faits absents du contexte ;
- tu ne peux pas inventer d allures hors zones ;
- tu dois retourner uniquement le JSON attendu.

Question centrale :

```text
Si on applique ce patch, la semaine garde-t-elle une logique sportive utile
pour l objectif, la fatigue recente, les contraintes et la mission de semaine ?
```

Le prompt doit insister sur les compromis :

- mission preservee ou diluee ;
- stimulus conserve ou remplace proprement ;
- key sessions protegees ;
- recuperation placee au bon endroit ;
- densite fin de semaine ;
- charge recente ;
- fatigue / douleur ;
- change budget ;
- multi-sport interference.

## Semaine generee

La review sportive ne concerne pas seulement les adaptations.

Flux cible pour generation initiale / hebdo :

```text
build_fitness_snapshot()
  -> build_planning_decision()
  -> build_week_plan()
  -> validate_week_plan()
  -> WeekCoherenceReviewer
  -> commit ScheduledSessions
```

Si la review bloque :

- ne pas commit une semaine mauvaise ;
- tenter une regeneration bornee ou fallback conservateur ;
- logger la review ;
- ne jamais inventer une promesse utilisateur depuis le reviewer.

## Long terme : TrainingRoadmap

Ne pas generer 8-12 semaines figees.

Contrat horizon :

| Horizon | Detail | Statut |
| --- | ---: | --- |
| Aujourd hui | seance concrete | committed |
| Semaine courante | seances concretes | committed adaptable |
| Semaine prochaine | focus + charge cible + seances probables | tentative |
| 4 semaines | bloc / mesocycle | projected |
| 8-12 semaines | trajectoire objectif | strategic |

Objet futur :

```python
@dataclass(frozen=True, slots=True)
class TrainingRoadmap:
    user_id: int
    horizon_weeks: int
    goal: str
    primary_sport: str
    secondary_sports: tuple[str, ...]
    start_date: date
    target_event_date: date | None
    current_phase: str
    block_focus: str
    weekly_target_tss_band: tuple[float, float]
    progression_policy: dict[str, Any]
    risk_policy: dict[str, Any]
    mesocycles: tuple[dict[str, Any], ...]
```

Pas prioritaire pour Slice A+0/A+1.

## SessionPrescription doctrine

Phase B0, apres Phase A+, introduira une prescription structuree.

Doctrine :

```text
On ne progresse pas les allures.
On progresse le stimulus.
Les allures suivent quand les seuils/zones sont recalibres.
```

Correct :

```text
2 x 8 min Z3
-> 2 x 10 min Z3
-> 3 x 8 min Z3
-> recalibrage VMA si evidence
-> zones plus rapides
-> meme seance, allures naturellement mises a jour
```

Interdit :

```text
Meme seance Z3, mais +10 sec/km plus vite sans update de zone.
```

Objet futur :

```python
@dataclass(frozen=True, slots=True)
class SessionPrescription:
    sport_type: str
    session_type: str
    role: Literal["key", "support", "recovery", "optional"]
    stimulus: str
    progression_axis: str
    target_zone: str
    blocks: tuple[PrescriptionBlock, ...]
    success_criteria: tuple[str, ...]
    downgrade_options: tuple[dict[str, Any], ...]
    progression_notes: str


@dataclass(frozen=True, slots=True)
class PrescriptionBlock:
    phase: str
    block_type: str
    zone: str
    reps: int | None
    duration_min: int | None
    rep_duration: str | None
    rep_distance: str | None
    recovery: str | None
    target: str | None
```

Premier slice B0 :

- pas besoin de migration DB ;
- generer `SessionPrescription` ;
- rendre `session_description` comme aujourd hui ;
- futur : stocker `prescription_json` sur `ScheduledSession`.

`SessionPrescriptionEngine` doit utiliser les `SessionBlueprint` existants dans
`session_templates.py`.

## SessionQualityReviewer

Question :

```text
Cette seance est-elle bien prescrite pour son role dans la semaine ?
```

Appeler pour :

- seance cle ;
- seance hard ;
- seance creee ;
- seance remplacee ;
- seance apres fatigue / douleur ;
- seance avec progression de stimulus.

Ne pas appeler pour tous les footings easy basiques au debut.

Contrat futur :

```python
@dataclass(frozen=True, slots=True)
class SessionQualityReview:
    status: Literal["valid", "requires_revision", "requires_confirmation", "blocked"]
    quality: Literal["good", "acceptable", "fragile", "poor"]
    confidence: float
    findings: tuple[SessionQualityFinding, ...]
    suggested_revision: dict[str, Any] | None
```

Regle dure : le reviewer ne peut pas inventer de seuils ou d allures hors zones.

## Progression et calibration

Les signaux de progression ne modifient pas les zones directement.

Running :

- meme allure avec FC plus basse ;
- meme FC avec allure plus rapide ;
- tempo complete en controle ;
- RPE bas sur seance dure ;
- derive cardio faible sur endurance ;
- sortie longue terminee propre.

Cycling :

- puissance plus haute a FC/RPE equivalent ;
- intervals completes au-dessus cible ;
- effort FTP-like ameliore.

Swimming :

- CSS apparent meilleur ;
- series 100m plus rapides avec recup stable ;
- moins de degradation en fin de serie.

Regle :

```text
1 signal = observation
2-3 signaux coherents = calibration candidate
debut = confirmation utilisateur
```

Contrat futur :

```python
@dataclass(frozen=True, slots=True)
class CalibrationProposal:
    sport_type: str
    metric: Literal["vma", "ftp", "css", "fc_max"]
    current_value: float
    proposed_value: float
    confidence: float
    evidence: tuple[str, ...]
    risk: str
    requires_confirmation: bool
```

Les allures viennent uniquement de :

```text
Thresholds -> AthleteZones -> SessionPrescription
```

V1 peut stocker les seuils dans `UserFact(category="threshold")`.

Futur : table dediee `athlete_threshold_estimates`.

## ProgressionEngine futur

```python
@dataclass(frozen=True, slots=True)
class ProgressionDecision:
    mode: Literal[
        "hold",
        "progress_volume",
        "progress_density",
        "progress_intensity",
        "recalibrate_threshold",
        "deload",
        "protect",
    ]
    sport_type: str
    stimulus: str
    max_weekly_load_delta_pct: float
    session_adjustments: tuple[dict[str, Any], ...]
    threshold_proposal: CalibrationProposal | None
    rationale: tuple[str, ...]
```

Regle dure :

```text
Ne jamais augmenter agressivement zones + volume + intensite en meme temps.
```

Si zones recalibrees :

```text
Garder la structure de seance stable la semaine suivante.
```

## Ordre d implementation

La sequence a ete recadree le 5 mai 2026 : ne pas ouvrir 3B-C action-tools
avant la gate sportive core. Sinon on augmente l'autonomie du coach sans
reviewer sportif. Le bon ordre est :

```text
Dogfood 3B-B court
  -> A+ core gate
  -> 3B-C action-tools derriere gate
  -> A+ hardening
  -> B0/B1/B2 scale sportif
```

Trois blocs :

```text
MVP = A+1 -> A+3
Hardening = 3B-C -> A+5
Scale sportif = B0 -> B2
```

Critere de passage de MVP vers hardening :

```text
Aucun PlanPatch significatif ne peut commit sans:
validate_plan_patch -> WeekCoherenceReviewer -> backend policy -> PlanMutationService.
```

### Slice A+0 - Documentation + contrats

- creer ce document ;
- mettre a jour `BUILD-ORDER.md` ;
- mettre a jour `RUNTIME-TOOLS.md`.
- statut : fait localement le 5 mai 2026.

### Slice A+1 - Week coherence context deterministe

- `simulate_plan_patch` ;
- `build_week_coherence_context` ;
- `evaluate_week_invariants`.
- statut : implemente localement le 5 mai 2026 dans `backend/src/fitmas/week_coherence.py`.

Tests :

- simulation pure ne write pas DB ;
- `move_session` produit before/after correct ;
- `replace_session` detecte key touchee ;
- recovery lost detecte ;
- hard gap calcule ;
- change budget calcule.

### Slice A+2 - LLM WeekCoherenceReviewer

- prompt strict ;
- JSON typed ;
- parse / validate ;
- retry / fallback.
- statut : implemente localement le 5 mai 2026. Le runtime appelle le reviewer via `llm_gateway.request_json` quand disponible ; provider indisponible => fallback type conservateur.

Tests :

- JSON valid accepte ;
- JSON invalide retry/fallback ;
- reviewer ne peut pas override hard block ;
- reviewer peut monter `valid` vers `requires_confirmation` ;
- reviewer blocked empeche commit.

### Slice A+3 - Gate runtime

- brancher dans `apply_patch_for_user` ;
- etendre `PlanPatchServiceResult` ;
- construire pending/replies depuis week gate.
- statut : implemente localement le 5 mai 2026. `PlanPatchServiceResult` porte `week_review` + `week_policy_status`.

Tests :

- patch runtime valid mais reviewer `requires_confirmation` => pending/no commit ;
- reviewer `blocked` => no commit ;
- `allow_requires_confirmation` applique seulement apres confirmation ;
- aucun event commit quand blocked.

### Chantier 3B-C - Action-tools natifs bornes

Position dans la sequence : apres A+3, pas avant.

Objectif :

- ajouter des action-tools natifs bornes ;
- garder les writes sous orchestrateur ;
- faire passer toute action planning par la gate A+ core.

Regle :

```text
Action-tool -> PlanPatch/artefact borne
  -> validate_plan_patch
  -> WeekCoherenceReviewer
  -> backend policy
  -> PlanMutationService
```

Tests :

- un action-tool ne commit jamais directement ;
- action-tool retourne un artefact borne ;
- gate sportive bloque/pending comme sur un patch conversationnel ;
- aucun bypass de `apply_patch_for_user`.

### Slice A+4 - Tool validate_week_coherence

✅ Implemente localement 5 mai 2026.

- ajoute au registry ;
- allowed `conversation`, `planning`, `heartbeat` ;
- retourne validation runtime, deterministic checks, review sportive et
  `policy_status` ;
- aucun write (`commit_performed=false`, `writer=none`) ;
- heartbeat peut capturer un patch reviewe comme pending confirmation ;
- backend re-run toujours avant commit.

Tests :

- ✅ tool returns review payload ;
- ✅ tool never writes ;
- ✅ tool budget respecte ;
- ✅ backend re-run gate meme si tool deja appele.

### Slice A+5 - Review semaine generee

✅ Implemente localement 5 mai 2026.

- branche apres `build_week_plan` / `formulate_week_plan` ;
- avant `replace_plan` et donc avant creation/sync des `ScheduledSession` ;
- transforme la semaine candidate en `PlanPatch` synthetique `create_session`
  read-only ;
- appelle `WeekCoherenceReviewer` sur cette semaine candidate ;
- si policy review non `valid` : genere une version allegee prudente et la
  reviewe ;
- si cette version allegee est encore `blocked` : stoppe avec erreur 409, aucun
  `replace_plan`.
- une version allegee `warning` / `requires_confirmation` reste
  persistable en onboarding : il vaut mieux livrer une semaine allegee relue que
  bloquer un nouveau user sur un compromis non critique.
- cette version ne doit jamais exposer de jargon interne user-facing
  (`fallback`, `review`, `patch`, `commit`, etc.) dans `summary` /
  `session_note`.
- en mode `injury_protection`, le planner garde un minimum efficace si des
  sports support faciles sont disponibles : recuperation primaire + supports
  low-impact disponibles, puis mobilite/renfo seulement si budgetee ou seul
  support explicite, toujours easy/load <= 1.

Tests :

- ✅ generated week reviewed ;
- ✅ blocked / requires_confirmation review trigger fallback/regeneration ;
- ✅ valid review commit sessions.

### Slice B0 - SessionPrescriptionEngine

- utiliser `SessionBlueprint` ;
- produire prescription structuree + rendered description.

### Slice B1 - SessionQualityReviewer

- appeler sur seances cles / hard / creees / remplacees / fatigue.

### Slice B2 - PerformanceSignalService + CalibrationProposal

- diagnostic d abord ;
- confirmation user par defaut.

## Gates d acceptation globales

Architecture :

- aucun second coach agent ;
- reviewer non-writer ;
- reviewer non user-facing ;
- backend policy final ;
- `PlanMutationService` seul writer.

Sport quality :

- tout `PlanPatch` significatif passe par `WeekCoherenceReviewer` ;
- `validate_plan_patch` reste hard gate runtime ;
- reviewer peut augmenter friction mais pas supprimer hard block ;
- semaine initiale/generee relue avant commit.

Session detail :

- detail seance vient d une prescription structuree ;
- allures derivees des zones ;
- LLM ne peut pas inventer des allures hors zones ;
- progression = stimulus/dose d abord ;
- allures changent seulement via recalibrage seuils.

Progression :

- pas de recalibrage seuil sur un seul signal ;
- `CalibrationProposal` type ;
- confirmation utilisateur par defaut ;
- pas de double progression agressive.

## Phrase resume

```text
Coach libre.
Reviewer sportif quasi systematique sur les vrais patchs.
Runtime souverain.
Progression par stimulus et zones recalibrees.
```
