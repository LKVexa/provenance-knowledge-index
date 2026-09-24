# 0.1.2a1 — 2026-09-23

- Validate and atomically commit bounded document ingestion under a lock.
- Preserve exact source/chunk spans and omit hard-split token fragments.
- Return detached index views and verify all source/derived state before queries.
- Expose full BM25 arithmetic, deduplicate query terms and anchor whole-word snippets.
- Add provenance/answer digests, 36 regressions, packaging and CI.
- Include README and Apache 2.0 LICENSE/NOTICE; original certifications remain open.

# Changelog — E04 Indexed Knowledge Retrieval (JY-S024-P001)

## 0.1.1-partial (2026-09-14)

Baseline fingerprint: build-0001 product.zip sha256
`706a741552eeaea70d651f228fafc9d55c601fba4fb027824b19b80dc965330d` (version 0.1.0-partial, 12/12 tests passing).
Maintenance repairs only (patch bump); no capabilities removed.

### A021-F1 — returned citations aliased stored provenance (FIXED)
- Observed (reproduced on baseline): mutating
  `result["citation"]["paragraphs"]` from a query answer mutated the
  index's stored provenance in place ([999, 1] observed), and
  `verify()` still returned PASS — silent index corruption.
- Expected: query answers are value copies; caller mutation never
  touches index state.
- Fix: citations are built as fresh dicts with a copied paragraphs list.

### A021-F2 — negative `limit` silently dropped the best results (FIXED)
- Observed (reproduced on baseline): `query(q, limit=-1)` returned 0
  results where `limit=5` returned 1 — Python slice semantics dropped
  the top-ranked results silently.
- Expected: an invalid limit is rejected with a clear ValueError;
  `limit=0` returns an empty result list.
- Fix: limit validated as a non-negative int (bool rejected).

### A021-F3 — whitespace-only doc bypassed the duplicate-ingest guard (FIXED)
- Observed (reproduced on baseline): ingesting a whitespace-only text
  produced zero chunks, so the doc id was never recorded and a second
  `ingest` with the same id was ACCEPTED, defeating the explicit-
  versioning contract.
- Expected: every ingested doc id is registered; re-ingestion always
  raises ValueError.
- Fix: new `doc_ids` registry populated on every ingest and used for
  the duplicate check.

### Compatibility
- Public API unchanged for all valid inputs; answer schema unchanged
  except citations are now defensive copies. `query` now raises
  ValueError for negative/non-int limits (previously silent wrong
  results). New attribute `KnowledgeIndex.doc_ids`.
- Rollback: restore build-0001 product.zip (706a741552eeaea70d651f228fafc9d55c601fba4fb027824b19b80dc965330d).
