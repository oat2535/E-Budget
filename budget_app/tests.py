import json
import os
import re
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from budget_app.constants import ALL_BRANCH_USERNAMES
from budget_app.models import SystemSettings, ebudget_vet_manpower, ebudget_gl_entry
from master_data.models import ebudget_general_ledger_master


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


class FreezeBypassTests(TestCase):
    """require_not_frozen must block POST mutations while the budget is
    frozen for everyone except ALL_BRANCH_USERNAMES, enforced server-side
    regardless of what the client sends — this is the highest-risk gate in
    the app (it protects budget data from being edited after close-out)."""

    def setUp(self):
        self.regular_user = User.objects.create_user(username='regular_emp', password='x')
        privileged_username = next(iter(ALL_BRANCH_USERNAMES))
        self.privileged_user = User.objects.create_user(username=privileged_username, password='x')
        SystemSettings.objects.create(is_frozen=1, active_budget_year=2026)
        self.payload = json.dumps([{
            'cost_center_name': 'CC1',
            'position_name': 'Nurse',
            'salary': 20000,
            'monthly_data': {},
        }])

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
    def test_regular_user_blocked_while_frozen(self, mock_branch):
        self.client.force_login(self.regular_user)
        response = self.client.post(reverse('budget_add'), data=self.payload, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(ebudget_vet_manpower.objects.count(), 0)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
    def test_privileged_user_not_blocked_while_frozen(self, mock_branch):
        self.client.force_login(self.privileged_user)
        response = self.client.post(reverse('budget_add'), data=self.payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        self.assertEqual(ebudget_vet_manpower.objects.count(), 1)


class BudgetAddViewTests(TestCase):
    """Happy-path and rejection-path coverage for budget_add_view, as a
    representative sample of the add_*_view family (all share the same
    validate -> create -> save_monthly_data shape) — previously untested
    despite being the code that writes financial data."""

    def setUp(self):
        self.user = User.objects.create_user(username='regular_emp2', password='x')
        SystemSettings.objects.create(is_frozen=0, active_budget_year=2026)
        self.client.force_login(self.user)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
    def test_missing_cost_center_returns_error_without_saving(self, mock_branch):
        payload = json.dumps([{'position_name': 'Nurse', 'salary': 20000, 'monthly_data': {}}])
        response = self.client.post(reverse('budget_add'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(ebudget_vet_manpower.objects.count(), 0)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
    def test_happy_path_creates_document_with_monthly_data(self, mock_branch):
        payload = json.dumps([{
            'cost_center_name': 'CC1',
            'position_name': 'Nurse',
            'salary': 20000,
            'monthly_data': {'jan': {'headcount': 1, 'cost': 20000}},
        }])
        response = self.client.post(reverse('budget_add'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        obj = ebudget_vet_manpower.objects.get()
        self.assertEqual(obj.position_name, 'Nurse')
        self.assertEqual(obj.create_eid, 'regular_emp2')
        self.assertEqual(obj.monthly_details.count(), 1)


class GlEntryMasterAutofillTests(TestCase):
    """proportion/depreciation on ebudget_gl_entry are snapshotted from GL
    master by general_ledger_code — never trusted from the client — so a
    request can't spoof them (see BudgetService.get_gl_master_fields_bulk)."""

    def setUp(self):
        self.user = User.objects.create_user(username='regular_emp3', password='x')
        SystemSettings.objects.create(is_frozen=0, active_budget_year=2026)
        self.client.force_login(self.user)
        ebudget_general_ledger_master.objects.create(
            gl_code='GL001', gl_name='Test GL', proportion='12.50', depreciation='3.75',
        )

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
    def test_create_autofills_proportion_and_depreciation_from_gl_master(self, mock_branch):
        payload = json.dumps([{
            'cost_center_name': 'CC1',
            'general_ledger_code': 'GL001',
            'monthly_data': {'jan': {'amount': 1000}},
        }])
        response = self.client.post(reverse('budget_add_gl_entry'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        obj = ebudget_gl_entry.objects.get()
        self.assertEqual(obj.proportion, 12.50)
        self.assertEqual(obj.depreciation, 3.75)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
    def test_client_supplied_proportion_and_depreciation_are_ignored(self, mock_branch):
        payload = json.dumps([{
            'cost_center_name': 'CC1',
            'general_ledger_code': 'GL001',
            'proportion': 999,
            'depreciation': 999,
            'monthly_data': {'jan': {'amount': 1000}},
        }])
        response = self.client.post(reverse('budget_add_gl_entry'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        obj = ebudget_gl_entry.objects.get()
        self.assertEqual(obj.proportion, 12.50)
        self.assertEqual(obj.depreciation, 3.75)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
    def test_unknown_gl_code_defaults_to_zero(self, mock_branch):
        payload = json.dumps([{
            'cost_center_name': 'CC1',
            'general_ledger_code': 'NO_SUCH_GL',
            'monthly_data': {'jan': {'amount': 1000}},
        }])
        response = self.client.post(reverse('budget_add_gl_entry'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        obj = ebudget_gl_entry.objects.get()
        self.assertEqual(obj.proportion, 0)
        self.assertEqual(obj.depreciation, 0)


class MetropolisFontConsistencyTests(SimpleTestCase):
    """Regression test for the font flipping between font-display's
    fallback and Metropolis depending on whether the page load was a hard
    reload (Ctrl+F5, cache bypassed) or a normal one (F5/navigation, cache
    warm). Confirmed via a Playwright timing simulation: without an early
    <link rel=preload> for the weights a page actually uses, a cold,
    throttled load loses the font-display: optional ~100ms race and locks
    in the fallback font for that whole page view, while a load where the
    font is already available renders Metropolis - i.e. the exact flip the
    user reported. This can't be caught at the Django TestCase seam (no
    real browser/network here to race), so it locks down the two static
    facts that make the real fix work instead: every page preloads the
    Metropolis weights it uses, correctly enough to be honored, and every
    Metropolis face opts into font-display: optional.
    """

    TEMPLATES_TO_WEIGHTS = {
        'budget_app/templates/budget_app/base.html': ['Regular', 'Medium', 'SemiBold', 'Bold'],
        'budget_app/templates/budget_app/login.html': ['Regular', 'SemiBold', 'Bold'],
    }

    def _read(self, relative_path):
        with open(os.path.join(settings.BASE_DIR, relative_path), encoding='utf-8') as f:
            return f.read()

    def test_pages_preload_the_metropolis_weights_they_use(self):
        preload_re = re.compile(
            r'<link\s+rel="preload"\s+as="font"[^>]*href="[^"]*Metropolis-(?P<weight>\w+?)\.otf[^"]*"[^>]*>'
        )
        for template_path, expected_weights in self.TEMPLATES_TO_WEIGHTS.items():
            html = self._read(template_path)
            preloads = {m.group('weight'): m.group(0) for m in preload_re.finditer(html)}
            for weight in expected_weights:
                with self.subTest(template=template_path, weight=weight):
                    self.assertIn(
                        weight, preloads,
                        f'{template_path} no longer preloads Metropolis-{weight}.otf',
                    )
                    # A font preload without crossorigin is fetched in a
                    # different CORS mode than the @font-face request and
                    # gets silently ignored by the browser, so the whole
                    # point of the preload would be lost.
                    self.assertIn('crossorigin', preloads[weight])

    def test_metropolis_font_faces_use_font_display_optional(self):
        css = self._read('budget_app/static/budget_app/css/styles.css')
        font_face_blocks = re.findall(r'@font-face\s*\{([^}]*)\}', css)
        metropolis_blocks = [b for b in font_face_blocks if 'font-family: "Metropolis"' in b]
        self.assertTrue(metropolis_blocks, 'no @font-face rules found for Metropolis')
        for block in metropolis_blocks:
            with self.subTest(block=block):
                self.assertIn('font-display: optional', block)
