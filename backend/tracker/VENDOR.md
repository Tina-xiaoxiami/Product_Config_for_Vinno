# Release workbench provenance

- Source repository: `Tina-xiaoxiami/product-management`
- Source branch: `codex/preview-match-navigation`
- Vendored commit: `68dc759`
- Preview navigation implementation: `56791d6`

Only the tracked `tracker/` runtime package is vendored. Runtime databases,
local configuration, source documents, outputs, and other business data are not
copied into this repository.

## Local automatic feature descriptions (2026-10-30)

- The query page's **API 设置** stores separate DeepSeek/OpenAI profiles at
  `~/.config/vinno-product-config/model.json` (0600; keys are never returned to the UI).
  The private-profile implementation is adapted from the separate guide app's
  `guidelines.model.ModelSettings`; that checkout is not a runtime dependency.
- Feature queries use JSON POST to `/api/v1/workbench/scenario`; GET reads existing
  descriptions without making paid calls. New imported/indexed evidence takes effect
  on the next query. No library-wide or periodic model calls are scheduled.
- SQLite migration 15 adds a derived model cache, an append-only manual revision
  history, and token usage/reservations. The existing database backup includes them.
  Unchanged semantic evidence hits the cache; only new evidence is sent with the
  previous automatic result. Changed/removed evidence rebuilds the automatic result.
- Daily token budgets reset in Asia/Shanghai. Missing usage remains reserved rather
  than being reported as actual usage. Oversized input, budget limits, invalid quotes,
  incomplete replies and provider failures preserve the last good description.
- Source scope, original language and version references remain attached. Every model
  paragraph must quote a verified input verbatim; unbounded context windows cannot
  establish a factual paragraph. This checks provenance, not semantic correctness.
- Manual saves make no model call, detect stale data/revisions, and never overwrite
  automatic evidence, canonical feature records or publication status.
