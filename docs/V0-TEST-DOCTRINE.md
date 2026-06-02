---
summary: doctrine de test du Runtime V0 ; deux couches, matrice mecanique et simulation live
read_when:
  - prouver ou contester une evolution du runtime V0
  - choisir entre matrice et sonde sous-agent
  - lire un resultat de test sans le surinterpreter
---

# Doctrine De Test V0

Tester V0, c'est deux couches aux roles distincts. Ne pas les confondre.
La matrice est un filet mecanique, pas une preuve de qualite.
La vraie qualite ne se juge que dans la simulation live.

## Pourquoi

Barre de preuve (milestone courant) : le potentiel est **montre**. La barre est
maintenant de **prouver V0 meilleur que l'app legacy sur simulation reelle non
scriptee** (couche 2) — pas sur la matrice scriptee, pas sur le replay legacy.
"Meilleur" reste profil-d'echec-first : V0 doit echouer en **securite** la ou
l'app echoue en **danger**, et au moins egaler l'utilite sur les scenarios que
V0 couvre. Jamais farmer un taux brut. Le verdict de verite se **prouve**
(danger metrics a 0, guard fallback < 15 %), il ne s'affirme pas.

## Couche 1 — Matrice Deterministe

```text
outil : scripts/v0_eval/run_matrix.py
forme : 11 scenarios x N reps x providers, scoring mecanique
```

Prouve :

- regression — un comportement connu tient-il encore ;
- danger — `wrong_write`, `old_plan_date`, `wrong_correction_target`,
  `claim_without_event` restent a 0 ;
- cout de la verite — guard fallback rate < 15 %.

Ne prouve PAS la qualite reelle. Elle **scripte les deux cotes** de l'echange,
donc elle ne verra jamais une reponse coach qui fait derailler une vraie
conversation. Vecu : elle scorait `followup_planning_turn1` a 5/5 pendant que
la conversation reelle s'effondrait en `no_send`.

Role : filet. Avant/apres un changement, prouver "rien casse, rien dangereux".
Jamais "c'est bon".

## Couche 2 — Simulation Live

```text
outil  : scripts/v0_eval/drive_turn.py  (seed | turn | state)
joueur : un sous-agent qui joue l'utilisateur, un tour a la fois
monde  : une shadow DB persistee (jamais la prod)
```

C'est **la** que se simule et se juge la vraie qualite, comparaison comprise.
La conversation n'est pas scriptee : le coach repond pour de vrai a chaque tour.
L'etat (pending, `last_unresolved_intent`) persiste entre tours via la shadow DB.
`today` vient du timestamp de l'event (`--date`), pas de l'horloge, donc un run
est reproductible.

A trouve le `no_send` au premier run aveugle, la ou la matrice scorait 5/5.

### Scenario derive d'un echec reel

`move_today_open_week` (dans `scenarios.py`, hors `DEFAULT_SCENARIOS` donc hors
matrice) rejoue l'echec app du 1 juin 2026 : user pas dispo, demande de deplacer
la seance du jour, semaine et week-end ouverts. L'app a **fabrique** un blocage
"fin de semaine saturee" puis a **faussement cloture** ("ca roule") sans rien
deplacer.

```bash
python3 scripts/v0_eval/drive_turn.py seed --scenario move_today_open_week --db .tmp-v0-couche2/move_today.db
python3 scripts/v0_eval/drive_turn.py turn --db .tmp-v0-couche2/move_today.db \
  --text "Salut, je suis pas dispo aujourd'hui, tu peux déplacer ma séance ?" \
  --turn-id c2t1 --date 2026-06-01 --hour 11 --minute 24
python3 scripts/v0_eval/drive_turn.py state --db .tmp-v0-couche2/move_today.db
```

Run DeepSeek (3 tours, 1 juin 2026) : tour 1 demande le jour cible sans inventer
de calendrier et **persiste** `last_unresolved_intent = move_session`; tour 3 le
move est **committe** (`ApplyPlanPatchCommand`, seance #81 du 1 -> 2 juin), reply
porteuse du fait et soutenue par l'event. Zero write errone, zero cloture
mensongere : V0 echoue/agit **safe + utile** la ou l'app echoue **dangereux +
incapable**. Friction honnete relevee par la couche 2 : une clarification de
trop (le `source_ref` "seance d'aujourd'hui", deja verbalise au tour 1, n'est pas
porte quand la date se resout). Notee, non patchee — c'est sur, pas dangereux,
et un fix reflexe trahirait la doctrine anti-reactive.

### Trou d'utilite revele par seed reel (2 juin 2026)

Depuis que la couche 2 peut partir du vrai monde (`drive_turn.py seed
--from-real-db`, tranche #2 S2), un run seede sur une vraie DB a revele un trou
que la matrice ne voit pas : sur une demande de deplacement claire ou l'user **ne
nomme pas le jour** ("pas dispo aujourd'hui, decale-le"), le coach restait muet —
DeepSeek `no_send` 3/4, Grok 4/4. Safe (zero write, zero fausse cloture) mais
inutile.

Racine : `propose_plan_patch` exige une `target_date` blanchie par
`resolve_date_reference`, mais le prompt ne declenchait ce chemin que pour un jour
**nomme par l'user**. Sans jour nomme, le coach posait une date brute -> rejet
`planning_date_not_resolved` -> `no_send`. Contre-epreuve : un jour nomme committe
4/4 (`resolve_date_reference` appele a chaque fois).

Fix (LLM-first, commit `8ff5dc8`) : principe general d'adaptation a une contrainte
— l'user donne une contrainte, pas une solution ; le coach choisit l'adaptation,
choisit lui-meme un jour ouvert, le ground via `resolve_date_reference`, puis
`propose_plan_patch`. Zero keyword sur le texte user ; la policy garde
commit/pending ; le choix reste celui du LLM. Post-fix couche 2 (DeepSeek x4) :
`no_send` 4/8 -> 0/8, move committe CLEAR 1/4 -> 4/4, OPEN 1/4 -> 3/4, 100 % safe.
Cross-provider : Grok post-fix 4/4 commit (etait 0/4), dont 1 reply rattrapee par
le guard (`guard_ok` false, write correct) — flakiness reply Grok, pas une
regression du fix (DeepSeek 8/8 `guard_ok`).

Lecon : la matrice scorait ces tours verts (elle scripte les tool-calls du coach,
donc ne voit jamais le coach muet). Seul un seed reel en couche 2 l'a expose.

### Discrimination skip-vs-move + arc multi-tours (2 juin 2026)

Mesure skip-vs-move (probes ×4, vrai monde) : seance **passee** -> `execution_update`
(skip) 4/4 ; **future empechee** -> `plan_patch` (move) 4/4. Discrimination des cas clairs
solide, sans code. Ambigu ("j'ai pas fait ma seance") : 2/4 `ask_clarification`, 2/4 devine
un skip — **safe** (reversible, event-backed) et coherent avec le fact "l'user prefere que
le coach decide". Laisse au LLM, pas de regle imposee (forcer "demande" entrerait en conflit
avec la preference + sur-correction).

Arc joueur aveugle 3 tours (vrai monde) : T1 "pas dispo jeudi" -> move fartlek jeu->ven ;
T2 "mercredi non plus" -> move natation mer->jeu **en se calant sur le fartlek deja deplace**
(raisonnement explicite). **Coherence cross-tour prouvee SANS transcript** : c'est le monde
persiste (la mutation T1) qui porte le fil, pas l'historique de conversation — exactement le
design. T3 cloture sociale ("merci, t'es au top") -> `no_send` : safe (zero write fabrique
sur un simple merci) mais **froid** (reply non-sequitur "je n'ai aucune information..."). Minceur
Groupe B (rapport sans action) confirmee en reel — a traiter plus tard, jamais en relachant
l'anti-hallucination.

Audit filet backend (probe directe policy) : un move vers une date **passee** est bloque
(`target_date_out_of_range`) ; marquer une seance **future** "done"/"partial" l'est desormais
aussi (`ask_clarification` / `future_session_not_completable`, net pose le 2 juin 2026 dans
`_execution_update`). Un skip pre-emptif futur et un "done"/"partial" du jour restent valides.
Le coach ne l'avait jamais declenche, mais l'etat etait incoherent et l'OutputGuard ne pouvait
pas l'attraper (la fausse claim est portee par un event reel committe) — fix doctrine-aligne =
validation d'un artefact LLM, pas du texte user.

### Mecanisme d'honnetete (le coeur)

Separation **joueur / juge** :

- **Joueur** = le sous-agent. Aveugle aux internes V0. Joue un user realiste
  avec un objectif. Ne note JAMAIS le succes.
- **Juge** = oracle mecanique. Lit l'etat DB (`drive_turn.py state` : sessions,
  pending, commands), pas le ressenti d'une reponse. Tranche sur la structure.

Sans cette separation, le juge se fait berner par une reponse fluide-mais-fausse
et le joueur teleguide la conversation vers un pass.

## Lire Un Resultat Sans Se Tromper

- **Variance** : un LLM est non-deterministe. 4/5 vs 5/5 peut etre du bruit.
  Avant d'imputer un changement, pooler le MEME scenario sur plusieurs runs pour
  etablir le taux de panne de base. Vecu : `hard_unsafe_block` etait deja 3/5
  avant tout changement ; un run isole a 5/5 etait l'exception, pas la base.
- **Goal coherent** : l'objectif du joueur doit etre interne-coherent. Un
  objectif contradictoire (ex. une erreur de date) brouille l'oracle et invente
  de faux echecs.
- Un run de simulation = une anecdote riche, pas un chiffre. La couche 2 revele
  des classes de bug ; la couche 1 mesure si elles reviennent.

## Discipline

- Matrice = gate de regression/securite. Obligatoire avant de declarer un fix
  prouve. Ne pas la surinterpreter comme une mesure de qualite.
- Simulation = preuve de qualite. Obligatoire avant dogfood ; un chiffre matrice
  ne suffit pas. Ne pas la chiffrer comme une matrice.

## Legacy

`scripts/v0_eval/compare_app_vs_v0.py` (avec `spike_real_turn.py`,
`real_snapshot.py`, `oracle_compare.py`) rejouait des tours de prod captures
pour comparer V0 au pipeline app sur le meme monde. **Remplace par la simulation
sous-agent (couche 2).** Conserve pour reference, plus le chemin recommande.
