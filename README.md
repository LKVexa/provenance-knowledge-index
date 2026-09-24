# Provenance Knowledge Index

**0.1.2a1 — experimental partial candidate, JY-S024-P001 / E04**

A bounded in-memory lexical index with paragraph-aware chunking, BM25 scoring,
source citations and integrity checks. It operates only on supplied text: no
file access, network client, external service or generated factual answer exists.

## Install and use

Python 3.10+; no third-party runtime dependencies.

~~~sh
python -m pip install .
python -m unittest discover -s tests -t .
~~~

~~~python
from e04.core import KnowledgeIndex

index = KnowledgeIndex(chunk_chars=500)
index.ingest("guide-v1", "The ledger stores execution receipts.", "docs/guide.md")
answer = index.query("execution receipts", limit=5)
assert answer["results"][0]["citation"]["doc_id"] == "guide-v1"
assert index.verify()["verdict"] == "PASS"
~~~

## Ingestion and provenance

Each ingestion validates document ID, source label, Unicode, content and corpus
budgets before committing a new state. Failures leave existing state and the
document registry unchanged. IDs are unique, including for empty/whitespace-only
documents; updates require a new explicit versioned ID. There is no delete/update
API or persistence layer.

Paragraphs are separated by blank lines with LF, CRLF or CR line endings. Leading/
trailing paragraph whitespace is excluded from chunks. Grouped chunks retain
the exact intervening source characters. Long paragraphs are split at whitespace
where possible, with a hard character cap otherwise. Original document text is
retained in memory for integrity checks.

Every chunk stores its document ID, source label, zero-based inclusive paragraph
range, zero-based half-open Unicode character range, text digest, document digest,
document-record digest and chunk-record digest. Source labels are opaque caller
claims; they are never fetched or independently verified. Hashes bind content
and provenance metadata but are not signatures or evidence of authorship.

Chunks, postings, document lengths and document IDs are exposed as detached
snapshots. Mutating them does not edit the index. An RLock serializes ingestion,
queries and checks within one process. Integrity checks rebuild chunks, postings
and lengths from stored documents and compare configuration, statistics and a
state digest. Corruption causes queries/ingestion to raise IntegrityError.
Private-field manipulation is not a supported API or a security boundary.

## Lexical retrieval and scoring

Tokens are whole ASCII alphanumeric words of 2..128 characters, lowercased, with
a fixed stopword list. Words embedded in Unicode words or underscore identifiers
are excluded. There is no stemming, fuzzy/semantic matching or multilingual
segmentation. Oversized words and words cut by a hard chunk boundary are not
indexed as misleading fragments; their count is exposed in verify statistics.
Query responses count ignored oversized query tokens separately.

Queries deduplicate and sort terms, so repeated words do not silently change
weight. Unknown terms are listed once in unmatched_terms; unknown/empty/stopword
queries return zero matches. Results are lexical matches, not synthesized answers.
answered_from_index_only is retained for compatibility and means only that
reported matches come from supplied indexed text.

BM25 uses k1=1.5 and b=0.75. For each matched term, idf is
log(1 + (N-df+0.5)/(df+0.5)) and the component is
idf * tf * (k1+1) / (tf + k1*(1-b+b*dl/avgdl)). N is the chunk count, df the
number of matching chunks, dl the chunk's indexed-token count, and avgdl the
mean over all chunks. Reports expose those values and full-precision components.
score is math.fsum of components; display_score alone rounds to four decimals.
Ranking uses the full score, then chunk ID for deterministic ties. Floating-point
arithmetic is deterministic within the tested runtime envelope, not exact rational math.

Snippets are at most 160 source characters plus ellipsis markers and are anchored
to an actual whole-token match. snippet_characters cites the underlying source
span before ellipses. A citation covers the full indexed chunk; a short snippet
does not necessarily contain every query term or all surrounding context.

Answer schema e04/answer/v2 includes query terms, limit, total_matches, BM25
configuration, index digest, citations and an answer digest binding the response.
Returned structures are detached. Digests are unsigned consistency/correlation
values; a caller can fabricate and rehash data. They do not authenticate source
claims or make retrieved text safe to execute or follow as instructions.

## Budgets and performance

chunk_chars is an immutable integer in 32..8192 (default 500). Document IDs are
trimmed, control-free labels up to 128 UTF-8 bytes; source labels up to 2,048.
Each document is at most 256 KiB UTF-8. The corpus is capped at 250 documents,
8 MiB source text, 10,000 chunks and 250,000 indexed tokens. All limits apply
together; an earlier bound may be reached first.

Questions are capped at 4,096 UTF-8 bytes and 64 unique indexed query terms.
limit is an integer in 0..100; zero returns no results while retaining match
counts/diagnostics. Invalid types, lone Unicode surrogates and exceeded budgets
raise TypeError/ValueError; booleans are not accepted as numeric configuration.

This prototype rebuilds candidate state during ingestion and checks integrity
before each query. That favors reviewability over large-corpus throughput and
costs work proportional to stored source/index size. It is not a production
search service, persistent database, multitenant authorization layer or OS
resource sandbox. Inputs/results can contain private text; manage access and
retention in the caller and escape text in downstream rendering.

## Verification and migration

51 tests: 15 inherited checks and 36 new regressions, covering atomic failure,
concurrent ingestion, strict bounds, exact chunk/snippet spans, full scoring
arithmetic, duplicate query terms, source metadata and derived-state corruption.
Source and installed-wheel results: [CHECK_RUNS](docs/CHECK_RUNS.json). CI covers
Linux Python 3.10/3.12/3.14 and Windows 3.12. See [AUDIT](docs/AUDIT.md) and
[SECURITY](SECURITY.md).

0.1.1-partial -> 0.1.2a1 changes tokenization, strict chunk bounds, answer schema,
full-precision scores and repeated-query handling. Chunk IDs/ranking can change
after rebuilding; rebuild from source rather than relying on prior positional IDs.
Public dictionaries are now snapshots. Existing score consumers should use
display_score for four-decimal display and score for ranking/recomputation.

The original 752-item certification program, embeddings/semantic retrieval,
durable persistence, governance integrations and formal platform qualification
remain outside this partial candidate.

## License

Copyright 2026 **RUSSELL PHILIP SMITHSON**.
[Apache License 2.0](LICENSE), with [NOTICE](NOTICE).
No third-party source is vendored; see [THIRD-PARTY-NOTICES](THIRD-PARTY-NOTICES.md).
