"""Bounded in-memory lexical retrieval with source provenance and BM25 details.

No I/O, embeddings, authentication or factual-answer generation is performed.
"""
from __future__ import annotations
from collections import Counter
import copy
import hashlib
import json
import math
import re
import threading

VERSION = "0.1.2a1"
K1, B = 1.5, 0.75
MAX_DOCUMENT_BYTES = 256 * 1024
MAX_CORPUS_BYTES = 8 * 1024 * 1024
MAX_DOCUMENTS = 250
MAX_CHUNKS = 10000
MAX_INDEXED_TOKENS = 250000
MAX_TOKEN_CHARS = 128
MAX_QUERY_CHARS = 4096
MAX_QUERY_TERMS = 64
MAX_RESULTS = 100
_TOKEN = re.compile(r"(?<!\w)[A-Za-z0-9]{2,}(?!\w)")
_STOP = frozenset({"the", "a", "an", "and", "or", "of", "to", "in", "is", "it",
    "for", "on", "as", "at", "by", "be", "this", "that", "with"})
_NEWLINE = r"(?:\r?\n|\r(?!\n))"
_PARAGRAPH_BREAK = re.compile(_NEWLINE + r"[ \t]*" + _NEWLINE)


class IntegrityError(ValueError):
    """Internal index state does not match its source and derived structures."""


def _digest(text):
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _record_digest(value):
    return _digest(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False))


def _text(value, name, limit, nonempty=False):
    if type(value) is not str:
        raise TypeError(name + " must be a string")
    if len(value) > limit:
        raise ValueError(name + " exceeds its byte budget")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError as exc:
        raise ValueError(name + " contains invalid Unicode") from exc
    if size > limit or (nonempty and not value.strip()):
        raise ValueError(name + " is empty or outside its byte budget")
    return size


def _label(value, name, limit):
    _text(value, name, limit, nonempty=True)
    if value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(name + " must be a trimmed single-line label")


def _token_spans(text):
    return [(m.start(), m.end(), m[0].lower()) for m in _TOKEN.finditer(text)
            if len(m[0]) <= MAX_TOKEN_CHARS and m[0].lower() not in _STOP]


def tokenize(text):
    _text(text, "text", MAX_DOCUMENT_BYTES)
    return [term for _, _, term in _token_spans(text)]


def _paragraph_spans(text):
    spans, cursor = [], 0
    for end, next_start in [(m.start(), m.end()) for m in _PARAGRAPH_BREAK.finditer(text)] + [(len(text), len(text))]:
        value = text[cursor:end]
        start = cursor + len(value) - len(value.lstrip())
        stop = end - (len(value) - len(value.rstrip()))
        if start < stop:
            spans.append((start, stop))
        cursor = next_start
    return spans


def _chunk_spans(text, size):
    pieces = []
    for paragraph, (start, stop) in enumerate(_paragraph_spans(text)):
        while start < stop:
            end = min(start + size, stop)
            if end < stop:
                # Prefer whitespace in the latter half; hard splits are still
                # bounded and never turn partial words into indexed terms.
                boundary = next((p for p in range(end-1, start+size//2-1, -1) if text[p].isspace()), None)
                if boundary is not None:
                    end = boundary + 1
            if pieces and end - pieces[-1][0] <= size:
                pieces[-1] = (pieces[-1][0], end, pieces[-1][2], paragraph)
            else:
                pieces.append((start, end, paragraph, paragraph))
            if len(pieces) > MAX_CHUNKS:
                raise ValueError("chunk budget exceeded")
            start = end
    return pieces


def _document(doc_id, text, source):
    _label(doc_id, "doc_id", 128)
    _label(source, "source", 2048)
    _text(text, "document", MAX_DOCUMENT_BYTES)
    record = {"doc_id": doc_id, "text": text, "source": source, "document_digest": _digest(text)}
    record["record_digest"] = _record_digest(record)
    return record


def _build(documents, chunk_chars):
    if type(chunk_chars) is not int or not 32 <= chunk_chars <= 8192:
        raise ValueError("invalid chunk configuration")
    if type(documents) is not dict or len(documents) > MAX_DOCUMENTS:
        raise ValueError("document registry outside budget")
    chunks, postings, lengths = {}, {}, {}
    total_bytes, total_tokens, unindexed = 0, 0, 0
    for doc_id in sorted(documents):
        document = documents[doc_id]
        if type(document) is not dict:
            raise ValueError("invalid document record")
        expected = _document(doc_id, document["text"], document["source"])
        if document != expected:
            raise ValueError("document metadata or digest mismatch")
        text = document["text"]
        total_bytes += len(text.encode("utf-8"))
        if total_bytes > MAX_CORPUS_BYTES:
            raise ValueError("corpus byte budget exceeded")
        tokens = _token_spans(text)
        token_index, indexed_here = 0, 0
        for number, (start, end, first, last) in enumerate(_chunk_spans(text, chunk_chars)):
            if len(chunks) >= MAX_CHUNKS:
                raise ValueError("chunk budget exceeded")
            chunk_id = f"{doc_id}#c{number}"
            frequencies = Counter()
            while token_index < len(tokens) and tokens[token_index][0] < end:
                left, right, term = tokens[token_index]
                if left >= start and right <= end:
                    frequencies[term] += 1
                token_index += 1
            count = sum(frequencies.values())
            indexed_here += count
            total_tokens += count
            if total_tokens > MAX_INDEXED_TOKENS:
                raise ValueError("indexed-token budget exceeded")
            piece = text[start:end]
            chunk = {"chunk_id": chunk_id, "doc_id": doc_id, "text": piece,
                "provenance": {"source": document["source"], "paragraphs": [first, last],
                    "characters": [start, end], "chunk_digest": _digest(piece),
                    "document_digest": document["document_digest"], "document_record_digest": document["record_digest"]}}
            chunk["record_digest"] = _record_digest(chunk)
            chunks[chunk_id] = chunk
            lengths[chunk_id] = count
            for term, frequency in frequencies.items():
                postings.setdefault(term, {})[chunk_id] = frequency
        unindexed += len(tokens) - indexed_here + sum(len(m[0]) > MAX_TOKEN_CHARS for m in _TOKEN.finditer(text))
    return {"documents": documents, "chunks": chunks, "postings": postings, "doc_lengths": lengths,
        "config": {"chunk_chars": chunk_chars, "k1": K1, "b": B, "tokenizer": "whole-ascii-alphanumeric-v2"},
        "statistics": {"source_bytes": total_bytes, "indexed_tokens": total_tokens,
                       "unindexed_long_or_split_tokens": unindexed}}


class KnowledgeIndex:
    def __init__(self, chunk_chars=500):
        if type(chunk_chars) is not int or not 32 <= chunk_chars <= 8192:
            raise ValueError("chunk_chars must be an integer in 32..8192")
        self._chunk_chars = chunk_chars
        self._lock = threading.RLock()
        self._state = _build({}, chunk_chars)
        self._seal = _record_digest(self._state)

    @property
    def chunk_chars(self):
        return self._chunk_chars

    @property
    def chunks(self):
        with self._lock:
            return copy.deepcopy(self._state["chunks"])

    @property
    def postings(self):
        with self._lock:
            return copy.deepcopy(self._state["postings"])

    @property
    def doc_lengths(self):
        with self._lock:
            return dict(self._state["doc_lengths"])

    @property
    def doc_ids(self):
        with self._lock:
            return set(self._state["documents"])

    def _verify_locked(self):
        try:
            expected = _build(self._state["documents"], self._chunk_chars)
            current = _record_digest(self._state)
            chunks = self._state["chunks"]
            postings = self._state["postings"]
            bad_chunks = sorted(cid for cid in set(chunks) | set(expected["chunks"])
                if chunks.get(cid) != expected["chunks"].get(cid))
            orphan = sorted({cid for posting in postings.values() for cid in posting} - set(chunks))
            consistent = postings == expected["postings"]
            lengths = self._state["doc_lengths"] == expected["doc_lengths"]
            ok = current == self._seal and self._state == expected
            return {"chunks": len(chunks), "terms": len(postings), "documents": len(expected["documents"]),
                "tampered_chunks": bad_chunks, "orphan_postings": orphan, "postings_consistent": consistent,
                "lengths_consistent": lengths, "index_digest": current, "seal_matches": current == self._seal,
                "statistics": dict(expected["statistics"]), "malformed": [], "verdict": "PASS" if ok else "FAIL"}
        except (TypeError, ValueError, KeyError, AttributeError, RecursionError):
            return {"verdict": "FAIL", "malformed": ["index state is invalid"], "index_digest": None,
                "tampered_chunks": [], "orphan_postings": [], "postings_consistent": False,
                "lengths_consistent": False, "seal_matches": False}

    def verify(self):
        with self._lock:
            return self._verify_locked()

    def _require_integrity(self):
        report = self._verify_locked()
        if report["verdict"] != "PASS":
            raise IntegrityError("index integrity failed; rebuild from trusted source documents")

    def ingest(self, doc_id, text, source):
        document = _document(doc_id, text, source)
        with self._lock:
            self._require_integrity()
            if doc_id in self._state["documents"]:
                raise ValueError("document ID already exists; use an explicit versioned ID")
            documents = dict(self._state["documents"])
            documents[doc_id] = document
            prospective = _build(documents, self._chunk_chars)
            seal = _record_digest(prospective)
            self._state, self._seal = prospective, seal
            return [cid for cid, chunk in prospective["chunks"].items() if chunk["doc_id"] == doc_id]

    def query(self, question, limit=5):
        _text(question, "question", MAX_QUERY_CHARS)
        if type(limit) is not int or not 0 <= limit <= MAX_RESULTS:
            raise ValueError("limit must be an integer in 0..100")
        terms = sorted(set(tokenize(question)))
        if len(terms) > MAX_QUERY_TERMS:
            raise ValueError("query term budget exceeded")
        with self._lock:
            self._require_integrity()
            chunks, postings, lengths = self._state["chunks"], self._state["postings"], self._state["doc_lengths"]
            count = len(chunks)
            average = sum(lengths.values()) / count if count else 0.0
            scores = {}
            for term in terms:
                posting = postings.get(term, {})
                if not posting:
                    continue
                frequency = len(posting)
                idf = math.log1p((count - frequency + 0.5) / (frequency + 0.5))
                for chunk_id, tf in posting.items():
                    length = lengths[chunk_id]
                    component = idf * tf * (K1+1) / (tf + K1*(1-B+B*length/average))
                    scores.setdefault(chunk_id, []).append({"term": term, "tf": tf, "df": frequency,
                        "idf": idf, "document_length": length, "component": component})
            ranked = sorted(((math.fsum(part["component"] for part in parts), cid, parts)
                             for cid, parts in scores.items()), key=lambda row: (-row[0], row[1]))
            results = []
            for score, chunk_id, parts in ranked[:limit]:
                chunk = chunks[chunk_id]
                matched = [part["term"] for part in parts]
                document = self._state["documents"][chunk["doc_id"]]
                snippet, span = _snippet(document["text"], chunk["provenance"]["characters"], set(matched))
                results.append({"chunk_id": chunk_id, "score": score, "display_score": round(score, 4),
                    "arithmetic": parts, "matched_terms": matched, "snippet": snippet, "snippet_characters": span,
                    "citation": {**copy.deepcopy(chunk["provenance"]), "doc_id": chunk["doc_id"],
                                 "chunk_record_digest": chunk["record_digest"]}})
            answer = {"schema": "e04/answer/v2", "engine_version": VERSION, "question": question, "limit": limit,
                "query_terms": terms, "results": results, "total_matches": len(ranked),
                "unmatched_terms": [term for term in terms if term not in postings],
                "ignored_long_query_tokens": sum(len(m[0]) > MAX_TOKEN_CHARS for m in _TOKEN.finditer(question)),
                "bm25": {"k1": K1, "b": B, "chunks": count, "average_length": average,
                         "repeated_query_terms": "deduplicated"},
                "index_digest": self._seal, "answered_from_index_only": True,
                "note": "lexical matches from supplied index text; source claims and authority are not verified"}
            answer["answer_digest"] = _record_digest(answer)
            return answer


def _snippet(text, span, terms, width=160):
    left, right = span
    match = None
    for candidate in _TOKEN.finditer(text, left):
        if candidate.start() >= right:
            break
        if candidate.end() <= right and candidate[0].lower() in terms:
            match = candidate
            break
    position, end = (match.start(), match.end()) if match else (left, left)
    start = max(left, position - width//4, end-width)
    stop = min(right, start+width)
    return (("…" if start > left else "") + text[start:stop] + ("…" if stop < right else ""), [start, stop])
