import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from vncolab import (
    AmbiguousColabPostError, Client, ColabRequestError, TooManyAssignmentsError,
)


class ReadTimeout(Exception):
    pass


class ConnectionError(Exception):
    pass


FAKE_REQUESTS = types.SimpleNamespace(exceptions=types.SimpleNamespace(
    ProxyError=ConnectionError, ConnectionError=ConnectionError, ReadTimeout=ReadTimeout))


class Response:
    def __init__(self, data, status=200):
        self.text = data if isinstance(data, str) else json.dumps(data)
        self.status_code = status
        self.reason = 'OK' if status == 200 else 'Service Unavailable'
        self.ok = status < 400


class FakeSession:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class ColabAssignmentRetryTests(unittest.TestCase):
    def test_active_runtime_blocks_a_new_account_assignment(self):
        client = Client(None)
        client.list_assignments = lambda: [{'endpoint': 'existing'}]
        with self.assertRaisesRegex(TooManyAssignmentsError, 'already active'):
            client.ensure_no_active_assignments()

    def test_post_timeout_reconciles_assignment_without_replaying_token(self):
        existing = {'endpoint': 'runtime.example', 'runtimeProxyInfo': {'token': 'runtime'}}
        session = FakeSession([
            Response({'token': 'one-use-token'}),
            ReadTimeout('assignment response timed out'),
            Response(existing),
        ])
        client = Client(session)

        with patch('vncolab.time.sleep'), patch.dict(sys.modules, {'requests': FAKE_REQUESTS}):
            result = client.assign(accelerator='T4')

        self.assertEqual(result, existing)
        self.assertEqual([call[0] for call in session.calls], ['GET', 'POST', 'GET'])
        self.assertEqual(session.calls[1][2]['headers']['X-Goog-Colab-Token'],
                         'one-use-token')

    def test_post_timeout_uses_fresh_token_only_if_reconciliation_has_no_assignment(self):
        created = {'endpoint': 'runtime.example', 'runtimeProxyInfo': {'token': 'runtime'}}
        session = FakeSession([
            Response({'token': 'first-token'}),
            ReadTimeout('assignment response timed out'),
            Response({'token': 'fresh-token'}),
            Response(created),
        ])
        with patch('vncolab.time.sleep'), patch.dict(sys.modules, {'requests': FAKE_REQUESTS}):
            result = Client(session).assign(accelerator='T4')

        self.assertEqual(result, created)
        self.assertEqual([call[0] for call in session.calls], ['GET', 'POST', 'GET', 'POST'])
        self.assertEqual([call[2]['headers'].get('X-Goog-Colab-Token')
                          for call in session.calls if call[0] == 'POST'],
                         ['first-token', 'fresh-token'])

    def test_assignment_503_is_reported_once_for_explicit_profile_recovery(self):
        session = FakeSession([
            Response({'token': 'one-use-token'}),
            Response('busy', status=503),
        ])
        with patch.dict(sys.modules, {'requests': FAKE_REQUESTS}):
            with self.assertRaisesRegex(ColabRequestError, '503 Service Unavailable'):
                Client(session).assign(accelerator='T4')
        self.assertEqual([call[0] for call in session.calls], ['GET', 'POST'])

    def test_other_post_transport_errors_are_marked_ambiguous_not_retried(self):
        session = FakeSession([ConnectionError('connection lost')])
        client = Client(session)
        with patch.dict(sys.modules, {'requests': FAKE_REQUESTS}):
            with self.assertRaisesRegex(AmbiguousColabPostError, 'outcome is unknown'):
                client._req('POST', 'https://colab.research.google.com/tun/m/assign')
        self.assertEqual(len(session.calls), 1)


if __name__ == '__main__':
    unittest.main()
