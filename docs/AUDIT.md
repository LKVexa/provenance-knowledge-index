# Audit and hardening — 0.1.2a1

Date: 2026-09-23. Source: JY-S024-P001 / 0.1.1-partial / run-0001 / product.
Reviewed ingestion, chunk provenance, tokenization, scoring, snippets and integrity.
Original source remains separate from this release checkout.

## Repaired findings

- IDs were reserved before ingestion could fail, and mutations were not atomic.
  Input validation plus prospective state construction now precede a locked
  commit; failed limits leave the registry/index unchanged.
- Single long paragraphs bypassed chunk_chars and grouping ignored separator
  length. Exact source spans and bounded splitting/grouping enforce the cap.
  Hard-split words are omitted instead of indexing false word fragments.
- Public mutable dictionaries allowed callers to corrupt text, postings and
  lengths. Public access now returns detached snapshots, with locked operations.
- Integrity omitted document registry, lengths, source labels and paragraph spans.
  Reconstruction from retained source now checks every derived structure plus
  configuration/statistics and a state digest. Corrupt state refuses queries.
- Repeated query terms multiplied scores without an explicit policy; terms now
  deduplicate and sort. Four-decimal component rounding affected ranking; full-
  precision components/math.fsum drive ranking and display rounding is separate.
  All BM25 inputs needed to recompute each score are exposed.
- Substring snippet matching could anchor to an unrelated larger word. Snippets
  now anchor to an indexed whole token and cite exact source character spans.
- Input, corpus, token and query budgets were absent. Strict types/Unicode,
  immutable chunk policy, registry/chunk/token caps and bounded results now apply.

## Verification and release

15 baseline tests passed. 51 source and installed-wheel tests pass after changes,
including 36 new regressions for atomicity, concurrency, exact source slices,
hard word splits, CRLF, scoring, determinism, bounds and state/provenance corruption.
The inherited score test now uses full precision; two integrity fixtures deliberately
corrupt private state because public mappings are detached. The inherited no-I/O
spy test remains intact. Test success does not authenticate indexed source claims.

CHECK_RUNS.json records current tests; BASELINE_CHECK_RUNS.json preserves original
evidence. CI covers Linux Python 3.10/3.12/3.14 and Windows Python 3.12. No throughput
benchmark or formal platform qualification is claimed. Candidate rebuild/check
cost is documented instead of claiming large-scale search performance.

Version 0.1.1-partial -> 0.1.2a1; answer schema v1 -> v2. README documents changed
tokens/chunk IDs, deduplicated query terms, score/display separation and snapshot
views. Added packaging, pinned-action CI, README, security guidance and Apache 2.0
LICENSE/NOTICE naming RUSSELL PHILIP SMITHSON. No third-party code is vendored or
runtime dependency needs upgrading; no build-tool vulnerability scan is claimed.
The original 752-item certification program and semantic/persistence breadth remain open.
