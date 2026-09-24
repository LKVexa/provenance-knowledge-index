import socket
import math
import unittest

from e04.core import KnowledgeIndex, tokenize

DOC_A = """\
The Merkle ledger stores every execution receipt in an append-only file.

Receipts carry a SHA-256 leaf hash and the current tree root, so any
prefix of the ledger is independently verifiable.

Configuration lives in a JSON file next to the ledger.
"""

DOC_B = """\
The calculator engine evaluates expressions with exact rational
arithmetic and explicit precision for irrational functions.

A loopback server exposes the engine on 127.0.0.1 only.
"""


def build():
    ix = KnowledgeIndex(chunk_chars=120)
    ix.ingest("ledger-doc", DOC_A, "docs/ledger.md")
    ix.ingest("calc-doc", DOC_B, "docs/calc.md")
    return ix


class Ingestion(unittest.TestCase):
    def test_chunking_with_provenance(self):
        ix = build()
        self.assertGreaterEqual(len(ix.chunks), 3)
        for c in ix.chunks.values():
            self.assertTrue(c["provenance"]["chunk_digest"].startswith("sha256:"))
            self.assertIn("paragraphs", c["provenance"])

    def test_duplicate_ingest_rejected(self):
        ix = build()
        with self.assertRaises(ValueError):
            ix.ingest("ledger-doc", "new text", "x")

    def test_tokenizer_drops_stopwords(self):
        self.assertNotIn("the", tokenize("the Merkle tree"))
        self.assertIn("merkle", tokenize("the Merkle tree"))


class Retrieval(unittest.TestCase):
    def setUp(self):
        self.ix = build()

    def test_relevant_chunk_ranks_first_with_citation(self):
        ans = self.ix.query("how are receipts verified in the merkle ledger?")
        top = ans["results"][0]
        self.assertEqual(top["citation"]["doc_id"], "ledger-doc")
        self.assertEqual(top["citation"]["source"], "docs/ledger.md")
        self.assertTrue(set(top["matched_terms"]) & {"receipts", "ledger",
                                                     "merkle", "verifiable"})

    def test_arithmetic_recomputable(self):
        ans = self.ix.query("exact rational arithmetic engine")
        for r in ans["results"]:
            self.assertEqual(r["score"],
                             math.fsum(p["component"] for p in r["arithmetic"]))

    def test_snippet_contains_match(self):
        ans = self.ix.query("loopback server")
        self.assertIn("127.0.0.1", ans["results"][0]["snippet"])

    def test_unmatched_terms_reported_not_hallucinated(self):
        ans = self.ix.query("quantum blockchain llama")
        self.assertIn("llama", ans["unmatched_terms"])
        self.assertTrue(ans["answered_from_index_only"])

    def test_no_results_for_fully_unknown_query(self):
        ans = self.ix.query("zzzz qqqq")
        self.assertEqual(ans["results"], [])

    def test_deterministic(self):
        q = "merkle ledger receipts"
        self.assertEqual(self.ix.query(q), self.ix.query(q))


class Hardening011(unittest.TestCase):
    """Regression tests for 0.1.1-partial fixes (A021-F1..F3)."""

    def setUp(self):
        self.ix = build()

    def test_citation_mutation_does_not_corrupt_index(self):
        # A021-F1: returned citation must not alias stored provenance
        ans = self.ix.query("merkle ledger")
        top = ans["results"][0]
        top["citation"]["paragraphs"][0] = 999
        top["citation"]["source"] = "evil"
        cid = top["chunk_id"]
        prov = self.ix.chunks[cid]["provenance"]
        self.assertNotEqual(prov["paragraphs"][0], 999)
        self.assertNotEqual(prov["source"], "evil")
        self.assertEqual(self.ix.verify()["verdict"], "PASS")

    def test_negative_or_non_int_limit_rejected(self):
        # A021-F2: limit=-1 silently dropped the best results on baseline
        with self.assertRaises(ValueError):
            self.ix.query("merkle ledger", limit=-1)
        with self.assertRaises(ValueError):
            self.ix.query("merkle ledger", limit=True)
        with self.assertRaises(ValueError):
            self.ix.query("merkle ledger", limit="5")
        self.assertEqual(self.ix.query("merkle", limit=0)["results"], [])

    def test_zero_chunk_doc_still_registers_doc_id(self):
        # A021-F3: whitespace-only doc bypassed the duplicate-ingest guard
        ix = KnowledgeIndex()
        self.assertEqual(ix.ingest("doc1", "   \n\n  ", "empty.md"), [])
        with self.assertRaises(ValueError):
            ix.ingest("doc1", "real content now", "v2.md")


class Integrity(unittest.TestCase):
    def test_verify_pass_and_tamper_detection(self):
        ix = build()
        self.assertEqual(ix.verify()["verdict"], "PASS")
        cid = next(iter(ix.chunks))
        ix._state["chunks"][cid]["text"] += " tampered"
        rep = ix.verify()
        self.assertEqual(rep["verdict"], "FAIL")
        self.assertIn(cid, rep["tampered_chunks"])
        self.assertFalse(rep["seal_matches"])

    def test_orphan_posting_detected(self):
        ix = build()
        ix._state["postings"].setdefault("ghost", {})["nope#c0"] = 1
        rep = ix.verify()
        self.assertIn("nope#c0", rep["orphan_postings"])
        self.assertEqual(rep["verdict"], "FAIL")

    def test_no_network_no_files(self):
        import builtins
        opened = []
        real_open, real_socket = builtins.open, socket.socket
        builtins.open = lambda *a, **k: (opened.append(a), real_open(*a, **k))[1]
        socket.socket = lambda *a, **k: (_ for _ in ()).throw(AssertionError)
        try:
            ix = build()
            ix.query("merkle ledger")
            ix.verify()
        finally:
            builtins.open, socket.socket = real_open, real_socket
        self.assertEqual(opened, [])
        import e04.core as m
        for name in dir(m):
            for bad in ("fetch", "http", "download", "requests"):
                self.assertNotIn(bad, name.lower())


if __name__ == "__main__":
    unittest.main()
