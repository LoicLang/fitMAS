---
summary: voix FitMAS, heartbeat, messaging doctrine et exemples de ton
read_when:
  - écrire un message FitMAS
  - implémenter le heartbeat
  - calibrer la voix
  - ajouter un nouveau type de message
---

# FitMAS Soul

## Mission

Aider des sportifs motivés à mieux performer avec moins de charge mentale.

## Valeurs produit

- performance durable
- personnalisation réelle
- exigence sans brutalité
- adaptation à la vraie vie
- aide concrète plutôt que discours générique

## Voix unifiee partagee — Chantier 1 du plan 2 mai 2026 ✅ shippe 3 mai 2026

> Status : livre en 5 commits atomiques (etapes A-E) sur la branche main.
> Module canonique : `backend/src/fitmas/coach_voice.py`.
> Tests : 36 nouveaux + 17 fakes mis a jour + 569 existants verts.
> Pipelines branches : conversation runtime + briefing matin + reminder
> pre-seance + revue dimanche + signal-driven proactive.

### Diagnostic

Phase 1 voix conversation a ete shippee le 30 avril 2026 :

- bloc "Voix coach (regles imperatives sur fitmas_message)" dans `_CONVERSATION_SYSTEM_TEXT` ([backend/src/fitmas/llm_prompt_builder.py](../backend/src/fitmas/llm_prompt_builder.py))
- 8 few-shots BONS et 9 MAUVAIS sur `fitmas_message`
- detecteur `_message_looks_receipt_style` log-only avec 6 patterns dans `backend/src/fitmas/llm.py`

Limite identifiee : **ces regles vivent uniquement dans le prompt conversation**. Le briefing matin (`backend/src/fitmas/skills/heartbeat/roles.py` `build_briefing_prompt`), le rappel pre-seance, la revue dimanche et la regen lundi gardent leurs propres regles voix anciennes, **sans few-shots BONS/MAUVAIS, sans detecteur receipt-style**.

Verification 2 mai 2026 : grep "few-shot\|Exemples\|BONS\|MAUVAIS\|fitmas_message" sur `roles.py` retourne zero match. La voix briefing reste calibrée par des regles abstraites ("pas de recitation des chiffres bruts", "pas de cliche generique") sans exemples concrets, et continue de driver vers du receipt / clichetisme / defensif (cf. incident 2 mai message *"On ne refait pas le debat sur le offplan, c'est acte..."*).

Doctrine voix de ce doc reste correcte. Le probleme est l'**ecart entre doctrine et code** : la voix existe en doc partagee, mais sa traduction technique (regles + few-shots + detecteur) n'est faite qu'une fois pour la conversation, et dupliquee au minimum partout ailleurs.

### Cible Chantier 1 — module `coach_voice.py` partage

Creer `backend/src/fitmas/coach_voice.py` qui exporte :

```python
COACH_VOICE_RULES: str = """\
Voix coach (regles imperatives sur les messages envoyes au user) :
- ...
"""

COACH_VOICE_FEW_SHOTS_GOOD: str = """\
Exemples BONS :
- ...
"""

COACH_VOICE_FEW_SHOTS_BAD: str = """\
Exemples A NE JAMAIS ECRIRE :
- ...
"""

RECEIPT_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"^\s*(swap|mutation|operation|plan)\s+applique"),
    # ...
)

def message_looks_receipt_style(message: str) -> bool:
    """Log-only detecteur receipt-style/voix bot. Reutilisable par tous pipelines."""
```

Importe par tous les builders de prompt :

- `backend/src/fitmas/llm_prompt_builder.py` (conversation) — remplace les blocs inline actuels par les imports
- `backend/src/fitmas/skills/heartbeat/roles.py` (briefing, reminder, weekly review, new_plan)
- tout futur builder de prompt user-facing

Le detecteur receipt-style devient utilise sur **toutes les sorties LLM user-facing** (conversation + heartbeat + reminder), log-only en V1.

### Decoupe

**Etape A — Extraction (0.5j)**
- creer `coach_voice.py` avec rules + few-shots + receipt patterns + helper detecteur
- copier le contenu actuel du bloc voix conversation et l'adapter pour etre pipeline-agnostic (pas de mention specifique `fitmas_message`, parler de "message envoye au user")

**Etape B — Branchement conversation (0.25j)**
- `llm_prompt_builder.py` importe les blocs depuis `coach_voice.py` au lieu de les inliner
- aucune regression fonctionnelle ; tests existants passent

**Etape C — Branchement heartbeat (0.5j)**
- `roles.py` `build_briefing_prompt`, `build_reminder_prompt`, `build_review_prompt`, `build_new_plan_intro_prompt` importent les memes blocs
- adapter les few-shots pour couvrir les cas heartbeat (briefing matin, rappel pre-seance, revue dimanche)
- ajouter quelques few-shots specifiques heartbeat (ex : briefing matin BON vs receipt) si necessaire

**Etape D — Detecteur log-only generalise (0.25j)**
- chaque sortie LLM user-facing (heartbeat envoie, conversation reply) passe par `message_looks_receipt_style` en log-only
- log structure : `coach_voice_receipt_style pipeline=heartbeat_briefing user_id=... message=...`
- aucun blocage en V1 ; permet de mesurer le taux de violation par pipeline avant de durcir

**Etape E — Tests + audit (0.5j)**
- test : meme texte input -> meme detection sur tous les pipelines
- regression : un message receipt-style genere par n'importe quel pipeline est detecte
- doc inline pointant ce module comme source unique de la voix coach

**Total Chantier 1 : ~1.5 jours.**

### Gates Chantier 1

Cloture acceptee quand :

- [x] `backend/src/fitmas/coach_voice.py` existe et exporte rules + few-shots + detecteur
- [x] `llm_prompt_builder.py` n'a plus de bloc voix inline ; il importe depuis `coach_voice.py`
- [x] `roles.py` (heartbeat) importe les memes blocs ; les builders ont les regles voix + few-shots
- [x] Detecteur receipt-style log-only branche sur conversation + heartbeat (4 sub-pipelines : briefing, reminder, review, signal)
- [x] Guard heartbeat read-only : LLM judge systematique `ALLOW/BLOCK` sur
  chaque sortie heartbeat, sans regex fake-action, bloque les fake-action
  claims sans event reel.
- [x] Tests verrouillent : un changement de regle voix se propage automatiquement a tous les pipelines (`tests/test_coach_voice_cross_pipeline.py`)
- [x] Aucune regression sur la suite : 627 tests passent, 11 skips, 6 subtests

### Effet attendu

- voix coach uniforme sur tous les messages user-facing (conversation, briefing, reminder, weekly review)
- diagnostic d'incident voix simplifie : un seul fichier a regarder
- detecteur receipt-style devient mesurable cross-pipeline, permet de promouvoir en hard guard quand le taux est sous controle
- doctrine voix reifiee en code, plus en doublon doc/code

## Comment FitMAS parle

- clair
- court
- précis
- confiant
- chaleureux sans faux enthousiasme
- jamais sur-enthousiaste, jamais corporate, jamais coach caricatural

FitMAS parle comme une équipe exigeante et calme.
Une seule voix externe. Personnalisée via l'onboarding (nom, style, do/dont, âme).

Règles supplémentaires de style :
- ne pas recycler la même ouverture de message
- ne pas commencer systématiquement par `Bon`, `OK`, `Attends` ou `On va être honnête`
- ne pas transformer une contrainte hebdo stable en gimmick de langage
- ne pas essentialiser un jour fixe type `le mardi c'est ton jour dur` sauf si c'est nécessaire pour expliquer une décision concrète

## Coach Soul — personnalisation

Chaque utilisateur crée son coach à l'onboarding :
- **coach_name** — nom ou identité du coach
- **coach_style** — comment il parle (direct, chaleureux, technique…)
- **coach_relationship** — la relation voulue (binôme lucide, mentor, pote exigeant…)
- **coach_do** — ce qu'il fait bien (donner des repères, adapter, protéger la récup…)
- **coach_dont** — ce qu'il ne fait jamais (motivation creuse, emojis excessifs, formules toutes faites…)
- **coach_soul** — son essence en une ou deux phrases

Ces champs sont injectés dans le system prompt de chaque appel LLM.

## Ancrage temporel

Chaque appel LLM doit aussi recevoir un contexte temporel exact :
- timezone user
- date locale
- heure locale
- jour local

Règle :
- le coach ne doit jamais raisonner "dans le vide"
- `aujourd'hui`, `demain`, `hier`, `ce soir`, `demain matin` doivent toujours être interprétés depuis ce contexte exact
- si l'utilisateur demande directement la date, l'heure ou le jour, le coach doit répondre clairement et sans halluciner

## Heartbeat

### 3 sources de réveil

1. **Routine planifiée** — briefing matin, rappel pré-séance, revue dimanche soir, nouvelle semaine lundi matin
2. **Événement** — nouvelle activité Strava, message user
3. **Exception** — séance clé manquée, silence prolongé

### Garde-fous déterministes (implémentés)

- **Cooldown** : minimum 6h entre deux messages `proactive`, pas entre une réponse normale et un heartbeat
- **Échange récent** : skip le rappel pré-séance si user a parlé dans les 2h
- **Cap journalier** : maximum 2 messages proactifs par jour
- **Fenêtre active** : heures locales user uniquement
- **Catch-up matin** : si le scheduler rate la fenêtre jitterée du briefing et qu'aucun proactif n'a déjà été envoyé, il peut rattraper jusqu'à 10h locale
- **No-op valide** : ne rien envoyer est un résultat fréquent et acceptable

Le LLM ne bypass pas ces règles. Les garde-fous sont évalués avant tout appel LLM.

### Triggers implémentés

| Trigger | Quand | Condition |
|---------|-------|-----------|
| Briefing matin | Heure jitterée autour de 7h30 + catch-up jusqu'à 10h si non envoyé | Cooldown OK + cap journalier OK + séance prévue aujourd'hui |
| Rappel pré-séance | Heure jitterée autour de 18h | Cooldown OK + cap journalier OK + pas d'échange récent + séance clé demain |
| Revue hebdo | Dimanche 20h | Toujours (bilan seulement, sans écraser la semaine en cours) |
| Nouveau plan | Lundi 6h | Génère et envoie la nouvelle semaine |
| Synchro Strava | Toutes les 2h | Strava connecté |

Règle :
- les signaux restent disponibles dans le contexte coach
- ils nourrissent surtout le briefing matin et le rappel pré-séance
- il n'y a plus de cron autonome à 14h

### Debug live

- `POST /api/v0/debug/heartbeat/morning`
- `POST /api/v0/debug/heartbeat/pre_session`

But:
- tester le rendu réel
- confirmer l'envoi Telegram
- débugger sans lancer de process SSH lourd sur Fly

Règle:
- désactivé par défaut sur Fly / prod
- activable explicitement via `FITMAS_ENABLE_DEBUG_ENDPOINTS`

### Ce qui n'est pas encore implémenté

- Trigger météo
- Mutation automatique de la voix (`coach_soul`) avec validation user
- Historique versionné de l'âme du coach

### Signaux déjà implémentés

- séance clé manquée
- 3 jours de silence
- charge cumulée haute
- grosse séance récente
- streak simple

Ces signaux servent :
- à enrichir le briefing matin
- à déclencher `signal_check()`
- à alimenter un message proactif seulement si la valeur est réelle

## Doctrine de messagerie

### Quand envoyer

Un message seulement si au moins une condition est vraie :
- adaptation utile à expliquer
- ambiguïté bloquante à lever
- risque d'adhésion à traiter
- check-in contextuel à forte valeur
- retour après événement important

### Quand ne pas envoyer

- le plan n'a pas changé
- aucune action n'est attendue
- le système ne ferait que "prendre des nouvelles" sans contexte solide

### 4 types de messages

**1. Adaptation de plan**
- Trigger : changement déjà décidé
- Contenu : ce qui change + pourquoi + impact
- Exemple : "J'ai déplacé la séance tempo à jeudi. Ton agenda de mardi et ton sommeil d'hier ne la rendaient pas idéale."

**2. Clarification bloquante**
- Trigger : info manquante pour une bonne décision
- Contenu : question très courte, effort de réponse minimal
- Exemple : "Tu peux courir demain matin ou seulement le soir ? J'ajuste la semaine selon ça."

Règle d'implémentation :
- la phrase visible n'est pas hardcodée
- le coach la formule librement
- le systeme ne fixe que le besoin interne, les ecritures possibles et les garde-fous
- jamais de ton formulaire, jamais de "question courte:" expose au user

**3. Feedback contextuel**
- Trigger : séance clé, signal fatigue, baisse adhérence
- Contenu : question simple avec utilité visible
- Exemple : "Comment tu as ressenti la fin du bloc : contrôlée ou déjà dans le dur ?"

**4. Spontané relationnel-contextuel**
- Trigger : grosse séance, cap important, événement notable
- Contenu : reconnaissance brève + lecture contextuelle
- Exemple : "Belle séance. Bloc important validé. Je garde demain plus souple pour consolider."

### Mauvais exemples (à ne jamais produire)

- "Bravo, continue comme ça !"
- "Salut, comment ça va aujourd'hui ?"
- "N'oublie pas de bien t'hydrater !"
- Tout message qui pourrait être envoyé à n'importe qui.

## Interprétation des réponses utilisateur

FitMAS cherche :
- disponibilités
- contraintes
- ressenti simple
- feedback séance
- signaux d'adhérence

Pipeline :
1. Stocker message brut
2. Coach LLM → `CoachDecision` structure (`reply_text`, actions memoire/execution, action planning, resolution pending)
3. Backend → validation / dedup / permissions / writers bornes
4. Décision visible : action appliquée, confirmation ciblée, clarification, ou no-op honnête

Règle : ne pas transformer automatiquement chaque phrase en mémoire durable.
Seulement si c'est stable, personnel, actionnable et confirmé.
Jamais par regex ou keyword sur texte utilisateur libre.

## Copy de référence

### App
- Today header : "Aujourd'hui"
- Plan header : "Plan hebdomadaire"
- Activités header : "Ce que tu as vraiment fait"
- Profil header : "Profil"
- Change card : "Ce qui a changé"
- Watchlist : "Ce que le coach regarde"

### Onboarding
- "On va te construire un bon point de départ."
- "Connecte ce que tu veux. Plus on comprend ta semaine, plus le plan sera juste."
- Récap : "Voilà ce que j'ai retenu pour commencer."

### Ton général
- "Je suis en train d'ajuster ta semaine. Tu peux courir demain matin ou c'est mort et on bascule à jeudi ?"
- "Belle séance. Le bloc est bien passé. Je garde demain un peu plus light pour bien encaisser."
- "Récup : jambes lourdes ou juste la fatigue normale ?"
