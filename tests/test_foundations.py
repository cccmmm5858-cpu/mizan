import concurrent.futures
import json
from pathlib import Path
import tempfile
import unittest

from foundations import (ARTICLES, RateLimiter, authenticated, build_prompt,
                         normalize, render_reply, search_articles, validate_chat)


class FoundationsTests(unittest.TestCase):
    def test_required_queries_retrieve_relevant_text(self):
        for query, term, source in [('كفالة', 'الكفالة', 'civil'),
                                    ('واتساب', 'الرقمي', 'ethbat'),
                                    ('إقرار', 'الاقرار', 'ethbat'),
                                    ('مطالبة مالية', 'الدائن', 'civil')]:
            with self.subTest(query=query):
                results = search_articles(query)
                self.assertTrue(results)
                self.assertTrue(any(a['source'] == source and normalize(term) in normalize(a['content']) for a in results))
                self.assertTrue(all(a['id'] for a in results))

    def test_guarantee_definition_is_retrieved(self):
        self.assertTrue(any('الكفالة عقد' in normalize(a['content']) for a in search_articles('كفالة')))

    def test_digital_correspondence_is_retrieved(self):
        self.assertTrue(any('المراسلات الرقمية' in a['content'] for a in search_articles('واتساب')))

    def test_whatsapp_retrieves_digital_evidence_53_55_57(self):
        expected = {'المادة الثالثة والخمسون', 'المادة الخامسة والخمسون',
                    'المادة السابعة والخمسون'}
        for query in ['واتساب', 'وَاتْسَاب']:
            results = search_articles(query)
            titles = {a['title'] for a in results if a['source'] == 'ethbat'}
            self.assertTrue(expected <= titles, expected - titles)
            self.assertEqual(results, search_articles(query, articles=list(reversed(ARTICLES))))

    def test_identity_and_ranking_independent_of_array_order(self):
        self.assertEqual(search_articles('كفالة'), search_articles('كفالة', articles=list(reversed(ARTICLES))))
        self.assertEqual(len(ARTICLES), len({a['id'] for a in ARTICLES}))

    def test_no_results_and_normalization(self):
        self.assertEqual(search_articles('zzzzzzzz'), [])
        self.assertEqual(search_articles('إِقْرَار'), search_articles('اقرار'))
        self.assertEqual(search_articles(None), [])

    def test_auth_fails_closed(self):
        token = 't' * 32
        for header, expected in [(None, token), ('Bearer x', token), ('Bearer ', ''), ('Bearer short', 'short')]:
            self.assertFalse(authenticated(header, expected))
        self.assertTrue(authenticated('Bearer ' + token, token))

    def test_canonical_case_and_server_owned_query(self):
        messages = [{'role': 'user', 'content': 'كفالة'}]
        self.assertEqual(validate_chat(dict(messages=messages, case_type='financial', query='إقرار')), (messages, 'كفالة'))
        for case in ['f', 'p', 'personal', 'unknown']:
            with self.assertRaises(ValueError):
                validate_chat(dict(messages=messages, case_type=case))

    def test_attachments_and_malformed_messages_are_rejected(self):
        cases = [None, [], {}, {'messages': 'bad'}, {'messages': [{'role': 'system', 'content': 'x'}]},
                 {'messages': [{'role': 'user', 'content': [{'type': 'image'}]}]},
                 {'messages': [{'role': 'user', 'content': 'x' * 6001}]},
                 {'messages': [{'role': 'user', 'content': 'x'}], 'files': ['x.pdf']}]
        for data in cases:
            with self.subTest(data=str(data)[:60]), self.assertRaises(ValueError):
                validate_chat(data)

    def test_citations_are_rendered_verbatim_from_retrieval(self):
        found = search_articles('كفالة')
        raw = json.dumps({'article_ids': [found[0]['id']], 'question_ids': ['amount']})
        reply = render_reply(raw, found)
        self.assertIn(found[0]['content'], reply)
        self.assertIn(found[0]['title'], reply)
        self.assertNotIn('المادة الأولى', build_prompt([]))

    def test_hallucinations_and_injection_fail_closed(self):
        found = search_articles('واتساب')
        for data in [{'article_ids': ['civil:invented'], 'question_ids': []},
                     {'article_ids': [], 'question_ids': [], 'analysis': 'المادة 999'},
                     {'article_ids': [], 'question_ids': ['المادة 999']},
                     {'article_ids': [{'id': 'x'}], 'question_ids': []},
                     {'article_ids': 'x', 'question_ids': []}]:
            with self.assertRaises(ValueError):
                render_reply(json.dumps(data), found)
        self.assertNotIn('المادة الأولى', render_reply('{"article_ids":[],"question_ids":[]}', []))

    def test_rate_limit_shared_across_instances_and_window_reset(self):
        with tempfile.TemporaryDirectory() as temp:
            now = [120]
            path = Path(temp) / 'limits.sqlite3'
            one = RateLimiter(path, 2, 60, lambda: now[0])
            two = RateLimiter(path, 2, 60, lambda: now[0])
            self.assertTrue(one.allow('user'))
            self.assertTrue(two.allow('user'))
            self.assertFalse(one.allow('user'))
            now[0] = 180
            self.assertTrue(two.allow('user'))

    def test_rate_limit_atomic_under_concurrency(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'limits.sqlite3'
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
                results = list(pool.map(lambda _: RateLimiter(path, 3).allow('user'), range(15)))
            self.assertEqual(sum(results), 3)


if __name__ == '__main__':
    unittest.main()
