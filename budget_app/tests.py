import json
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
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

    @patch('budget_app.services.BudgetService.get_branch_id_from_imedx', return_value='B001')
    def test_regular_user_blocked_while_frozen(self, mock_branch):
        self.client.force_login(self.regular_user)
        response = self.client.post(reverse('budget_add'), data=self.payload, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(ebudget_vet_manpower.objects.count(), 0)

    @patch('budget_app.services.BudgetService.get_branch_id_from_imedx', return_value='B001')
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

    @patch('budget_app.services.BudgetService.get_branch_id_from_imedx', return_value='B001')
    def test_missing_cost_center_returns_error_without_saving(self, mock_branch):
        payload = json.dumps([{'position_name': 'Nurse', 'salary': 20000, 'monthly_data': {}}])
        response = self.client.post(reverse('budget_add'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(ebudget_vet_manpower.objects.count(), 0)

    @patch('budget_app.services.BudgetService.get_branch_id_from_imedx', return_value='B001')
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

    @patch('budget_app.services.BudgetService.get_branch_id_from_imedx', return_value='B001')
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

    @patch('budget_app.services.BudgetService.get_branch_id_from_imedx', return_value='B001')
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

    @patch('budget_app.services.BudgetService.get_branch_id_from_imedx', return_value='B001')
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
