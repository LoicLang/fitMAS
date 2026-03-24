# Planning V2 — Prochaine étape : Plan adaptatif intelligent

## Contexte

Le moteur d'entraînement V2 est en place (mars 2026) :
- **Zones athlète** : VMA/FTP/CSS → allures, watts, sec/100m personnalisés
- **Blueprints paramétriques** : séances structurées avec RepScaling par niveau + semaine
- **Distribution 80/20** : budget d'intensité polarisé (Seiler) par mode de planning
- **Périodisation 3+1** : mésocycle 3 build + 1 recovery avec multiplieurs TSS/volume/reps
- **Knowledge docs** : 7 fichiers sport injectés dans les prompts LLM

**Le moteur est solide mais strict.** Il produit un plan de qualité, mais il ne sait pas encore s'adapter en cours de route. Ce qui manque : le LLM qui analyse les données en continu et ajuste intelligemment le plan.

### Constat actuel des mutations

Le coach LLM peut aujourd'hui :
- `move_session` — déplacer une séance
- `swap_sessions` — échanger deux séances
- `lighten_day` — **supprime** la séance (sport_type="rest", durée=null, description vide)
- `update_session` — modifier titre/objectif uniquement (pas sport_type, pas description, pas intensité)

**Ce qu'il ne peut PAS faire** :
- Remplacer un fractionné par du stretching/mobilité/gainage
- Baisser l'intensité d'une séance sans la supprimer (ex: intervals Z5 → footing Z1)
- Changer le sport_type (ex: running → strength)
- Adapter la description (ex: "8x400m" → "5x400m + 10min gainage")
- Proposer un downgrade intelligent au lieu d'annuler

---

## Axe 1 — Progression automatique du mésocycle

**Effort : ~2h | Impact : fondation pour tout le reste**

### Problème
`compute_mesocycle_state()` existe mais `total_weeks` n'est ni persisté ni incrémenté. Le plan se régénère chaque dimanche sans savoir où on en est dans le cycle.

### Solution
- Persister `total_weeks` sur `WeeklyPlan` ou `User` (schema.py)
- Incrémenter à chaque régénération hebdomadaire (heartbeat weekly review)
- Passer `cycle_week` à `build_week_plan()` → les blueprints scalent automatiquement
- Semaine 4 → `adjust_planning_mode()` force le deload

### Résultat concret
- Sem 1 : 8x400m @ Z5
- Sem 2 : 8x400m @ Z5 (+5% TSS, sessions clé +5-10min)
- Sem 3 : 10x400m @ Z5 (+8% TSS, +2 reps)
- Sem 4 : 4x400m @ Z5 (recovery, -35% TSS, -50% reps, pas de Z4+)
- Sem 5 : nouveau cycle, baseline recalculée

---

## Axe 2 — Mutations enrichies (le LLM peut vraiment adapter)

**Effort : ~4h | Impact : le coach passe de "annuler ou garder" à "adapter intelligemment"**

### Problème
`lighten_day` est binaire : soit la séance reste telle quelle, soit elle disparaît en "Journée flexible". Le coach ne peut pas proposer un middle ground.

### Solution — `replace_session` mutation

Nouveau type de mutation qui permet au LLM de transformer une séance en une autre :

```python
class MutationDecision(BaseModel):
    mutation_type: str  # + "replace_session"
    # ... champs existants ...
    # Nouveaux champs pour replace_session :
    new_sport_type: str | None = None
    new_session_type: str | None = None
    new_duration_min: int | None = None
    new_intensity: str | None = None
    new_description: str | None = None
```

#### Scénarios concrets

| L'utilisateur dit | Aujourd'hui | Après |
|---|---|---|
| "J'ai mal aux jambes" | lighten → rest (séance supprimée) | replace → 25min mobilité + gainage |
| "Je suis crevé" | lighten → rest | replace → footing Z1 30min (récup active) |
| "Trop dur le fractionné" | update titre seulement | replace → fartlek Z2 ou tempo léger Z3 |
| "Pas le temps pour 55min" | rien (update ne change pas la durée) | replace → même sport, 30min, intensité réduite |
| "Je veux grimper plutôt" | impossible | replace → escalade technique |

#### Règles du remplacement

Le LLM choisit le remplacement, mais le moteur valide :
- Le replacement doit réduire ou maintenir le load_score (jamais augmenter)
- Si l'intensité baisse (hard → easy), la durée peut rester identique
- Si le sport change, recalculer le load_score via le template
- Toujours persister une `ChangeNote` expliquant l'adaptation
- Le blueprint paramétrique génère la description du replacement si zones disponibles

#### Templates de remplacement prédéfinis

Pour guider le LLM et éviter les remplacements absurdes :

| Séance originale | Remplacements valides |
|---|---|
| Running intervals (hard) | Running easy, Running fartlek, Strength core, Mobility |
| Running tempo (hard) | Running easy, Running recovery, Strength general |
| Running long (moderate) | Running easy (plus court), Cycling endurance |
| Cycling sweet_spot (hard) | Cycling endurance, Cycling recovery, Strength core |
| Swimming CSS (hard) | Swimming technique, Swimming recovery |
| Any sport (hard/moderate) | Mobility, Core, Rest |

### Fichiers à modifier
- `backend/src/fitmas/llm.py` — ajouter `replace_session` au prompt decide()
- `backend/src/fitmas/mutations.py` — handler pour `replace_session`
- `backend/src/fitmas/plan_actions.py` — `replace_session()` qui applique les changements
- `backend/src/fitmas/session_templates.py` — `get_replacement_options()` pour guider le LLM

---

## Axe 3 — Analyse fine LLM (triggers intelligents)

**Effort : ~5h | Impact : le plan évolue avec l'athlète sans qu'il demande**

### Problème
Aujourd'hui le LLM ne réagit qu'aux messages utilisateur. Il ne regarde jamais les données de manière proactive pour adapter le plan.

### Quand déclencher une analyse LLM ?

Le coût d'un appel LLM est non-nul (~0.5-2 cents, ~1-3s). On ne veut pas analyser chaque micro-événement. La logique : des **triggers déterministes** détectent un signal, et seulement alors on envoie le contexte au LLM pour une décision fine.

#### Triggers et leur pipeline

| Trigger | Détection (déterministe, pas de LLM) | Action LLM |
|---------|--------------------------------------|------------|
| **Activité Strava importée** | Match activité ↔ séance planifiée, comparer durée/HR/allure vs zone cible | Décider : valider, adapter les séances suivantes, ou ne rien faire |
| **Séance manquée (J+1 sans activité)** | Signal `missed_key` existant (signals.py) | Décider : réduire la semaine, proposer un replacement, ou ignorer |
| **2+ séances manquées consécutives** | Compteur missed dans la semaine | Forcer deload anticipé + message empathique |
| **TSB < -15 (fatigue accumulée)** | `compute_ctl_atl_tsb()` existant (training_load.py) | Proposer allègement proactif des 2-3 prochains jours |
| **TSB > +10 (trop frais = sous-entraîné)** | Même calcul | Proposer +1 séance qualité ou augmenter volume |
| **Grosse activité hors plan** | Activité Strava TSS > 80 pas matchée à une séance | Réduire la charge J+1, J+2 |
| **Fait santé récent (blessure, douleur)** | UserFact category="health" créé/modifié | Analyse complète : quelles séances adapter ou remplacer |
| **Début de semaine recovery** | `week_in_cycle == 4` à la régénération | Le LLM formule le plan en mode "rien à prouver cette semaine" |
| **Météo extrême** (V3) | API météo | Proposer HT au lieu de route, salle au lieu d'extérieur |

#### Architecture du pipeline

```
Événement (Strava import, cron, message)
    ↓
Détection déterministe (Python pur, pas de LLM, ~1ms)
    → Signal détecté ? Non → stop
    → Oui ↓
Assemblage du contexte (séances à venir, zones, facts, historique récent)
    ↓
Appel LLM ciblé (prompt spécialisé, pas le prompt decide() généraliste)
    → Décision structurée (JSON)
    ↓
Application (mutation replace/lighten/update + ChangeNote)
    ↓
Notification (heartbeat ou message inline)
```

#### Prompts LLM spécialisés (pas le decide() généraliste)

Chaque trigger a son propre prompt, plus court et plus ciblé que `decide()` :

**Prompt post-activité** (~500 tokens context) :
```
Activité réelle: {sport} {duration}min, HR moy {hr}, allure {pace}
Séance planifiée: {title}, zone cible {zone}, durée prévue {planned_duration}min
Zones athlète: {zones_summary}
Séances à venir (48h): {next_sessions}
TSB actuel: {tsb}

L'activité était-elle conforme au plan ?
Si non, quelles séances des 48h suivantes faut-il adapter et comment ?
Réponds en JSON: {adaptations: [{session_id, action, rationale}]}
```

**Prompt fatigue accumulée** (~400 tokens context) :
```
TSB: {tsb} (fatigué)
Dernière semaine: {sessions_done} séances faites sur {sessions_planned}
Charge derniers 7j: {atl} vs moyenne 28j: {ctl}
Séances à venir cette semaine: {remaining_sessions}
Facts santé: {health_facts}

Faut-il alléger la fin de semaine ? Si oui, quelles séances adapter ?
Réponds en JSON: {adaptations: [{session_id, action, rationale}]}
```

**Prompt fait santé** (~300 tokens context) :
```
Nouveau fait santé: {fact_value} (category: {category}, confidence: {confidence})
Séances à venir (7j): {upcoming_sessions}
Zones athlète: {zones_summary}

Quelles séances doivent être adaptées pour ce fait de santé ?
Options: keep (garder), replace (remplacer par sport/type/durée), lighten (supprimer)
Réponds en JSON: {adaptations: [{session_id, action, replacement_sport?, replacement_type?, rationale}]}
```

### Modèle de données

```python
@dataclass
class SessionComparison:
    session_id: int
    planned_duration_min: int
    actual_duration_min: int
    planned_zone: str           # "Z5"
    actual_avg_hr_zone: str     # "Z4" (estimé depuis HR)
    actual_avg_pace_zone: str   # "Z5" (estimé depuis allure)
    completion: str             # "completed" | "shortened" | "missed" | "off_plan"
    effort_delta: str           # "under" | "on_target" | "over"

@dataclass
class AdaptationRequest:
    trigger: str                # "post_activity" | "missed_session" | "fatigue" | "health_fact"
    context: dict               # données assemblées pour le prompt
    urgency: str                # "immediate" | "next_session" | "end_of_week"

@dataclass
class SessionAdaptation:
    target_session_id: int
    action: str                 # "keep" | "replace" | "lighten" | "increase"
    new_sport_type: str | None
    new_session_type: str | None
    new_duration_min: int | None
    rationale: str
    change_note: str            # pour l'utilisateur
```

### Fichiers à créer/modifier
- **CRÉER** `backend/src/fitmas/adaptation.py` — pipeline trigger → contexte → LLM → mutation
- **CRÉER** `backend/src/fitmas/adaptation_prompts.py` — prompts spécialisés par trigger
- `backend/src/fitmas/strava.py` — appeler adaptation après import
- `backend/src/fitmas/signals.py` — enrichir les détecteurs existants
- `backend/src/fitmas/heartbeat.py` — déclencher adaptation aux crons (fatigue, missed)
- `backend/src/fitmas/training_load.py` — exposer TSB thresholds

---

## Axe 4 — Affinage des seuils depuis Strava

**Effort : ~3h | Impact : zones de plus en plus précises avec le temps**

### Problème
Les zones sont basées sur des estimations par niveau (VMA 14 pour intermédiaire). Un coureur "intermédiaire" peut avoir une VMA de 12 ou 16.

### Solution
Après import d'activité Strava avec données suffisantes :

**Running → VMA estimée :**
- Activité avec HR + allure + durée > 20min
- Identifier le meilleur effort ~6min (proxy VO2max)
- VMA estimée = allure du meilleur effort 6min (en km/h)
- Confidence : 0.6 (une seule activité) → 0.8 (3+ activités convergentes)

**Cycling → FTP estimé :**
- Activité avec puissance + durée > 30min
- Meilleur effort 20min × 0.95 = FTP
- Besoin de données puissance (pas toujours dispo)

**Swimming → CSS estimé :**
- Plus complexe, nécessite des séries identifiables
- V3 — pour l'instant estimation par niveau suffit

### Persistence
```python
repo.upsert_facts(db, user_id, [{
    "category": "threshold",
    "key": "vma",
    "value": "15.2",
    "confidence": 0.7,
    "source": "strava_estimated",
    "ttl": "long",
}])
```

Les zones se recalculent automatiquement au prochain `build_athlete_zones()`.

---

## Axe 5 — Gestion multisport intelligente

**Effort : ~4h | Impact : plan cohérent pour les athlètes multi-activités**

### Problème
Le moteur traite chaque sport indépendamment. Il n'y a pas de logique croisée : une sortie longue vélo le samedi ne réduit pas la charge running du dimanche.

### Solution

#### 5.1 Budget de charge partagé
- Un TSS total hebdomadaire réparti entre les sports, pas un budget par sport
- La fatigue est systémique : 90min vélo Z2 = fatigue réelle même si le running n'a pas bougé
- Le `planning_decision.weekly_target_tss` doit être cross-sport

#### 5.2 Matrice d'interférence entre sports

| Combinaison | Même jour | J+1 | Règle |
|---|---|---|---|
| Running hard + Running (any) | NON | Fragile | Jamais 2 runs qualité consécutifs |
| Running hard + Cycling easy | OK si récup | OK | Le vélo moulinette aide la récup |
| Running hard + Strength hard | NON | NON | Double fatigue musculaire |
| Running + Swimming | OK | OK | Faible interférence (non-porteur) |
| Cycling hard + Running hard | NON | Fragile | Même groupes musculaires |
| Climbing hard + Strength | NON | NON | Fatigue doigts + tirage |
| Climbing + Running | OK | OK | Groupes musculaires différents |
| Any hard + Any hard | NON | Éviter | Max 1 séance hard/jour |

#### 5.3 Rôle par sport dans le plan

| Rôle | Créneaux | Exemple |
|---|---|---|
| Sport primaire | Qualité + long + easy | Running : fractionné mardi, tempo jeudi, longue dimanche |
| Sport secondaire | Endurance/technique seulement | Cycling : endurance mercredi |
| Sport tertiaire | Récup ou plaisir | Swimming : technique vendredi |
| Renfo/mobilité | Support, jamais avant qualité | Gainage lundi, mobilité jour off |

Le planner doit connaître le rôle de chaque sport pour un athlète donné et distribuer les créneaux en conséquence.

#### 5.4 Adaptation croisée post-activité
- Si grosse sortie vélo hors plan → réduire le running du lendemain
- Si escalade intense → pas de renfo haut du corps J+1
- Si 2 sports le même jour → adapter la durée/intensité du 2e

### Fichiers à modifier
- `backend/src/fitmas/planner.py` — matrice d'interférence dans `_pick_day_for_session()` et `_schedule_sessions()`
- `backend/src/fitmas/planning_decision.py` — budget TSS cross-sport
- `backend/src/fitmas/adaptation.py` — adaptation croisée dans le pipeline post-activité

---

## Ordre d'exécution

| Axe | Effort | Impact | Prérequis |
|-----|--------|--------|-----------|
| **1** Mésocycle auto | ~2h | Progression structurée | Aucun |
| **2** Mutations enrichies (replace_session) | ~4h | Coach peut vraiment adapter | Aucun |
| **3** Analyse fine LLM (triggers) | ~5h | Plan réactif aux données | Axe 2 |
| **4** Seuils Strava | ~3h | Zones affinées | Axe 3 (optionnel) |
| **5** Multisport intelligent | ~4h | Cohérence cross-sport | Axe 3 |

**Chemin critique** : 1 + 2 (parallèle) → 3 → 4 + 5 (parallèle)

Total : ~18h, déployable progressivement.

---

## Résultat final attendu

### Avant (plan statique V2)
```
Utilisateur a mal au genou depuis hier.
→ lighten_day → "Journée flexible" (séance supprimée)
→ Pas d'adaptation des jours suivants
```

### Après (plan adaptatif V2.5)
```
Utilisateur a mal au genou depuis hier.
→ Trigger: health_fact détecté
→ LLM analyse: douleur articulaire, séance running demain, escalade après-demain
→ Adaptations:
  - Demain: running intervals Z5 → replace: 25min mobilité + gainage bas du corps
  - Après-demain: escalade technique → keep (pas d'impact genou)
  - J+3: running tempo → replace: natation endurance Z2 (non-porteur)
→ ChangeNotes ajoutées, message au coach:
  "Genou signalé — j'ai basculé les runs en mobilité et natation pour les 3 prochains jours. On remet du running dès que ça va mieux."
```

---

## Ce qui vient APRÈS (V3)

- **Macrocycle avec objectif daté** : "Je fais un marathon le 15 juin" → Base→Build→Specialty→Taper automatique
- **Progression levels par energy system** (style TrainerRoad) : endurance level 3.2, threshold level 2.8
- **Prédiction de performance** : VMA + historique → temps estimé 10k/semi/marathon
- **HRV morning readiness** : si capteur dispo, ajuster la séance du jour en temps réel
- **Météo** : proposer HT au lieu de route, salle au lieu d'extérieur
