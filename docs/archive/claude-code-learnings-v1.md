---
summary: synthese fusionnee des enseignements Claude Code, croisee avec les sources publiques verifiees et orientee decisions utiles pour FitMAS
read_when:
  - reflechir a l evolution agentique de FitMAS
  - faire evoluer runtime tools ou la boucle conversationnelle
  - arbitrer mono-agent vs subagents
  - concevoir task system, compaction de contexte ou permissions
  - choisir quoi reprendre ou ignorer des patterns Claude Code
---

# Claude Code - synthese utile pour FitMAS

## But

Cette note fusionne :

- la note precedente orientee "learnings"
- le compte rendu produit par Claude
- une verification externe sur les artefacts publics encore accessibles

Objectif :

- separer les faits solides du folklore post-leak
- garder les patterns qui valent vraiment le coup
- transformer ca en decisions pragmatiques pour FitMAS

Date de synthese :

- **31 mars 2026**

## Methode et niveau de confiance

## Sources primaires verifiees

Ce que j'ai verifie directement :

- notice DMCA GitHub du **10 mars 2025** visant `anthropics/claude-code` comme oeuvre originale et `dnakov/claude-code` comme repo retire, avec action sur un reseau de **438 repositories**
- package npm officiel `@anthropic-ai/claude-code`
- version npm publique observee le **31 mars 2026** : **2.1.87**
- `sdk-tools.d.ts` du package officiel recent
- repo public `Kuberwastaken/claude-code`
- repo public `instructkr/claw-code`
- repo public `shareAI-lab/analysis_claude_code`

## Sources secondaires credibles

Utiles pour comprendre les patterns, mais a traiter comme reconstruction / synthese :

- `Kuberwastaken/claude-code` :
  - aujourd'hui surtout une **clean-room reimplementation Rust**
  - avec une **spec** assez detaillee de l'ancien systeme TypeScript
- `shareAI-lab/analysis_claude_code` :
  - reconstruction pedagogique des mecanismes agentiques
- `instructkr/claw-code` :
  - miroir/reimplementation centree sur le harness

## Ce que je downgrade explicitement

Je ne traite pas comme verite dure, sauf confirmation supplementaire :

- l'histoire exacte du leak via `@anthropic-ai/claude-code@2.1.88`
- la presence certaine d'un sourcemap `.map` de `59.8 MB` dans une version npm publique encore visible
- les noms internes precis comme `nO`, `h2A`, `Tengu`
- les line counts hyper precises relayées par des blogs
- les details exacts de features unreleased comme `KAIROS`, `ULTRAPLAN`, `BUDDY`

Point de correction important :

- `npm view @anthropic-ai/claude-code@2.1.88 version` renvoie **404**
- donc la version `2.1.88` citee dans l'autre doc n'est pas une base assez solide pour notre doc canonique

Autre correction importante :

- `Kuberwastaken/claude-code` **n'heberge plus le TypeScript original**
- son README le dit explicitement
- il faut donc le lire comme **spec secondaire utile**, pas comme preuve brute

## Ce qu'on peut tenir pour solide

## 1. Claude Code est surtout un harness autour d'une boucle simple

Le pattern central reste :

1. assembler `messages + system + tools`
2. appeler le modele
3. laisser le modele repondre ou demander des tools
4. executer les tools
5. reinjecter les resultats
6. reboucler

Le vrai enseignement n'est pas "ils ont un secret multi-agent".

Le vrai enseignement est :

- le modele fait l'essentiel du raisonnement
- le code entoure le modele avec :
  - outils
  - permissions
  - contexte
  - etat externe
  - isolation

Autrement dit :

- **le produit est surtout un bon harness**

## Lecture FitMAS — avril 2026

Ce qu'on a bien repris :

- la séparation entre contexte durable et contexte injecté
- la valeur de tools sémantiques bornés
- la priorité au mono-agent bien outillé
- le transcript comme unité d'audit

Ce qu'on a seulement partiellement repris :

- la vraie atomicité des décisions métier
- la compaction fondée sur des couches réellement vivantes partout
- la séparation stricte entre compréhension, choix et action

Ce qu'il ne faut pas mal comprendre :

- "Claude Code a plein de liberté" ne veut pas dire qu'un coach produit doit tout laisser émerger du modèle
- les bonnes surfaces typed servent surtout à réduire l'ambiguïté et à rendre l'action pilotable

Leçon pratique pour FitMAS :

- lecture atomique : déjà correcte
- décision atomique : encore insuffisante
- il faut extraire davantage de primitives métier, pas seulement davantage de prompts

## 2. La surface de tools est riche, et surtout typée

Le package officiel recent expose clairement une surface typed pour :

- `BashInput`
- `FileReadInput`
- `FileWriteInput`
- `FileEditInput`
- `GlobInput`
- `GrepInput`
- `TodoWriteInput`
- `WebFetchInput`
- `WebSearchInput`
- `ReadMcpResourceInput`
- `EnterWorktreeInput`
- `ExitWorktreeInput`
- `ExitPlanModeInput`
- `AgentInput`

Lecture forte :

- ils n'ont pas tout mis dans un tool shell unique
- ils ont prefere des **actions semantiques et etroites**
- le shell reste la, mais ce n'est pas le seul langage du systeme

Le snapshot public des tools renforce cette lecture, avec notamment :

- `AgentTool`
- `BashTool`
- `FileReadTool`
- `FileWriteTool`
- `FileEditTool`
- `GlobTool`
- `GrepTool`
- `WebFetchTool`
- `WebSearchTool`
- `MCPTool`
- `SkillTool`
- `TodoWriteTool`
- `TaskCreate/Get/List/Update/Stop/Output`
- `TeamCreateTool`
- `TeamDeleteTool`
- `SendMessageTool`
- `EnterPlanModeTool`
- `ExitPlanModeTool`
- `EnterWorktreeTool`
- `ExitWorktreeTool`

Lecon forte :

- plus un tool est semantique, plus il est pilotable
- plus un input/output est type, plus il est reusable
- plus une action est etroite, plus la permission est lisible

## 3. Le plan est une primitive produit, pas juste un prompt trick

Le couple `EnterPlanMode` / `ExitPlanMode` apparait comme un vrai concept du produit.

Le type `ExitPlanModeInput` est particulierement utile :

- il accepte des `allowedPrompts`
- rattaches a un tool
- aujourd'hui surtout `Bash`

Ca suggere un pattern plus profond :

- le plan ne sert pas seulement a mieux penser
- le plan sert aussi a **contractualiser l'action a venir**
- permissions et plan ne sont pas separes

Lecon forte :

- **plan = contrat visible entre intention et action**

## 4. Delegation et subagents sont reels, mais bornes

Le type `AgentInput` officiel expose :

- `description`
- `prompt`
- `subagent_type`
- `model`
- `run_in_background`
- `name`
- `team_name`
- `mode`
- `isolation`

Ca raconte deja une architecture :

- delegation explicite
- specialisation par type d'agent
- choix du modele
- execution en background possible
- rattachement a une team
- mode de permission specifique
- isolation possible en `worktree`

Le pattern important :

- les subagents ne sont pas la base du produit
- ils sont une **surcouche de delegation borne**

## 5. Todo, tasks et background sont des concepts de premier rang

Le package officiel et la spec secondaire pointent ensemble vers trois niveaux differents :

### todo

- pilotage court terme de la session
- petit, vivant, modifiable souvent

### task

- unite d'execution plus durable
- observable
- stoppable
- avec output recuperable

### background

- un shell ou agent peut tourner sans bloquer le thread principal
- avec sortie relisible plus tard

Lecon forte :

- ne pas melanger checklist de raisonnement et execution durable

## 6. L'isolation de travail est prise tres au serieux

Les artefacts publics confirment :

- `EnterWorktree`
- `ExitWorktree`
- `AgentInput.isolation = "worktree"`
- gestion explicite du retour a l'espace de travail initial

Lecon forte :

- paralleliser sans isolation = collision
- si plusieurs executeurs travaillent sur le meme substrate, l'isolation doit etre explicite

## 7. Les extensions sont pensees des le coeur du produit

On voit clairement :

- MCP
- ressources MCP
- plugins / marketplace
- skills
- `CLAUDE.md`

Le produit semble penser l'extension comme un concept de premier rang, pas comme un patch tardif.

Lecon forte :

- noyau mince
- bords extensibles

## 8. Le contexte est couche, pas juste "un gros prompt"

Ce qui est confirme ou fortement suggere :

- presence de `CLAUDE.md`
- exclusions possibles de `CLAUDE.md`
- presence de `compact`
- presence de `memory`
- presence de `transcript`
- presence d'un `SYSTEM_PROMPT_DYNAMIC_BOUNDARY` dans la spec et la reimplementation secondaire

Le detail exact de la compaction interne reste secondaire.
Mais le pattern est clair :

- tout n'est pas laisse dans la fenetre active
- il y a separation entre :
  - instructions stables
  - contexte dynamique
  - historique externalise

Lecon forte :

- **etat durable hors prompt**
- **resume exploitable dans le prompt**

## 9. Les permissions sont un pilier UX, pas juste une garde basse-niveau

Le package officiel montre :

- des modes de permissions pour les agents
- des settings de type `allow / deny / ask / defaultMode`
- `additionalDirectories`
- `dangerouslyDisableSandbox` pour Bash
- des descriptions semantiques de ce que fait une commande

La spec secondaire ajoute, de facon credible mais moins primaire :

- auto-approval / classifier
- explication separee du risque
- protected files
- sandboxing plus riche

Lecon forte :

- la permission est une surface produit
- elle structure :
  - la confiance
  - la vitesse
  - le confort d'usage
  - la gouvernance

## Ce que les sources secondaires ajoutent de plausible

Je garde ces points comme **credibles** et **utiles**, sans les sur-vendre.

## 1. Une boucle principale single-threaded

Les spec reconstruites convergent vers :

- une boucle principale simple
- pas un graphe d'orchestration complexe par defaut
- le multi-agent vient apres

Pour nous, c'est un signal fort :

- la robustesse vient d'abord du mono-agent bien outille

## 2. Tool search / deferred loading

La spec secondaire insiste sur `ToolSearch` et sur des outils "deferred".

Le pattern est tres bon :

- tout declarer coute cher en tokens
- ne charger le detail que quand il devient utile

## 3. Memoire longue + consolidation periodique

Les sources secondaires convergent sur :

- memoire par fichiers / memdir
- index compact
- consolidation de fond type `autoDream`

Je ne prends pas le folklore "Claude reve" comme design principle.
Je prends l'idee utile :

- une memoire durable ne doit pas etre juste append-only
- elle doit etre :
  - consolidee
  - de-duplicatee
  - contradiction-aware
  - taillee pour le prompt

## 4. Proactivite tick-based

Les elements autour de `KAIROS` sont secondaires.
Mais l'idee produit est bonne :

- evaluer regulierement "est-ce que j'ai quelque chose d'utile a dire ?"
- plutot que parler a heure fixe sans nuance

## 5. Pre/post hooks autour des actions

Les hooks dans l'ecosysteme secondaire sont credibles et surtout tres reutilisables conceptuellement :

- valider avant
- recalculer / logger apres

## 6. Feature flags partout

Ca ressort fortement des specs et de plusieurs repos :

- beaucoup de capabilities semblent developpees avant publication
- gates compile-time et runtime

Lecon forte :

- preparer sans tout shipper

## Ce que je retire ou minimise par rapport a l'autre doc

L'autre doc contenait des choses interessantes mais trop assertives pour une doc canonique FitMAS.

Je retire ou downgrade donc explicitement :

- l'affirmation que le leak publie verifie etait `@anthropic-ai/claude-code@2.1.88`
- le chiffre "59.8 MB sourcemap" comme fait etabli
- les labels internes `nO`, `h2A`, `Tengu` comme base d'architecture
- les line counts trop precis
- les points plus "presse / gossip" que design :
  - anti-distillation fake tools
  - lore codenames
  - attribution headers
  - buddy / tamagotchi comme sujet principal

Ca ne veut pas dire que c'est faux.
Ca veut dire :

- ce n'est pas assez robuste pour piloter nos choix

## Ce qui est vraiment bon a prendre pour FitMAS

## 1. Garder le coeur mono-agent

Notre doc `ARCHITECTURE.md` a raison :

- pas de multi-agent produit maintenant

Le vrai deficit actuel de FitMAS n'est pas :

- le manque de swarms

Le vrai deficit est plutot :

- compaction
- continuite de contexte
- tools metier plus semantiques
- task/job log durable
- meilleure gouvernance de mutation

Decision :

- **un seul orchestrateur LLM reste la bonne base**

## 2. Ajouter un vrai petit task/job log durable

Pas un workflow engine geant.
Un log/executor minimal pour :

- jobs lents
- sorties persistantes
- statut
- duree
- erreur
- resultat
- replay / debug

Tres bon pattern a reprendre de Claude Code :

- distinguer
  - ce que l'agent pense devoir faire
  - de ce qui tourne vraiment dans le runtime

## 3. Renforcer les runtime tools avec des tools metier etroits

Pas de shell libre pour le coach.
Pas de write tool large.

La bonne direction FitMAS reste :

- tools read-only
- petits
- outputs types
- routing determinant

Exemples utiles chez nous :

- `get_recent_reality_window`
- `get_scheduled_session_detail`
- `get_user_constraints_window`
- `get_load_context`
- `get_pattern_signals`
- `resolve_indication_target`

## 4. Introduire des skills charges a la demande

Tres bon candidat court terme.

Pas des skills generiques.
Des skills metier et ops.

Exemples FitMAS :

- grounding conversationnel
- adaptation d'indisponibilite future
- revue hebdo
- debug "prevu vs reel"
- lecture pattern memory
- triage signaux fatigue / douleur / charge

Pattern recommande :

- descriptions courtes disponibles en permanence
- corps complet charge seulement quand pertinent

## 5. Ajouter une vraie compaction avec transcript persiste

Probablement le meilleur next step agentique utile pour nous.

Objectif :

- moins de dump
- moins de drift
- plus de continuite
- meilleure auditabilite

Important :

- l'aligner sur `MEMORY-V2`
- ne pas recreer une memoire floue

Mapping propre pour FitMAS :

- `Event Truth` reste la verite episodique
- `Profile Memory` reste petit et durable
- `Working Memory` reste courte et purgeable
- `Pattern Memory` reste promue lentement
- les transcripts de conversation ne deviennent pas de la memoire durable par defaut

## 6. Adopter un prompt en deux zones

Tres utile chez nous.

### zone statique

- role FitMAS
- ton
- garde-fous
- definitions de tools
- regles de securite / mutation

### zone dynamique

- profil resume
- contexte local temps/date
- fenetre planning compacte
- facts utiles
- signaux actifs
- quelques messages recents
- resume si conversation longue

Lecon :

- on ne doit plus injecter toujours les memes blocs

## 7. Introduire un "plan mode" metier

Tres bon pattern a reutiliser.

Pas un plan mode de coding.
Un plan mode de mutation / adaptation.

Cas FitMAS typique :

- "je suis fatigue"
- "je ne peux pas jeudi soir"
- "j'ai mal au genou"

Le systeme devrait parfois construire un plan explicite avant d'agir :

- ce qui est touche
- la seance cible
- l'impact charge / semaine
- la proposition
- la validation necessaire ou non

Lecon forte :

- **plan = contrat visible avant mutation non triviale**

## 8. Ajouter du background propre

Tres utile pour nous avant meme toute delegation LLM.

Usages :

- syncs
- imports
- consolidations memoire
- recalculs
- regeneration plan si couteuse

Pattern :

- job lance
- output persiste
- statut interrogeable
- notification possible plus tard

## 9. Experimenter plus tard avec une proactivite tick-based

Aujourd'hui :

- nos crons fixes sont simples et fiables

Demain, si on veut monter en finesse :

- tick regulier
- score d'urgence / pertinence
- decision de parler ou non

Mais ce n'est pas un pre-requis.

## 10. Garder les side effects metier hors subagents

Si un jour on introduit des subagents, ils doivent surtout :

- explorer
- verifier
- resumer
- proposer

Et non :

- muter directement l'etat metier critique

Regle FitMAS recommande :

- les subagents retournent un draft / decision / payload
- l'orchestrateur principal execute ensuite

## Ce qu'il ne faut pas cargo-cult

## 1. Pas de swarm produit maintenant

Pourquoi :

- cout
- observabilite
- fiabilite
- besoin produit non prouve

## 2. Pas de memory blob fourre-tout

On a deja un meilleur contrat avec `MEMORY-V2`.

Il faut garder :

- memoire structuree
- write less
- promote slowly

## 3. Pas de write tools libres cote coach

Le produit n'est pas un IDE.
Le modele ne doit pas avoir :

- DB brute
- shell
- mutation libre

## 4. Pas de marketplace/plugin system produit

Trop tot.
Trop de confiance a gerer.
Trop de dette de compatibilite.

## 5. Pas de fascination pour le folklore interne

Les codenames et features flashy sont amusants.
Ils n'aident presque pas FitMAS.

## Roadmap FitMAS inspiree de cette analyse

## Phase 1 - maintenant

Objectif :

- renforcer le mono-agent
- sans changer le contrat produit

Chantiers :

1. prompt en 2 zones + cache breakpoint
2. debounce Telegram pour les rafales courtes
3. dates absolues + `profile_summary` compact
4. permissions tiers sur les mutations
5. transcript structure persiste

Notes :

- a ce stade : `transcript > compaction`
- le plan mode doit etre proportionnel a l'impact
- pas besoin d'un systeme de skills formel tout de suite

## Phase 2 - prochain niveau de maturite

Objectif :

- mieux gouverner les operations plus complexes

Chantiers :

1. consolidation memoire periodique
2. enrichment du registry de runtime tools semantiques
3. petit task/job log durable
4. background jobs avec statuts et output
5. score de proactivite plus fin / tick-based

## Phase 3 - seulement si la douleur est reelle

Objectif :

- delegation borne

Chantiers :

1. skills formels si assez de workflows repetes
2. plan mode plus explicite sur mutations a impact fort
3. subagents specialises lecture / verification
4. zero recursion
5. zero side effect metier direct depuis un subagent
6. retour au parent sous forme de decision / draft

## Decomposition tool / skill recommandee

Avant toute nouvelle capability, bonne question :

### si c'est deterministe et reusable

- faire un **tool**

### si c'est un workflow multi-etapes

- faire un **skill**

### si c'est de l'etat durable

- le sortir du prompt

Chez nous, bons candidats :

### tools

- `get_recent_reality_window`
- `get_load_context`
- `get_relevant_constraints`
- `resolve_planning_target`
- `get_pattern_memory`
- `get_session_contract`

### skills

- `adapt_future_constraint`
- `review_recent_reality`
- `explain_missed_session`
- `prepare_weekly_review`
- `triage_fatigue_signal`

### etat durable hors prompt

- transcripts
- job log
- decision log
- calibration needs

## Synthese CTO

Le bon enseignement de Claude Code n'est pas :

- "mettre des agents partout"

Le bon enseignement est :

- **externaliser l'etat que le modele oublie**
- **typer les actions**
- **gouverner les permissions**
- **planifier explicitement**
- **compacter le contexte**
- **n'ajouter delegation et parallelisme qu'apres**

Pour FitMAS, la bonne suite est donc :

1. meilleur harness mono-agent
2. meilleurs tools metier
3. meilleure memoire externe
4. meilleur contrat plan -> action
5. subagents bornes seulement plus tard

## Sources

### primaires verifiees

- [GitHub DMCA notice - 2025-03-10-anthropic.md](https://github.com/github/dmca/blob/master/2025/03/2025-03-10-anthropic.md)
- [npm - @anthropic-ai/claude-code](https://www.npmjs.com/package/@anthropic-ai/claude-code)
- [unpkg - @anthropic-ai/claude-code@2.1.87/package.json](https://unpkg.com/@anthropic-ai/claude-code@2.1.87/package.json)
- [unpkg - @anthropic-ai/claude-code@2.1.87/sdk-tools.d.ts](https://unpkg.com/@anthropic-ai/claude-code@2.1.87/sdk-tools.d.ts)

### secondaires utiles

- [Kuberwastaken/claude-code](https://github.com/Kuberwastaken/claude-code)
- [instructkr/claw-code](https://github.com/instructkr/claw-code)
- [shareAI-lab/analysis_claude_code](https://github.com/shareAI-lab/analysis_claude_code)

### note sur les sources secondaires

Ces repos sont utiles pour comprendre les patterns de harness et les reconstructions de l'architecture.
Ils ne doivent pas etre traites comme specification officielle ou preuve unique sur chaque detail interne.
