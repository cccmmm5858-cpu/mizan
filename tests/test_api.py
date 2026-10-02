import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HAS_DEPENDENCIES = all(importlib.util.find_spec(m) is not None for m in ('flask', 'anthropic'))
if HAS_DEPENDENCIES:
    import app as application
    from foundations import search_articles


@unittest.skipUnless(HAS_DEPENDENCIES, 'Flask/Anthropic packages are not installed')
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = patch.dict(application.app.config, TESTING=True, CHAT_ACCESS_TOKEN='t' * 32,
                                 RATE_LIMIT_DB=str(Path(self.temp.name) / 'rate.sqlite3'), CHAT_RATE_LIMIT=10)
        self.config.start()
        self.addCleanup(self.config.stop)
        self.client = application.app.test_client()
        self.provider = patch('app.anthropic.Anthropic')
        self.mock = self.provider.start()
        self.addCleanup(self.provider.stop)
        found = search_articles('كفالة')
        self.mock.return_value.messages.create.return_value = SimpleNamespace(content=[SimpleNamespace(
            type='text', text=json.dumps({'article_ids': [found[0]['id']], 'question_ids': ['amount']}))])
        self.headers = {'Authorization': 'Bearer ' + 't' * 32}
        self.payload = {'case_type': 'financial', 'messages': [{'role': 'user', 'content': 'كفالة'}]}

    def post(self, payload=None, headers=None):
        return self.client.post('/api/chat', json=self.payload if payload is None else payload,
                                headers=self.headers if headers is None else headers)

    def test_anonymous_and_missing_config_rejected_before_provider(self):
        self.assertEqual(self.post(headers={}).status_code, 401)
        with patch.dict(application.app.config, CHAT_ACCESS_TOKEN=''):
            self.assertEqual(self.post().status_code, 401)
        self.mock.assert_not_called()

    def test_financial_success_has_exact_retrieved_text(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertIn(body['retrieved_articles'][0]['content'], body['reply'])
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.mock.return_value.messages.create.assert_called_once()

    def test_rate_limit_precedes_provider_and_ignores_forwarded_ip(self):
        with patch.dict(application.app.config, CHAT_RATE_LIMIT=1):
            self.assertEqual(self.post().status_code, 200)
            response = self.post(headers=dict(self.headers, **{'X-Forwarded-For': '1.2.3.4'}))
            self.assertEqual(response.status_code, 429)
            self.assertIn('Retry-After', response.headers)
        self.mock.return_value.messages.create.assert_called_once()

    def test_provider_error_is_redacted(self):
        self.mock.return_value.messages.create.side_effect = RuntimeError('secret-api-key provider details')
        response = self.post()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn('secret', response.get_data(as_text=True))

    def test_fabricated_citation_is_rejected(self):
        self.mock.return_value.messages.create.return_value.content[0].text = '{"article_ids":["made-up"],"question_ids":[]}'
        self.assertEqual(self.post().status_code, 503)

    def test_personal_legacy_and_attachments_rejected(self):
        for case in ['p', 'personal', 'f']:
            self.assertEqual(self.post(dict(self.payload, case_type=case)).status_code, 400)
        self.assertEqual(self.post(dict(self.payload, attachments=['file.pdf'])).status_code, 400)
        self.assertEqual(self.post({'messages': [{'role': 'user', 'content': [{'type': 'image'}]}]}).status_code, 400)
        self.mock.assert_not_called()

    def test_malformed_and_oversized_json(self):
        response = self.client.post('/api/chat', data='not-json', content_type='application/json', headers=self.headers)
        self.assertEqual(response.status_code, 400)
        response = self.client.post('/api/chat', data='x' * (129 * 1024), content_type='application/json', headers=self.headers)
        self.assertEqual(response.status_code, 413)
        self.mock.assert_not_called()

    def test_empty_retrieval_does_not_call_provider(self):
        payload = {'messages': [{'role': 'user', 'content': 'zzzzzzzz'}]}
        self.assertEqual(self.post(payload).get_json()['retrieved_articles'], [])
        self.mock.assert_not_called()

    def test_search_and_pagination_validation(self):
        self.assertEqual(self.client.post('/api/search', json=[]).status_code, 400)
        self.assertEqual(self.client.get('/api/articles?per_page=-1').status_code, 400)
        self.assertEqual(self.client.get('/api/articles?page=nope').status_code, 400)
        self.assertTrue(self.client.post('/api/search', json={'query': 'إقرار'}).get_json()['results'])


if __name__ == '__main__':
    unittest.main()
