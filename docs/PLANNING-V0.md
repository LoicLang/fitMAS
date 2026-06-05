---
summary: architecture cible du moteur sport V0 — le LLM genere, un verificateur deterministe tient l'autorite, co-evolue avec le runtime
read_when:
  - concevoir ou coder le moteur de planification (semaine/bloc)
  - decider du partage LLM vs deterministe sur la generation de plan
  - ajouter un tool moteur appelable par le coach
  - arbitrer coherence long-terme / progressivite / visibilite plan
---

# Planning V0 — Moteur Sport Co-Evolue

## Statut

Vue d'architecture arretee (discussion 2 juin 2026). **Slice 0+1 codee** (5 juin
2026) : modele type Meso + vérificateur deterministe (5 proprietes), prouve en
fixtures dont le rejeu "TSS qui chute" de l'app (`backend/src/fitmas/runtime_v0/meso/`,
plan + spec dans `docs/superpowers/specs/2026-06-05-*`). Le Sport Core V0 actuel
(`V0-DOGFOOD-SCOPE.md`) reste un garde-fou de seance ; ce doc decrit son evolution
vers un moteur de **semaine** (Meso) puis de **bloc** (Macro), construit **en meme
temps que le runtime**, pas a cote.

## Doctrine De Co-Evolution (non negociable)

Le moteur sport et le runtime se construisent **imbriques**, jamais en deux
chantiers separes qu'on tenterait de relier apres.

- Le moteur n'est pas un systeme a part : c'est une **boite a outils appelable par
  le coach**, dans le meme paradigme tool-calling que le runtime actuel.
- Des la conception, chaque capacite moteur = un tool coach-callable :
  intention haut niveau -> moteur deterministe -> proposition typee -> policy gate.
  Meme forme que `propose_plan_patch` aujourd'hui.
- Le coach appelle des **intentions de haut niveau**, jamais les internes du moteur.
- On grandit **un tool a la fois**, chacun prouve en couche 2 avant le suivant.
- Interdit : "finir le runtime puis greffer le moteur". Ils evoluent ensemble,
  sinon ils ne se lieront jamais proprement.

## Principe Central

> Le LLM genere et personnalise. Un verificateur deterministe tient l'autorite.

La fiabilite vient du **verificateur**, pas de contraindre le LLM. "Le determinisme
controle le LLM" = c'est le **verificateur** (+ la policy), jamais un generateur
deterministe. C'est l'oppose de l'app (moteur deterministe qui *genere*, LLM en
role etroit) — et c'est pourquoi l'app est rigide/buggee (ex : TSS qui chute).

Corollaire (extension de la regle texte-user a la generation de plan) :

- determinisme = **mauvais outil** pour comprendre / generer -> LLM ;
- determinisme = **bon outil** pour valider / verifier / committer / auditer ;
- verifier est plus facile que generer -> on met le determinisme du cote tractable.

## Trois Couches

| Couche | Qui porte | Statut |
|--------|-----------|--------|
| Micro (jour/seance) | LLM conversationnel + policy | **prouve** (move/skip sur contrainte, coherence cross-tour) |
| Meso (semaine) | LLM genere -> verificateur juge | a construire (premier livrable) |
| Macro (bloc 4-6 sem) | periodisation -> cibles | differe, mais **accommode** des le design |

## La Boucle Meso (generate -> verify)

```text
cible (deterministe / declaree) -> generateur propose une semaine candidate
   -> verificateur checke
        PASS -> pending (Meso ne s'auto-commit jamais)
        FAIL -> renvoie LES violations -> regenere (max ~3) -> sinon fallback template
```

- Generation = **templates d'abord** (cas standard running, gratuit, previsible),
  **LLM pour la nuance**. Le verif juge les deux.
- Feedback de boucle = violations **structurees**, pas du texte libre.

## Coherence = Gestion De Contexte (pas un moteur de regles)

Le LLM ne gere **jamais** le long-terme (sa faiblesse documentee : planification
long-horizon). Il recoit un **distillat**, pas le firehose. C'est le pattern
snapshot etendu au planning.

Context-pack hierarchique : profil athlete -> plan de bloc -> semaine -> seance.
Pour generer UNE semaine, le LLM voit :

- les **cibles** (calculees / declarees) — elles pre-digerent l'historique long ;
- la **semaine passee en reel** (fait/saute, charge reelle) ;
- les **contraintes** de cette semaine (typees) ;
- les **signaux** recents (fatigue, courbatures, preferences = facts actifs) ;
- PAS l'historique multi-mois ni les streams bruts.

## Verificateur Bi-Mode

Le verif a deux modes ; l'**intention declaree** par le LLM choisit lequel.

- **Continuite** (dans un cycle) : enforce la progression lisse ; rejette les sauts
  et les swaps de type (ex : bloque 20x30sec a la place de 3x5 au seuil).
- **Transition** (frontiere de cycle, declaree + justifiee : "athlete adapte ->
  bloc d'overload") : autorise la discontinuite, mais enforce la **securite** (saut
  borne, recup apres, pas de red-flag) + **pending** systematique.

La declaration distingue le week-end choc justifie du spike accidentel.

## Continuite De Stimulus (le piege du 20x30sec)

La charge-equivalence n'est PAS l'identite de seance. La cible porte le **type**
(seuil continu) + l'**axe de progression** (volume), pas qu'un chiffre de charge.
Le LLM ne choisit pas le type de seance cle — il est prescrit ; le verif rejette
toute derive de type. Le type ne change qu'aux **frontieres de bloc**
(periodisation), jamais semaine-a-semaine pour une equivalence de charge.

## Allocation Du Risque

Role generatif du LLM **le plus petit la ou l'enjeu est le plus grand** :

- seance cle (type + progression) = quasi prescrite -> le LLM n'y touche pas ;
- placement dans la semaine, footings faciles = LLM (faible enjeu) ;
- detail / formulation = LLM.

## Methode

- **Running-only** : le forcage. Charge verifiable **a la main**. Multi-sport
  multiplie les modeles de charge -> complexite differee. Si tu ne peux pas
  verifier la charge a la main, tu ne peux pas prouver la fiabilite.
- **Le cut LLM<->deterministe se decouvre empiriquement** : demarrer ~100% LLM + un
  verif securite minimal ; le determinisme ne grossit que **sur preuve de derive**
  (doctrine anti-reactive appliquee au moteur).
- **L'app = oracle de comparaison permanent** (profil-d'echec). Le verif EST
  l'instrument (ex : il attrape la TSS qui chute des semaines app). L'usine planning
  de l'app = **a strangler, pas a brancher** (buggee / sur-batie).
- **Visibilite 2 semaines garantie** : horizon roulant (committed / tentative),
  cibles calculees d'avance, semaine montree tot + stabilisee dimanche **par
  confirmation** (pas re-roll). Budget de changement = "sans surprise".

## Ordre De Construction

1. **Continuite d'abord** (semaines lisses, running-only), prouvee couche 2 vs app.
2. **Transition / Macro ensuite** (step-change declare + veto securite + pending).
3. L'archi **accommode** la transition des le jour 1 (declaration + hook verif
   bi-mode) ; on la **code** en second.

## Premier Livrable

Le **context-pack running minimal + le verificateur (mode continuite, avec hook
transition)**. Test : generer 4-6 semaines d'affilee -> verif a la main de la
coherence/progression -> comparer au vecu app (le cas TSS qui chute).

Spec a produire en premier : les **4-5 proprietes d'une semaine running saine**,
dont l'anti-TSS-drop ("en build, charge N >= N-1 dans la bande ; chaque seance cle
progresse ou tient vs N-1 ; type de seance cle == type prescrit").

## Questions Ouvertes (a trancher EMPIRIQUEMENT, pas en chambre)

1. Jusqu'ou le **contexte seul** porte la coherence sur 6 semaines avant qu'il
   faille un ancrage deterministe sur la charge **cumulee** (eviter la derive
   surmenage : progression locale OK mais rien ne suit la fatigue accumulee) ?
2. Le **mix generation** templates-vs-LLM par type de seance.
3. La **localisation exacte du cut** LLM<->deterministe (decouverte par le test
   4-6 semaines, pas decidee d'avance).
4. Le **plan de bloc** est-il LLM-declare (et tenu en contexte) ou ancre
   deterministe ? (lie a Q1).
5. **Couches de contexte (sante toujours presente)** — releve 5 juin 2026. Le
   contexte coach doit etre **stratifie en couches**, pas une liste plate tronquee
   par recence (aujourd'hui le header ne montre que les 5 facts les plus recents).
   Les **facts sante = couche a part, TOUJOURS en contexte jusqu'a suppression**
   (resolu/expire), jamais evinces par la troncature. A mesure que les facts
   s'accumulent, definir une strategie de contexte long-terme (distillation /
   couches) qui ne fasse ni exploser le snapshot ni perdre un fact de securite.
   Pas urgent (peu de facts aujourd'hui), a concevoir avec le context-pack (Slice 2).

## Scope V0 (rester simple)

Heriter du scope existant (`V0-DOGFOOD-SCOPE.md`). Le moteur V0 commence par :

- **running-only** ;
- **Meso continuite seulement** (semaine lisse) ;
- generation **template d'abord**, LLM pour la nuance ;
- tout Meso / transition en **pending** (jamais auto-commit d'un replan de semaine).

Hors scope V0 (differe, accommode mais pas code) : Macro / transitions de bloc,
multi-sport, periodisation multi-mois, generation de plan from scratch a grande
echelle.

## Regles Dures

- Le LLM genere / comprend ; le **verificateur + la policy** tiennent l'autorite.
- Aucun write DB hors executor officiel ; aucune reply ne ment sur un write.
- Determinisme = validation / verification / commit / audit, **jamais**
  comprehension ni generation imposee.
- Moteur et runtime **co-evoluent** (tools coach-callable), jamais deux chantiers
  separes.
