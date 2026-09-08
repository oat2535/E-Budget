from django.conf import settings
from django.test import TestCase
from django.urls import reverse


class SessionExpiredApiTests(TestCase):
    """An expired/missing session hitting the fetch()-based API endpoints
    must get a JSON 401, not a redirect to the login page HTML — the
    frontend calls response.json() straight away and can't parse HTML."""

    def test_get_budget_documents_api_returns_json_401(self):
        response = self.client.get(reverse('api_get_documents', args=['C01']))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response['Content-Type'], 'application/json')
        self.assertEqual(response.json()['code'], 'session_expired')

    def test_get_document_detail_api_returns_json_401(self):
        response = self.client.get(reverse('api_document_detail', args=['VET', 'DOC1']))
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'session_expired')

    def test_update_document_api_returns_json_401(self):
        response = self.client.post(
            reverse('api_document_update', args=['VET', 'DOC1']),
            data='{}',
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['code'], 'session_expired')


class SessionIdleTimeoutContextTests(TestCase):
    """The client-side idle-timeout warning in base.html reads its deadline
    from this context value — it must always track SESSION_COOKIE_AGE so the
    warning can never fall out of sync with when the server actually expires
    the session."""

    def test_context_value_matches_session_cookie_age(self):
        response = self.client.get(reverse('login'))
        self.assertEqual(
            response.context['session_idle_timeout_seconds'],
            settings.SESSION_COOKIE_AGE,
        )
