# Legacy pipeline (retired)

This is the original FitMAS pipeline — a deterministic decision/planning brain with the LLM in a
narrow role. It died of deterministic fix-on-fix (see the root `README.md`).

**It is retired.** It is kept here for provenance, not as the product.

- The live core is [`../runtime_v0/`](../runtime_v0/) — the proven, isolated rebuild that runs the
  Telegram coach in production.
- These modules are **no longer the source of truth** for coaching. Only the legacy FastAPI webapp
  still imports them.

Nothing new should be built here.
