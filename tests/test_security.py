import concurrent.futures
import copy
import hashlib
import json
import math
import random
import unittest
from unittest.mock import patch

from e04 import core


class IngestionRegressions(unittest.TestCase):
    def test_constructor_validation(self):
        for size in (0, -1, 31, 8193, True, 32.5, '500', None):
            with self.subTest(size=size), self.assertRaises(ValueError):
                core.KnowledgeIndex(size)

    def test_chunk_policy_is_read_only(self):
        index = core.KnowledgeIndex()
        with self.assertRaises(AttributeError):
            index.chunk_chars = 1

    def test_failed_input_does_not_reserve_id(self):
        index = core.KnowledgeIndex()
        with self.assertRaises(TypeError):
            index.ingest('doc', None, 'source')
        self.assertEqual(index.doc_ids, set())
        self.assertTrue(index.ingest('doc', 'valid text', 'source'))

    def test_input_shapes(self):
        for args in ((None, 'text', 'source'), ('', 'text', 'source'), (' x', 'text', 'source'),
                     ('doc', 'text', ''), ('doc', 'text', 'line\nbreak'), ('doc', b'text', 'source')):
            with self.subTest(args=args), self.assertRaises((ValueError, TypeError)):
                core.KnowledgeIndex().ingest(*args)

    def test_unicode_and_byte_bounds(self):
        index = core.KnowledgeIndex()
        for value in ('\ud800', 'x'*(core.MAX_DOCUMENT_BYTES+1)):
            with self.assertRaises(ValueError):
                index.ingest('doc', value, 'source')
        self.assertEqual(index.doc_ids, set())

    def test_corpus_limit_is_atomic(self):
        index = core.KnowledgeIndex()
        index.ingest('a', 'alpha', 'source')
        before = index.verify()['index_digest']
        with patch.object(core, 'MAX_CORPUS_BYTES', 8):
            with self.assertRaises(ValueError):
                index.ingest('b', 'bravo', 'source')
        self.assertEqual(index.verify()['index_digest'], before)
        self.assertEqual(index.doc_ids, {'a'})

    def test_document_count_limit_is_atomic(self):
        index = core.KnowledgeIndex()
        index.ingest('a', '', 'source')
        with patch.object(core, 'MAX_DOCUMENTS', 1):
            with self.assertRaises(ValueError):
                index.ingest('b', '', 'source')
        self.assertEqual(index.doc_ids, {'a'})

    def test_chunk_and_token_limits_are_atomic(self):
        for name, cap in (('MAX_CHUNKS', 1), ('MAX_INDEXED_TOKENS', 2)):
            index = core.KnowledgeIndex(32)
            with patch.object(core, name, cap):
                with self.assertRaises(ValueError):
                    index.ingest('doc', 'alpha bravo charlie '*10, 'source')
            self.assertEqual(index.doc_ids, set())

    def test_long_paragraph_chunks_are_bounded_exact_slices(self):
        source = 'alpha bravo charlie delta '*100
        index = core.KnowledgeIndex(40)
        index.ingest('doc', source, 'source')
        for chunk in index.chunks.values():
            start, end = chunk['provenance']['characters']
            self.assertEqual(source[start:end], chunk['text'])
            self.assertLessEqual(len(chunk['text']), 40)
            self.assertEqual(chunk['provenance']['paragraphs'], [0, 0])

    def test_combination_counts_actual_separator_width(self):
        index = core.KnowledgeIndex(32)
        index.ingest('doc', 'a'*15+'\n\n'+'b'*16, 'source')
        self.assertEqual(len(index.chunks), 2)

    def test_crlf_is_not_a_paragraph_break_by_itself(self):
        index = core.KnowledgeIndex(100)
        index.ingest('doc', 'alpha\r\nbravo\r\n\r\ncharlie', 'source')
        chunk = next(iter(index.chunks.values()))
        self.assertEqual(chunk['provenance']['paragraphs'], [0, 1])

    def test_hard_split_word_does_not_create_false_tokens(self):
        index = core.KnowledgeIndex(32)
        index.ingest('doc', 'a'*40+' beta', 'source')
        self.assertNotIn('a'*32, index.postings)
        self.assertNotIn('a'*8, index.postings)
        self.assertEqual(index.query('beta')['total_matches'], 1)
        self.assertEqual(index.verify()['statistics']['unindexed_long_or_split_tokens'], 1)

    def test_long_tokens_ignored_with_diagnostics(self):
        index = core.KnowledgeIndex()
        index.ingest('doc', 'a'*129+' beta', 'source')
        self.assertEqual(index.query('a'*129)['ignored_long_query_tokens'], 1)
        self.assertEqual(index.verify()['statistics']['unindexed_long_or_split_tokens'], 1)

    def test_public_views_do_not_mutate_internal_state(self):
        index = core.KnowledgeIndex()
        index.ingest('doc', 'alpha beta', 'source')
        index.chunks.clear()
        index.postings['alpha'].clear()
        index.doc_lengths['doc#c0'] = 999
        index.doc_ids.clear()
        self.assertEqual(index.verify()['verdict'], 'PASS')
        self.assertEqual(index.query('alpha')['total_matches'], 1)

    def test_parallel_unique_ingestion_is_atomic(self):
        index = core.KnowledgeIndex()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: index.ingest(f'doc{i}', 'alpha beta', 'source'), range(20)))
        self.assertEqual(len(index.doc_ids), 20)
        self.assertEqual(index.verify()['verdict'], 'PASS')

    def test_parallel_duplicate_ingestion_only_one_wins(self):
        index = core.KnowledgeIndex()
        def attempt(_):
            try:
                index.ingest('same', 'alpha beta', 'source')
                return True
            except ValueError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(attempt, range(8))), 1)


class RetrievalRegressions(unittest.TestCase):
    def build(self):
        index = core.KnowledgeIndex()
        index.ingest('a', 'alpha alpha beta', 'one')
        index.ingest('b', 'alpha gamma', 'two')
        return index

    def test_bm25_arithmetic_recomputes_from_exposed_values(self):
        answer = self.build().query('alpha beta')
        config = answer['bm25']
        for result in answer['results']:
            parts = []
            for part in result['arithmetic']:
                idf = math.log1p((config['chunks']-part['df']+0.5)/(part['df']+0.5))
                score = idf*(part['tf']*(config['k1']+1))/(part['tf']+config['k1']*(1-config['b']+config['b']*part['document_length']/config['average_length']))
                self.assertAlmostEqual(score, part['component'], places=15)
                parts.append(part['component'])
            self.assertEqual(result['score'], math.fsum(parts))
            self.assertEqual(result['display_score'], round(result['score'], 4))

    def test_repeated_query_terms_do_not_change_scores(self):
        index = self.build()
        self.assertEqual(index.query('alpha beta')['results'], index.query('beta alpha alpha')['results'])

    def test_insertion_order_does_not_change_ranking_or_index_digest(self):
        left, right = core.KnowledgeIndex(), core.KnowledgeIndex()
        for name in ('a', 'b', 'c'):
            left.ingest(name, 'alpha beta', name)
        for name in ('c', 'b', 'a'):
            right.ingest(name, 'alpha beta', name)
        self.assertEqual(left.query('alpha'), right.query('alpha'))

    def test_unmatched_terms_are_unique_and_sorted(self):
        self.assertEqual(self.build().query('zebra unknown zebra')['unmatched_terms'], ['unknown', 'zebra'])

    def test_whole_ascii_words_not_substrings_of_unicode_or_identifiers(self):
        self.assertEqual(core.tokenize('café alpha_beta pi ALPHA 42'), ['pi', 'alpha', '42'])

    def test_snippet_anchors_to_word_not_substring(self):
        source = 'engines '+('padding '*35)+'engine word'
        index = core.KnowledgeIndex(1000)
        index.ingest('doc', source, 'source')
        result = index.query('engine')['results'][0]
        start, end = result['snippet_characters']
        self.assertGreater(start, 0)
        self.assertIn('engine word', source[start:end])
        self.assertEqual(result['snippet'].strip('…'), source[start:end])

    def test_long_match_fits_snippet(self):
        token = 'a'*128
        index = core.KnowledgeIndex(1000)
        index.ingest('doc', 'prefix '*20+token+' suffix '*20, 'source')
        self.assertIn(token, index.query(token)['results'][0]['snippet'])

    def test_citations_bind_exact_source_and_chunk(self):
        source = '  alpha beta\r\n\r\ngamma  '
        index = core.KnowledgeIndex()
        index.ingest('doc', source, 'source')
        citation = index.query('gamma')['results'][0]['citation']
        start, end = citation['characters']
        self.assertEqual(citation['chunk_digest'], core._digest(source[start:end]))
        self.assertEqual(citation['document_digest'], core._digest(source))
        self.assertEqual(citation['paragraphs'], [0, 1])

    def test_mutated_answer_does_not_change_future_results(self):
        index = self.build()
        original = index.query('alpha')
        result = copy.deepcopy(original)
        result['results'][0]['arithmetic'][0]['tf'] = 1000
        result['results'][0]['citation']['characters'][0] = 999
        self.assertEqual(index.query('alpha'), original)

    def test_answer_digest_binds_payload(self):
        answer = self.build().query('alpha')
        digest = answer.pop('answer_digest')
        self.assertEqual(digest, core._record_digest(answer))

    def test_empty_index_and_stopwords(self):
        for query in ('', 'the and', 'unknown'):
            answer = core.KnowledgeIndex().query(query)
            self.assertEqual(answer['results'], [])
            self.assertEqual(answer['bm25']['average_length'], 0)

    def test_zero_limit_and_upper_limit(self):
        index = self.build()
        answer = index.query('alpha', 0)
        self.assertEqual(answer['results'], [])
        self.assertEqual(answer['total_matches'], 2)
        with self.assertRaises(ValueError):
            index.query('alpha', 101)

    def test_query_type_byte_and_term_limits(self):
        index = self.build()
        with self.assertRaises(TypeError):
            index.query(None)
        for value in ('a'*(core.MAX_QUERY_CHARS+1), ' '.join('term'+str(i) for i in range(65))):
            with self.assertRaises(ValueError):
                index.query(value)


class IntegrityRegressions(unittest.TestCase):
    def build(self):
        index = core.KnowledgeIndex()
        index.ingest('doc', 'alpha beta', 'source')
        return index

    def test_length_tampering_detected_and_queries_refused(self):
        index = self.build()
        index._state['doc_lengths']['doc#c0'] = 999
        self.assertFalse(index.verify()['lengths_consistent'])
        with self.assertRaises(core.IntegrityError):
            index.query('alpha')

    def test_provenance_tampering_detected(self):
        for key, value in (('source', 'changed'), ('paragraphs', [99, 99]), ('characters', [9, 10])):
            index = self.build()
            index._state['chunks']['doc#c0']['provenance'][key] = value
            self.assertEqual(index.verify()['verdict'], 'FAIL')

    def test_document_registry_tampering_detected(self):
        index = self.build()
        index._state['documents']['doc']['source'] = 'changed'
        self.assertEqual(index.verify()['verdict'], 'FAIL')

    def test_config_and_statistics_tampering_detected(self):
        for field in ('config', 'statistics'):
            index = self.build()
            index._state[field] = {}
            self.assertEqual(index.verify()['verdict'], 'FAIL')

    def test_malformed_state_returns_fail(self):
        for field, value in (('chunks', None), ('postings', {'alpha': None}), ('documents', []), ('doc_lengths', None)):
            index = self.build()
            index._state[field] = value
            self.assertEqual(index.verify()['verdict'], 'FAIL')

    def test_ingestion_refuses_corrupt_prior_state(self):
        index = self.build()
        index._state['postings']['alpha']['doc#c0'] = 999
        with self.assertRaises(core.IntegrityError):
            index.ingest('other', 'gamma', 'source')
        self.assertEqual(index.doc_ids, {'doc'})

    def test_seeded_chunk_provenance_and_integrity(self):
        randomizer = random.Random(24001)
        for size in (32, 40, 80, 120):
            index = core.KnowledgeIndex(size)
            source = '\n\n'.join(' '.join(randomizer.choices(['alpha', 'beta', 'gamma', 'delta'], k=50)) for _ in range(8))
            index.ingest('doc', source, 'source')
            self.assertEqual(index.verify()['verdict'], 'PASS')
            for chunk in index.chunks.values():
                a, b = chunk['provenance']['characters']
                self.assertEqual(chunk['text'], source[a:b])
                self.assertLessEqual(b-a, size)
