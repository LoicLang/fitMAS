---
summary: resultats de comparaison entre l'app actuelle et Runtime V0 sur tours reels
read_when:
  - comparer Runtime V0 au pipeline actuel
  - decider si Runtime V0 peut avancer vers dogfood Telegram
  - analyser les ecarts policy, pending ou qualite de reponse
---

# Runtime V0 vs app actuelle

Passe du 30 mai 2026 sur 30 tours reels recents, avec 3 providers V0.

Commande:

```bash
.venv/bin/python scripts/v0_eval/compare_app_vs_v0.py \
  --real-db .tmp-prod-fitmas.db \
  --limit 30 \
  --providers deepseek,grok,mistral \
  --max-steps 6 \
  --export-dir exports/runtime-v0/app-vs-v0-30 \
  --report-path exports/runtime-v0/app-vs-v0-30/report.md
```

Exports conserves:

- `exports/runtime-v0/app-vs-v0-30/report.md`: rapport lisible, run par run.
- `exports/runtime-v0/app-vs-v0-30/records.json`: donnees brutes du comparateur.

Les DB shadow generees dans `exports/runtime-v0/app-vs-v0-30/db/` ne sont pas destinees a etre versionnees.

## Resultats

| Signal | Valeur |
| --- | ---: |
| Tours reels | 30 |
| Providers | 3 |
| Runs total | 90 |
| `tie_safe` | 73 |
| `app_better` | 17 |
| `v0_better` | 0 |
| `tie_bad` | 0 |
| `inconclusive_snapshot` | 0 |

Par provider:

| Provider | tie_safe | app_better |
| --- | ---: | ---: |
| DeepSeek | 25 | 5 |
| Grok | 24 | 6 |
| Mistral | 24 | 6 |

Flags de risque:

| Flag | Count |
| --- | ---: |
| `missed_pending` | 7 |
| `unhelpful_no_send` | 7 |
| `unsafe_auto_commit` | 6 |

Tous les runs utilisent `snapshot_source=conversation_context`.

## Lecture

Runtime V0 ne montre pas de panne catastrophique dans cette passe: pas de `tie_bad`, pas de snapshot inconclusif, et aucun signal de vieille source evidente.

Mais V0 n'est pas encore meilleur que l'app actuelle sur ce panel. Les 17 cas `app_better` pointent trois chantiers:

- `unsafe_auto_commit`: la policy V0 commit certains swaps planning que l'app met en confirmation.
- `missed_pending`: le replay comparatif ne materialise pas encore assez bien les pending confirmations existantes.
- `unhelpful_no_send`: V0 reste parfois muet ou trop generique sur des tours sociaux ou semi-actionnables.

Conclusion: la prochaine decision n'est pas provider-first. Elle est runtime/policy/adapter-first.

## Suite

Avant dogfood Telegram, traiter en priorite:

1. Durcir la policy sur les swaps et operations planning multi-seances.
2. Ameliorer l'adapter de replay pour les pending confirmations reelles.
3. Reduire les `no_send` inutiles sans autoriser de fausse mutation.
4. Relancer cette comparaison sur le meme panel pour verifier la regression.

