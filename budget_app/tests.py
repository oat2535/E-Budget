import hashlib
import json
import os
import re
from unittest.mock import patch, MagicMock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from django.template.loader import render_to_string
from budget_app.backends import ImedxAuthBackend
from budget_app.views import (
    login_view, get_document_visibility_filter_kwargs,
    cancel_document_api, update_document_api,
    budget_add_view, _budget_add_equipment_view
)
from budget_app.services import BudgetService, is_executive_view_only_user, is_district_view_only_user, is_view_only_user
from budget_app.context_processors import site_status
from budget_app.constants import (
    ALL_BRANCH_USERNAMES,
    EXECUTIVE_VIEW_ONLY_ROLES,
    DISTRICT_VIEW_ONLY_ROLES,
    VIEW_ONLY_ROLES,
    VET_CUSTOM_POSITION_GL_CODE,
    NON_VET_SALARY_GL_CODE,
    NON_VET_ALLOWANCE_GL_CODE,
)
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
        from django.core.cache import cache
        cache.clear()
        self.regular_user, _ = User.objects.get_or_create(username='regular_emp')
        self.regular_user.set_password('x')
        self.regular_user.save()
        privileged_username = next(iter(ALL_BRANCH_USERNAMES))
        self.privileged_user, _ = User.objects.get_or_create(username=privileged_username)
        self.privileged_user.set_password('x')
        self.privileged_user.save()
        if not SystemSettings.objects.exists():
            SystemSettings.objects.create(is_frozen=1, active_budget_year=2026)
        else:
            SystemSettings.objects.all().update(is_frozen=1, active_budget_year=2026)
        cache.clear()
        self.payload = json.dumps([{
            'cost_center_name': 'CC1',
            'position_name': 'Nurse',
            'salary': 20000,
            'monthly_data': {},
        }])

    def tearDown(self):
        from django.core.cache import cache
        SystemSettings.objects.all().update(is_frozen=0)
        cache.clear()

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_regular_user_blocked_while_frozen(self, mock_branch):
        self.client.force_login(self.regular_user)
        response = self.client.post(reverse('budget_add'), data=self.payload, content_type='application/json')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(ebudget_vet_manpower.objects.count(), 0)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
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
        self.user, _ = User.objects.get_or_create(username='regular_emp2')
        self.user.set_password('x')
        self.user.save()
        if not SystemSettings.objects.exists():
            SystemSettings.objects.create(is_frozen=0, active_budget_year=2026)
        else:
            SystemSettings.objects.filter(id=1).update(is_frozen=0, active_budget_year=2026)
        self.client.force_login(self.user)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_missing_cost_center_returns_error_without_saving(self, mock_branch):
        payload = json.dumps([{'position_name': 'Nurse', 'salary': 20000, 'monthly_data': {}}])
        response = self.client.post(reverse('budget_add'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'error')
        self.assertEqual(ebudget_vet_manpower.objects.count(), 0)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_happy_path_creates_document_with_monthly_data(self, mock_branch):
        payload = json.dumps([{
            'cost_center_name': 'CC1',
            'position_name': 'Nurse',
            'salary': 20000,
            'monthly_data': {'jan': {'headcount': 1, 'cost': 20000}},
        }])
        response = self.client.post(reverse('budget_add'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        obj = ebudget_vet_manpower.objects.filter(create_eid='regular_emp2').order_by('-id').first()
        self.assertIsNotNone(obj)
        self.assertEqual(obj.position_name, 'Nurse')
        self.assertEqual(obj.create_eid, 'regular_emp2')
        self.assertEqual(obj.monthly_details.count(), 1)


class GlEntryMasterAutofillTests(TestCase):
    """proportion/depreciation on ebudget_gl_entry are snapshotted from GL
    master by general_ledger_code — never trusted from the client — so a
    request can't spoof them (see BudgetService.get_gl_master_fields_bulk)."""

    def setUp(self):
        self.user, _ = User.objects.get_or_create(username='regular_emp3')
        self.user.set_password('x')
        self.user.save()
        if not SystemSettings.objects.exists():
            SystemSettings.objects.create(is_frozen=0, active_budget_year=2026)
        else:
            SystemSettings.objects.filter(id=1).update(is_frozen=0, active_budget_year=2026)
        self.client.force_login(self.user)
        ebudget_general_ledger_master.objects.get_or_create(
            gl_code='GL001', defaults={'gl_name': 'Test GL', 'proportion': '12.50', 'depreciation': '3.75'},
        )

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_create_autofills_proportion_and_depreciation_from_gl_master(self, mock_branch):
        payload = json.dumps([{
            'cost_center_name': 'CC1',
            'general_ledger_code': 'GL001',
            'monthly_data': {'jan': {'amount': 1000}},
        }])
        response = self.client.post(reverse('budget_add_gl_entry'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        obj = ebudget_gl_entry.objects.filter(general_ledger_code='GL001').order_by('-id').first()
        self.assertIsNotNone(obj)
        self.assertEqual(obj.proportion, 12.50)
        self.assertEqual(obj.depreciation, 3.75)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
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
        obj = ebudget_gl_entry.objects.filter(general_ledger_code='GL001').order_by('-id').first()
        self.assertIsNotNone(obj)
        self.assertEqual(obj.proportion, 12.50)
        self.assertEqual(obj.depreciation, 3.75)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_unknown_gl_code_defaults_to_zero(self, mock_branch):
        payload = json.dumps([{
            'cost_center_name': 'CC1',
            'general_ledger_code': 'NO_SUCH_GL',
            'monthly_data': {'jan': {'amount': 1000}},
        }])
        response = self.client.post(reverse('budget_add_gl_entry'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        obj = ebudget_gl_entry.objects.filter(general_ledger_code='NO_SUCH_GL').order_by('-id').first()
        self.assertIsNotNone(obj)
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


class EquipmentGlCodeResolutionTests(SimpleTestCase):
    """Unit tests for fixed GL code resolution on CAR, Renovate, and Software."""

    def test_resolve_equipment_gl_code_returns_correct_constants(self):
        from budget_app.constants import CAR_GL_CODE, RENOVATE_GL_CODE, SOFTWARE_GL_CODE
        from budget_app.views import resolve_equipment_gl_code

        self.assertEqual(CAR_GL_CODE, '61300013')
        self.assertEqual(RENOVATE_GL_CODE, '61300008')
        self.assertEqual(SOFTWARE_GL_CODE, '61300005')

        self.assertEqual(resolve_equipment_gl_code('CAR', 500000), '61300013')
        self.assertEqual(resolve_equipment_gl_code('Renovate', 150000), '61300008')
        self.assertEqual(resolve_equipment_gl_code('Software', 25000), '61300005')

    def test_resolve_price_threshold_gl_code_allows_5000_as_fix_asset(self):
        """A purchase price of exactly 5,000 THB or greater must resolve to the capitalized
        fixed-asset GL code (HIGH) across all threshold equipment categories without raising
        any error, while prices under 5,000 resolve to the low-value code."""
        from budget_app.views import resolve_equipment_gl_code
        from budget_app.constants import (
            MEDICAL_EQUIPMENT_GL_CODE_HIGH, MEDICAL_EQUIPMENT_GL_CODE_LOW,
            COMPUTER_EQUIPMENT_GL_CODE_HIGH, COMPUTER_EQUIPMENT_GL_CODE_LOW,
            FURNITURE_GL_CODE_HIGH, FURNITURE_GL_CODE_LOW,
            TOOLS_EQUIPMENT_GL_CODE_HIGH, TOOLS_EQUIPMENT_GL_CODE_LOW,
        )

        # 5,000 THB exactly (Fix Asset capitalization threshold)
        self.assertEqual(resolve_equipment_gl_code('Medical Equipment', 5000), MEDICAL_EQUIPMENT_GL_CODE_HIGH)
        self.assertEqual(resolve_equipment_gl_code('Computer Equipment', 5000), COMPUTER_EQUIPMENT_GL_CODE_HIGH)
        self.assertEqual(resolve_equipment_gl_code('Furniture', 5000), FURNITURE_GL_CODE_HIGH)
        self.assertEqual(resolve_equipment_gl_code('Tools & Equipment', 5000), TOOLS_EQUIPMENT_GL_CODE_HIGH)

        # Greater than 5,000 THB
        self.assertEqual(resolve_equipment_gl_code('Medical Equipment', 5001), MEDICAL_EQUIPMENT_GL_CODE_HIGH)
        self.assertEqual(resolve_equipment_gl_code('Medical Equipment', 25000), MEDICAL_EQUIPMENT_GL_CODE_HIGH)

        # Less than 5,000 THB
        self.assertEqual(resolve_equipment_gl_code('Medical Equipment', 4999), MEDICAL_EQUIPMENT_GL_CODE_LOW)
        self.assertEqual(resolve_equipment_gl_code('Computer Equipment', 4999), COMPUTER_EQUIPMENT_GL_CODE_LOW)
        self.assertEqual(resolve_equipment_gl_code('Furniture', 4999), FURNITURE_GL_CODE_LOW)
        self.assertEqual(resolve_equipment_gl_code('Tools & Equipment', 4999), TOOLS_EQUIPMENT_GL_CODE_LOW)


class FixAssetStaticTextUnitTests(SimpleTestCase):
    """Unit tests verifying all Fix Asset equipment static text entry, datalist editor in templates, and NULL item_master resolution."""

    def test_all_fix_asset_templates_contain_custom_editor_and_datalist(self):
        templates_to_check = [
            ('budget_add_car.html', 'car-item-datalist', 'carEditor'),
            ('budget_add_medical_equipment.html', 'medical-item-datalist', 'medicalEditor'),
            ('budget_add_computer_equipment.html', 'computer-item-datalist', 'computerEditor'),
            ('budget_add_furniture.html', 'furniture-item-datalist', 'furnitureEditor'),
            ('budget_add_tools_equipment.html', 'tools-item-datalist', 'toolsEditor'),
            ('budget_add_renovate.html', 'renovate-item-datalist', 'renovateEditor'),
            ('budget_add_software.html', 'software-item-datalist', 'softwareEditor'),
        ]
        for template_name, datalist_id, editor_name in templates_to_check:
            template_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', template_name)
            with open(template_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertIn(datalist_id, content, f"Missing {datalist_id} in {template_name}")
            self.assertIn(editor_name, content, f"Missing {editor_name} in {template_name}")
            self.assertIn(f'editor: {editor_name}', content, f"Missing editor: {editor_name} in {template_name}")

    def test_budget_list_js_contains_modal_equipment_editor_and_datalist(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('modal-equipment-item-datalist', content)
        self.assertIn('modalItemEditor', content)

    @patch('master_data.models.ebudget_budget_item_master.objects.filter')
    def test_bulk_lookup_returns_none_for_static_custom_items(self, mock_filter):
        from budget_app.services import BudgetService
        mock_filter.return_value = []
        custom_items = [
            'รถตู้สั่งทำพิเศษ 4x4',
            'เตียงตรวจสั่งทำพิเศษ',
            'คอมพิวเตอร์สเปกพิเศษ AI',
            'โต๊ะประชุมสั่งทำ',
            'เครื่องมือช่างเฉพาะทาง',
            'ปรับปรุงระบบดูดควันพิเศษ',
            'Custom AI Training Suite'
        ]
        master_fks = BudgetService.get_master_fks_bulk(custom_items)
        for item in custom_items:
            master_obj, gl_code = master_fks.get(item, (None, None))
            self.assertIsNone(master_obj, f"Expected master_obj to be None for {item}")
            self.assertIsNone(gl_code, f"Expected gl_code to be None for {item}")

    def test_all_fix_asset_templates_enforce_min_purchase_price_5000(self):
        templates = [
            'budget_add_medical_equipment.html',
            'budget_add_computer_equipment.html',
            'budget_add_furniture.html',
            'budget_add_tools_equipment.html',
            'budget_add_car.html',
            'budget_add_renovate.html',
            'budget_add_software.html'
        ]
        for tpl in templates:
            path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', tpl)
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertIn('salary < 5000', content, f"{tpl} must enforce salary < 5000 on save")
            self.assertIn('5,000 บาทขึ้นไป', content, f"{tpl} must contain formal 5000 THB warning")
            self.assertIn('priceNum < 5000', content, f"{tpl} must enforce priceNum < 5000 real-time in onchange")
            self.assertIn('4,999 บาทลงมา', content, f"{tpl} must warn against entering 4999 down")

    def test_budget_list_js_enforces_min_purchase_price_5000(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('isEquipment && salary < 5000', content)
        self.assertIn('5,000 บาทขึ้นไป', content)
        self.assertIn('isEquipment && x === priceCol', content)
        self.assertIn('priceNum < 5000', content)
        self.assertIn('4,999 บาทลงมา', content)

    def test_equipment_backend_rejects_purchase_price_under_5000(self):
        from django.test import RequestFactory
        from budget_app.views import _budget_add_equipment_view
        from budget_app.models import ebudget_tools_equipment
        from django.contrib.auth.models import AnonymousUser

        rf = RequestFactory()
        payload = json.dumps([{
            'cost_center_name': 'CC1',
            'item_name': 'เครื่องมือทดสอบ',
            'purchase_price': 4999.0,
            'monthly_data': {'jan': {'headcount': 1, 'cost': 4999.0}},
        }])
        req = rf.post('/add_tools_equipment/', data=payload, content_type='application/json')
        req.user = AnonymousUser()
        res = _budget_add_equipment_view(req, ebudget_tools_equipment, 'Tools & Equipment', 'budget_app/budget_add_tools_equipment.html', 7)
        data = json.loads(res.content.decode('utf-8'))
        self.assertEqual(data['status'], 'error')
        self.assertIn('5,000 บาทขึ้นไป', data['message'])

    def test_equipment_backend_accepts_purchase_price_5000(self):
        """A purchase price of exactly 5,000 THB is valid in Fix Asset and passes price validation."""
        from django.test import RequestFactory
        from budget_app.views import _budget_add_equipment_view
        from budget_app.models import ebudget_tools_equipment
        from django.contrib.auth.models import AnonymousUser

        rf = RequestFactory()
        payload = json.dumps([{
            'cost_center_name': 'CC1',
            'item_name': 'UNKNOWN_ITEM_TEST',
            'purchase_price': 5000.0,
            'monthly_data': {'jan': {'headcount': 1, 'cost': 5000.0}},
        }])
        req = rf.post('/add_tools_equipment/', data=payload, content_type='application/json')
        req.user = AnonymousUser()
        res = _budget_add_equipment_view(req, ebudget_tools_equipment, 'Tools & Equipment', 'budget_app/budget_add_tools_equipment.html', 7)
        data = json.loads(res.content.decode('utf-8'))
        # It must NOT be rejected by the purchase price < 5000 check:
        if data['status'] == 'error':
            self.assertNotIn('5,000 บาทขึ้นไป', data['message'])

    def test_update_document_api_no_inner_loop_shadowing(self):
        """In update_document_api, the purchase price validation for equipment must not be
        nested inside the row-creation loop using the same loop variable 'item', which would
        overwrite earlier rows with the last row's data."""
        views_path = os.path.join(settings.BASE_DIR, 'budget_app', 'views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find update_document_api definition
        start = content.find('def update_document_api(')
        end = content.find('def ', start + 1)
        update_func = content[start:end] if end != -1 else content[start:]

        # Must not contain nested 'for item in data:'
        self.assertNotIn(
            "for item in data:\n                        price = float(item.get('purchase_price')",
            update_func,
            "update_document_api must not have nested 'for item in data' re-assigning item"
        )
        # Validation must be before existing_items.delete()
        del_pos = update_func.find('.delete()')
        price_val_pos = update_func.find('for row_data in data:')
        self.assertGreater(del_pos, 0)
        self.assertGreater(price_val_pos, 0)
        self.assertLess(price_val_pos, del_pos, "Price validation must happen BEFORE existing_items.delete()")


class BudgetListC03FilterUnitTests(SimpleTestCase):
    """Unit tests verifying that Budget Plan (Category C03) includes GL Actual Template in its type filter."""

    def test_budget_list_html_contains_gl_actual_template_option(self):
        html_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_list.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('<option value="GL Actual Template">GL Actual Template</option>', content)
        self.assertNotIn('<option value="Budget Plan">Budget Plan</option>', content)

    def test_budget_list_js_populates_gl_actual_template_in_c03_filter(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Verify C03 block contains GL Actual Template
        self.assertIn('<option value="GL Actual Template">GL Actual Template</option>', content)
        # Verify C03 branch sets up GL Actual Template and does NOT include Budget Plan
        c03_idx = content.find("categoryCode === 'C03'")
        self.assertNotEqual(c03_idx, -1)
        c03_snippet = content[c03_idx:c03_idx + 400]
        self.assertIn('GL Actual Template', c03_snippet)
        self.assertIn('EXPENSE', c03_snippet)
        self.assertIn('Revenue', c03_snippet)
        self.assertNotIn('<option value="Budget Plan">', c03_snippet)


class EquipmentGlCodeSaveTests(TestCase):
    """Integration tests verifying CAR, Renovate, and Software add views save their fixed GL codes."""

    def setUp(self):
        self.user, _ = User.objects.get_or_create(username='test_officer')
        self.user.set_password('x')
        self.user.save()
        if not SystemSettings.objects.exists():
            SystemSettings.objects.create(is_frozen=0, active_budget_year=2026)
        else:
            SystemSettings.objects.filter(id=1).update(is_frozen=0, active_budget_year=2026)
        self.client.force_login(self.user)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_car_add_view_saves_correct_gl_code(self, mock_branch):
        from budget_app.models import ebudget_car
        payload = json.dumps([{
            'cost_center_name': 'CC_LOGISTICS',
            'item_name': 'รถกระบะขนส่ง',
            'description': 'รถกระบะ 4 ประตู',
            'purchase_price': 850000,
            'monthly_data': {'jan': {'headcount': 1, 'cost': 850000}},
        }])
        response = self.client.post(reverse('budget_add_car'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        car_item = ebudget_car.objects.filter(item_name='รถกระบะขนส่ง').first()
        self.assertIsNotNone(car_item)
        self.assertEqual(car_item.item_name, 'รถกระบะขนส่ง')
        self.assertEqual(car_item.general_ledger_code, '61300013')
        self.assertIsNone(car_item.item_master)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_renovate_add_view_saves_correct_gl_code(self, mock_branch):
        from budget_app.models import ebudget_renovate
        payload = json.dumps([{
            'cost_center_name': 'CC_FACILITY',
            'item_name': 'ปรับปรุงห้องผ่าตัด',
            'description': 'กั้นห้องและปูกระเบื้องใหม่',
            'purchase_price': 120000,
            'monthly_data': {'feb': {'headcount': 1, 'cost': 120000}},
        }])
        response = self.client.post(reverse('budget_add_renovate'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        renovate_item = ebudget_renovate.objects.filter(item_name='ปรับปรุงห้องผ่าตัด').first()
        self.assertIsNotNone(renovate_item)
        self.assertEqual(renovate_item.item_name, 'ปรับปรุงห้องผ่าตัด')
        self.assertEqual(renovate_item.general_ledger_code, '61300008')

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_software_add_view_saves_correct_gl_code(self, mock_branch):
        from budget_app.models import ebudget_software
        payload = json.dumps([{
            'cost_center_name': 'CC_IT',
            'item_name': 'Antivirus Enterprise',
            'description': 'ลิขสิทธิ์ 1 ปี',
            'purchase_price': 45000,
            'monthly_data': {'mar': {'headcount': 1, 'cost': 45000}},
        }])
        response = self.client.post(reverse('budget_add_software'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        software_item = ebudget_software.objects.filter(item_name='Antivirus Enterprise').first()
        self.assertIsNotNone(software_item)
        self.assertEqual(software_item.item_name, 'Antivirus Enterprise')
        self.assertEqual(software_item.general_ledger_code, '61300005')


class StaticTextPositionTests(TestCase):
    """Tests verifying VET, NON VET, and Position Adjustment support static text positions,
    leaving item_master_id NULL when the position is not in master data."""

    def setUp(self):
        self.user, _ = User.objects.get_or_create(username='test_officer2')
        self.user.set_password('x')
        self.user.save()
        if not SystemSettings.objects.exists():
            SystemSettings.objects.create(is_frozen=0, active_budget_year=2026)
        self.client.force_login(self.user)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_vet_manpower_static_text_saves_null_item_master(self, mock_branch):
        payload = json.dumps([{
            'cost_center_name': 'CC_VET',
            'position_name': 'สัตวแพทย์ที่ปรึกษาพิเศษ',
            'description': 'ตำแหน่งชั่วคราว',
            'salary': 65000,
            'monthly_data': {'jan': {'headcount': 1, 'cost': 65000}},
        }])
        response = self.client.post(reverse('budget_add'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        vet_obj = ebudget_vet_manpower.objects.filter(position_name='สัตวแพทย์ที่ปรึกษาพิเศษ').first()
        self.assertIsNotNone(vet_obj)
        self.assertEqual(vet_obj.position_name, 'สัตวแพทย์ที่ปรึกษาพิเศษ')
        self.assertIsNone(vet_obj.item_master)
        self.assertIsNone(vet_obj.item_master_id)
        self.assertEqual(vet_obj.general_ledger_code, VET_CUSTOM_POSITION_GL_CODE)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_non_vet_manpower_static_text_saves_null_item_master(self, mock_branch):
        from budget_app.models import ebudget_non_vet_manpower
        payload = json.dumps([{
            'cost_center_name': 'CC_ADMIN',
            'position_name': 'เจ้าหน้าที่ประสานงานโครงการพิเศษ',
            'description': 'งานโครงการเฉพาะกิจ',
            'salary': 30000,
            'position_allowance': 5000,
            'monthly_data': {'feb': {'headcount': 1, 'cost': 35000}},
        }])
        response = self.client.post(reverse('budget_add_non_vet'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        non_vet_obj = ebudget_non_vet_manpower.objects.filter(position_name='เจ้าหน้าที่ประสานงานโครงการพิเศษ').first()
        self.assertIsNotNone(non_vet_obj)
        self.assertEqual(non_vet_obj.position_name, 'เจ้าหน้าที่ประสานงานโครงการพิเศษ')
        self.assertIsNone(non_vet_obj.item_master)
        self.assertIsNone(non_vet_obj.item_master_id)
        self.assertEqual(non_vet_obj.salary_general_ledger_code, NON_VET_SALARY_GL_CODE)
        self.assertEqual(non_vet_obj.position_allowance_general_ledger_code, NON_VET_ALLOWANCE_GL_CODE)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_position_adjustment_static_text_saves_null_item_master(self, mock_branch):
        from budget_app.models import ebudget_position_adjustment
        payload = json.dumps([{
            'cost_center_name': 'CC_HR',
            'adjustment_type': 'NON VET',
            'old_position_name': 'เจ้าหน้าที่การตลาดเดิม',
            'old_description': 'ตำแหน่งเดิม',
            'new_position_name': 'ผู้จัดการฝ่ายกลยุทธ์ใหม่',
            'new_description': 'ตำแหน่งใหม่เฉพาะกิจ',
            'old_salary': 25000,
            'old_allowance': 3000,
            'new_salary': 40000,
            'new_allowance': 7000,
            'monthly_data': {'mar': {'headcount': 1, 'cost': 19000, 'salary_diff_cost': 15000, 'allowance_diff_cost': 4000}},
        }])
        response = self.client.post(reverse('budget_add_adjustment'), data=payload, content_type='application/json')
        self.assertEqual(response.json()['status'], 'success')
        adj_obj = ebudget_position_adjustment.objects.filter(new_position_name='ผู้จัดการฝ่ายกลยุทธ์ใหม่').first()
        self.assertIsNotNone(adj_obj)
        self.assertEqual(adj_obj.old_position_name, 'เจ้าหน้าที่การตลาดเดิม')
        self.assertEqual(adj_obj.new_position_name, 'ผู้จัดการฝ่ายกลยุทธ์ใหม่')
        self.assertIsNone(adj_obj.item_master)
        self.assertIsNone(adj_obj.item_master_id)
        self.assertEqual(adj_obj.salary_general_ledger_code, NON_VET_SALARY_GL_CODE)
        self.assertEqual(adj_obj.allowance_general_ledger_code, NON_VET_ALLOWANCE_GL_CODE)

    def test_templates_and_js_have_datalists_and_text_editors(self):
        vet_html = open(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add.html'), encoding='utf-8').read()
        self.assertIn('vet-position-datalist', vet_html)
        self.assertIn('vetEditor', vet_html)
        self.assertIn('eb-dropdown-cell', vet_html)

        non_vet_html = open(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_non_vet.html'), encoding='utf-8').read()
        self.assertIn('non-vet-position-datalist', non_vet_html)
        self.assertIn('nonVetEditor', non_vet_html)
        self.assertIn('eb-dropdown-cell', non_vet_html)

        adj_html = open(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_adjustment.html'), encoding='utf-8').read()
        self.assertIn('adj-vet-positions-datalist', adj_html)
        self.assertIn('adj-non-vet-positions-datalist', adj_html)
        self.assertIn('adj-type-datalist', adj_html)
        self.assertIn('adjTypeEditor', adj_html)
        self.assertIn('adjPositionEditor', adj_html)
        self.assertIn('eb-dropdown-cell', adj_html)

        budget_list_js = open(os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js'), encoding='utf-8').read()
        self.assertIn('modal-vet-position-datalist', budget_list_js)
        self.assertIn('modal-non-vet-position-datalist', budget_list_js)
        self.assertIn('modal-adj-type-datalist', budget_list_js)
        self.assertIn('modalAdjTypeEditor', budget_list_js)
        self.assertIn('modalAdjPositionEditor', budget_list_js)
        self.assertIn('modalItemEditor', budget_list_js)
        self.assertIn('eb-dropdown-cell', budget_list_js)

        car_html = open(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_car.html'), encoding='utf-8').read()
        self.assertIn('eb-dropdown-cell', car_html)

    def test_dropdown_indicator_styling_and_page_constraints(self):
        # 1. Global CSS in polish.css has .eb-dropdown-cell and .jexcel_dropdown styling
        polish_css = open(os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'css', 'polish.css'), encoding='utf-8').read()
        self.assertIn('.eb-dropdown-cell', polish_css)
        self.assertIn('.jexcel_dropdown', polish_css)
        self.assertIn('.eb-dropdown-input', polish_css)

        # 2. All equipment pages have eb-dropdown-cell
        equipment_templates = [
            'budget_add_car.html',
            'budget_add_medical_equipment.html',
            'budget_add_computer_equipment.html',
            'budget_add_furniture.html',
            'budget_add_tools_equipment.html',
            'budget_add_renovate.html',
            'budget_add_software.html',
        ]
        for tpl in equipment_templates:
            content = open(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', tpl), encoding='utf-8').read()
            self.assertIn('eb-dropdown-cell', content, f"{tpl} should have eb-dropdown-cell")

        # 3. EXPENSE and Revenue now use CAR-style datalist dropdown with validation against GL master
        expense_html = open(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_gl_entry.html'), encoding='utf-8').read()
        self.assertIn('gl-item-datalist', expense_html)
        self.assertIn('glEditor', expense_html)
        self.assertIn('eb-dropdown-cell', expense_html)
        self.assertIn('onselection', expense_html)
        self.assertIn('monthly-total-grand', expense_html)

        revenue_html = open(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_revenue.html'), encoding='utf-8').read()
        self.assertIn('gl-item-datalist', revenue_html)
        self.assertIn('glEditor', revenue_html)
        self.assertIn('eb-dropdown-cell', revenue_html)
        self.assertIn('onselection', revenue_html)
        self.assertIn('monthly-total-grand', revenue_html)

        budget_list_js = open(os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js'), encoding='utf-8').read()
        self.assertIn('glEntryMonthlyTotal-grand', budget_list_js)

        # 4. GL Actual Template must NOT have any modifications
        glat_html = open(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_gl_actual_template.html'), encoding='utf-8').read()
        self.assertNotIn('eb-dropdown-cell', glat_html)
        self.assertNotIn('datalist', glat_html)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None, 'is_manager': False})
    def test_position_adjustment_renders_with_type_editor(self, mock_branch):
        response = self.client.get(reverse('budget_add_adjustment'), SERVER_NAME='192.168.1.40')
        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('adj-type-datalist', content)
        self.assertIn('adjTypeEditor', content)
        self.assertIn('editor: adjTypeEditor', content)

    def test_non_vet_item_master_schedule_data(self):
        from master_data.models import ebudget_budget_item_master
        qs = ebudget_budget_item_master.objects.filter(category_id=1, sub_category_id=2)
        self.assertEqual(qs.count(), 40)
        lab_item = qs.filter(item_name='เจ้าหน้าที่ LAB').first()
        self.assertIsNotNone(lab_item)
        self.assertEqual(float(lab_item.salary), 15000.0)
        self.assertEqual(float(lab_item.position_allowance), 3000.0)
        self.assertEqual(float(lab_item.total_salary), 18000.0)

        fo_items = list(qs.filter(item_name='หัวหน้าหน่วย Front Office'))
        self.assertEqual(len(fo_items), 2)
        allowances = sorted([float(x.position_allowance) for x in fo_items])
        self.assertEqual(allowances, [3000.0, 4000.0])

        director = qs.filter(item_name='รองผู้อำนวยการ').first()
        self.assertIsNotNone(director)
        self.assertEqual(float(director.salary), 0.0)
        self.assertEqual(float(director.position_allowance), 0.0)
        self.assertEqual(float(director.total_salary), 0.0)

    def test_fix_asset_subcategories_have_other_option(self):
        """Verifies that all subcategories under category_id=2 (Fix Asset) contain
        an 'OTHER' entry in ebudget_budget_item_master."""
        from master_data.models import ebudget_budget_item_master, ebudget_budget_sub_category_master
        subcats = list(ebudget_budget_sub_category_master.objects.filter(category_id=2).values_list('id', flat=True))
        expected_subcats = [4, 5, 6, 7, 8, 9, 10]
        for subcat_id in expected_subcats:
            self.assertIn(subcat_id, subcats, f"Subcategory {subcat_id} missing in category 2")
            other_item = ebudget_budget_item_master.objects.filter(
                category_id=2,
                sub_category_id=subcat_id,
                item_name='OTHER'
            ).first()
            self.assertIsNotNone(other_item, f"Subcategory {subcat_id} missing 'OTHER' item in master")
            self.assertEqual(float(other_item.purchase_price), 0.0)
            self.assertEqual(float(other_item.salary), 0.0)
            self.assertEqual(float(other_item.total_salary), 0.0)

    def test_get_master_fks_bulk_isolates_by_subcategory(self):
        """Verifies that BudgetService.get_master_fks_bulk returns the subcategory-specific
        'OTHER' item when sub_category_id is passed."""
        from budget_app.services import BudgetService
        car_fks = BudgetService.get_master_fks_bulk(['OTHER'], category_id=2, sub_category_id=8)
        self.assertIn('OTHER', car_fks)
        car_master, _ = car_fks['OTHER']
        self.assertIsNotNone(car_master)
        self.assertEqual(car_master.sub_category_id, 8)

        med_fks = BudgetService.get_master_fks_bulk(['OTHER'], category_id=2, sub_category_id=4)
        self.assertIn('OTHER', med_fks)
        med_master, _ = med_fks['OTHER']
        self.assertIsNotNone(med_master)
        self.assertEqual(med_master.sub_category_id, 4)

        self.assertNotEqual(car_master.id, med_master.id)

    def test_furniture_item_master_data(self):
        """Verifies that Furniture (sub_category_id=6) has exactly 13 items:
        12 newly updated furniture items from the user schedule plus 'OTHER'."""
        from master_data.models import ebudget_budget_item_master
        qs = ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=6)
        self.assertEqual(qs.count(), 13)

        # Check 'OTHER'
        other_item = qs.filter(item_name='OTHER').first()
        self.assertIsNotNone(other_item)
        self.assertEqual(float(other_item.purchase_price), 0.0)

        # Check a low price item (GL 60600003)
        bar_chair = qs.filter(item_name='เก้าอี้บาร์กลม').first()
        self.assertIsNotNone(bar_chair)
        self.assertEqual(float(bar_chair.purchase_price), 2700.0)
        self.assertEqual(bar_chair.general_ledger_code, '60600003')

        # Check a high price item (GL 61300012)
        air_cond = qs.filter(item_name='เครื่องปรับอากาศ 36100 BTU').first()
        self.assertIsNotNone(air_cond)
        self.assertEqual(float(air_cond.purchase_price), 77500.0)
        self.assertEqual(air_cond.general_ledger_code, '61300012')

    def test_tools_equipment_item_master_data(self):
        """Verifies that Tools & Equipment (sub_category_id=7) has exactly 16 items:
        15 newly updated tools items from the user schedule plus 'OTHER'."""
        from master_data.models import ebudget_budget_item_master
        qs = ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=7)
        self.assertEqual(qs.count(), 16)

        # Check 'OTHER'
        other_item = qs.filter(item_name='OTHER').first()
        self.assertIsNotNone(other_item)
        self.assertEqual(float(other_item.purchase_price), 0.0)

        # Check dryer S
        dryer_s = qs.filter(item_name='ตู้เป่าขนสัตว์ ขนาดS 52.5*45*65cm').first()
        self.assertIsNotNone(dryer_s)
        self.assertEqual(float(dryer_s.purchase_price), 27500.0)
        self.assertEqual(dryer_s.general_ledger_code, '61300011')

        # Check printer
        printer = qs.filter(item_name='เครื่องพิมพ์ป้าย(Pet shop)').first()
        self.assertIsNotNone(printer)
        self.assertEqual(float(printer.purchase_price), 7000.0)
        self.assertEqual(printer.general_ledger_code, '61300011')


class ManpowerIntegerHeadcountTests(SimpleTestCase):
    """Verifies that VET Manpower, NON VET Manpower, and Position Adjustment
    enforce integer-only headcounts across client-side scripts, templates,
    API validations, and backend persistence."""

    def test_validate_manpower_headcount_integers_valid(self):
        from budget_app.views import validate_manpower_headcount_integers
        valid_data = [{
            'position_name': 'Veterinarian',
            'monthly_data': {
                'jan': {'headcount': 1, 'cost': 30000},
                'feb': {'headcount': 2.0, 'cost': 60000},
                'mar': {'headcount': '3', 'cost': 90000},
                'apr': {'headcount': 0, 'cost': 0},
            }
        }]
        err = validate_manpower_headcount_integers(valid_data, 'position_name')
        self.assertIsNone(err)

    def test_validate_manpower_headcount_integers_invalid_decimal(self):
        from budget_app.views import validate_manpower_headcount_integers
        invalid_data = [{
            'position_name': 'Veterinarian A',
            'monthly_data': {
                'jan': {'headcount': 1.5, 'cost': 45000},
            }
        }]
        err = validate_manpower_headcount_integers(invalid_data, 'position_name')
        self.assertIsNotNone(err)
        self.assertIn('มกราคม (Jan)', err)
        self.assertIn('จำนวนเต็มเท่านั้น', err)
        self.assertIn('Veterinarian A', err)

    def test_validate_manpower_headcount_integers_negative(self):
        from budget_app.views import validate_manpower_headcount_integers
        neg_data = [{
            'position_name': 'Vet Tech',
            'monthly_data': {
                'feb': {'headcount': -1, 'cost': 0},
            }
        }]
        err = validate_manpower_headcount_integers(neg_data, 'position_name')
        self.assertIsNotNone(err)
        self.assertIn('กุมภาพันธ์ (Feb)', err)
        self.assertIn('จำนวนเต็มเท่านั้น', err)

    def test_validate_manpower_headcount_integers_invalid_leading_zeros(self):
        from budget_app.views import validate_manpower_headcount_integers
        for bad_val in ['03', '04', '05', '007']:
            bad_data = [{
                'position_name': 'Vet Tech',
                'monthly_data': {
                    'mar': {'headcount': bad_val, 'cost': 15000},
                }
            }]
            err = validate_manpower_headcount_integers(bad_data, 'position_name')
            self.assertIsNotNone(err)
            self.assertIn('มีนาคม (Mar)', err)
            self.assertIn('ไม่อนุญาตให้ระบุรูปแบบที่มีเลข 0 นำหน้า', err)

        # Standalone '0' or 0 must still be completely valid
        zero_data = [{
            'position_name': 'Vet Tech',
            'monthly_data': {
                'mar': {'headcount': '0', 'cost': 0},
                'apr': {'headcount': 0, 'cost': 0},
            }
        }]
        err_zero = validate_manpower_headcount_integers(zero_data, 'position_name')
        self.assertIsNone(err_zero)

    def test_templates_enforce_integer_headcount(self):
        # 1. VET Manpower
        vet_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add.html')
        with open(vet_path, encoding='utf-8') as f:
            vet_content = f.read()
        self.assertIn('!Number.isInteger(num)', vet_content)
        self.assertIn('replace(/[^0-9]/g', vet_content)
        self.assertIn('clean.replace(/^0+(?=\\d)/', vet_content)
        self.assertIn('/^0\\d+/.test(rawStr)', vet_content)
        self.assertIn('count % 1 !== 0', vet_content)

        # 2. NON VET Manpower
        non_vet_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_non_vet.html')
        with open(non_vet_path, encoding='utf-8') as f:
            non_vet_content = f.read()
        self.assertIn('!Number.isInteger(num)', non_vet_content)
        self.assertIn('replace(/[^0-9]/g', non_vet_content)
        self.assertIn('clean.replace(/^0+(?=\\d)/', non_vet_content)
        self.assertIn('/^0\\d+/.test(rawStr)', non_vet_content)
        self.assertIn('count % 1 !== 0', non_vet_content)

        # 3. Position Adjustment
        adj_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_adjustment.html')
        with open(adj_path, encoding='utf-8') as f:
            adj_content = f.read()
        self.assertIn('!Number.isInteger(num)', adj_content)
        self.assertIn('replace(/[^0-9]/g', adj_content)
        self.assertIn('clean.replace(/^0+(?=\\d)/', adj_content)
        self.assertIn('/^0\\d+/.test(rawStr)', adj_content)
        self.assertIn('count % 1 !== 0', adj_content)

        # 4. budget_list.js (Modal editing)
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, encoding='utf-8') as f:
            js_content = f.read()
        self.assertIn('monthCounts[c] % 1 !== 0', js_content)
        self.assertIn('/^0\\d+/.test(rawStr)', js_content)
        self.assertIn('!Number.isInteger(num)', js_content)
        self.assertIn('clean.replace(/^0+(?=\\d)/', js_content)
        self.assertIn('x >= startCol && x <= endCol', js_content)
        self.assertIn('x >= 13 && x <= 24', js_content)

        # 5. All FIX ASSET templates
        fix_asset_templates = [
            'budget_add_medical_equipment.html',
            'budget_add_computer_equipment.html',
            'budget_add_furniture.html',
            'budget_add_tools_equipment.html',
            'budget_add_car.html',
            'budget_add_renovate.html',
            'budget_add_software.html',
        ]
        for tmpl in fix_asset_templates:
            tmpl_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', tmpl)
            with open(tmpl_path, encoding='utf-8') as f:
                content = f.read()
            self.assertIn('!Number.isInteger(num)', content, f"{tmpl} missing isInteger check")
            self.assertIn('clean.replace(/^0+(?=\\d)/', content, f"{tmpl} missing leading zero strip in input listener")
            self.assertIn('/^0\\d+/.test(rawStr)', content, f"{tmpl} missing leading zero check in save button")
            self.assertIn('count % 1 !== 0', content, f"{tmpl} missing count % 1 check in save button")

    @patch('budget_app.models.SystemSettings.load')
    def test_vet_manpower_api_rejects_decimal_headcount(self, mock_settings):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.views import budget_add_view

        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)
        factory = RequestFactory()
        payload = [{
            'cost_center_name': 'CC1',
            'position_name': 'Veterinarian',
            'salary': 35000,
            'monthly_data': {
                'jan': {'headcount': 2.5, 'cost': 87500}
            }
        }]
        request = factory.post(
            reverse('budget_add'),
            data=json.dumps(payload),
            content_type='application/json'
        )
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.username = 'test_vet_user'

        response = budget_add_view(request)
        self.assertEqual(response.status_code, 200)
        res_json = json.loads(response.content)
        self.assertEqual(res_json.get('status'), 'error')
        self.assertIn('จำนวนเต็มเท่านั้น', res_json.get('message', ''))

    @patch('budget_app.models.SystemSettings.load')
    def test_vet_manpower_api_rejects_leading_zero_headcount(self, mock_settings):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.views import budget_add_view

        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)
        factory = RequestFactory()
        payload = [{
            'cost_center_name': 'CC1',
            'position_name': 'Veterinarian',
            'salary': 35000,
            'monthly_data': {
                'jan': {'headcount': '03', 'cost': 105000}
            }
        }]
        request = factory.post(
            reverse('budget_add'),
            data=json.dumps(payload),
            content_type='application/json'
        )
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.username = 'test_vet_user'

        response = budget_add_view(request)
        self.assertEqual(response.status_code, 200)
        res_json = json.loads(response.content)
        self.assertEqual(res_json.get('status'), 'error')
        self.assertIn('ไม่อนุญาตให้ระบุรูปแบบที่มีเลข 0 นำหน้า', res_json.get('message', ''))
        self.assertIn('03', res_json.get('message', ''))

    @patch('budget_app.models.SystemSettings.load')
    def test_fix_asset_equipment_api_rejects_decimal_and_leading_zeros(self, mock_settings):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.views import budget_add_medical_equipment_view

        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)
        factory = RequestFactory()

        # 1. Decimal test
        payload_dec = [{
            'cost_center_name': 'CC1',
            'item_name': 'Medical Ultrasound',
            'purchase_price': 250000,
            'monthly_data': {
                'jan': {'headcount': 1.5, 'cost': 375000}
            }
        }]
        req_dec = factory.post(
            reverse('budget_add_medical_equipment'),
            data=json.dumps(payload_dec),
            content_type='application/json'
        )
        req_dec.user = MagicMock()
        req_dec.user.is_authenticated = True
        req_dec.user.username = 'test_user'

        res_dec = budget_add_medical_equipment_view(req_dec)
        self.assertEqual(res_dec.status_code, 200)
        self.assertEqual(json.loads(res_dec.content).get('status'), 'error')
        self.assertIn('จำนวนเต็มเท่านั้น', json.loads(res_dec.content).get('message', ''))

        # 2. Leading zero test
        payload_lz = [{
            'cost_center_name': 'CC1',
            'item_name': 'Medical Ultrasound',
            'purchase_price': 250000,
            'monthly_data': {
                'jan': {'headcount': '05', 'cost': 1250000}
            }
        }]
        req_lz = factory.post(
            reverse('budget_add_medical_equipment'),
            data=json.dumps(payload_lz),
            content_type='application/json'
        )
        req_lz.user = MagicMock()
        req_lz.user.is_authenticated = True
        req_lz.user.username = 'test_user'

        res_lz = budget_add_medical_equipment_view(req_lz)
        self.assertEqual(res_lz.status_code, 200)
        self.assertEqual(json.loads(res_lz.content).get('status'), 'error')
        self.assertIn('ไม่อนุญาตให้ระบุรูปแบบที่มีเลข 0 นำหน้า', json.loads(res_lz.content).get('message', ''))
        self.assertIn('05', json.loads(res_lz.content).get('message', ''))

    def test_templates_enforce_dropdown_only_and_warn_on_static_text(self):
        """Verifies that all MAN POWER and FIX ASSET templates check dropdown item validity and block static text."""
        from pathlib import Path
        templates_to_check = [
            'budget_add.html',
            'budget_add_non_vet.html',
            'budget_add_adjustment.html',
            'budget_add_medical_equipment.html',
            'budget_add_computer_equipment.html',
            'budget_add_furniture.html',
            'budget_add_tools_equipment.html',
            'budget_add_car.html',
            'budget_add_renovate.html',
            'budget_add_software.html',
        ]
        templates_dir = Path(__file__).resolve().parent / 'templates' / 'budget_app'
        for tmpl in templates_to_check:
            tmpl_path = templates_dir / tmpl
            content = tmpl_path.read_text(encoding='utf-8')
            self.assertIn('ไม่อนุญาตให้พิมพ์ระบุข้อความเอง', content, f"{tmpl} missing static text disallow warning")
            self.assertIn('Dropdown', content, f"{tmpl} missing dropdown mention in warning")
            # Verify that typed text is cleared from the cell on invalid entry
            if tmpl == 'budget_add_adjustment.html':
                self.assertIn("table1.setValueFromCoords(0, y, '', true)", content)
                self.assertIn("table1.setValueFromCoords(1, y, '', true)", content)
                self.assertIn("table1.setValueFromCoords(3, y, '', true)", content)
            else:
                self.assertIn("table1.setValueFromCoords(0, y, '', true)", content)

        # Also verify budget_list.js clearing logic for document detail modal
        js_path = Path(__file__).resolve().parent / 'static' / 'budget_app' / 'js' / 'budget_list.js'
        js_content = js_path.read_text(encoding='utf-8')
        self.assertIn("modalTable1.setValueFromCoords(0, y, '', true)", js_content)
        self.assertIn("adjTable1.setValueFromCoords(0, y, '', true)", js_content)
        self.assertIn("adjTable1.setValueFromCoords(1, y, '', true)", js_content)
        self.assertIn("adjTable1.setValueFromCoords(3, y, '', true)", js_content)

    @patch('budget_app.models.SystemSettings.load')
    @patch('budget_app.services.BudgetService.get_master_fks_bulk')
    def test_manpower_api_rejects_static_position_not_in_dropdown(self, mock_fks, mock_settings):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.views import budget_add_view, budget_add_non_vet_view

        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)
        mock_fks.return_value = {}  # Empty master data: any typed position will fail
        factory = RequestFactory()

        # VET test
        req_vet = factory.post(
            reverse('budget_add'),
            data=json.dumps([{
                'cost_center_name': 'CC1',
                'position_name': 'แพทย์นอกระบบ',
                'salary': 50000,
                'monthly_data': {'jan': {'headcount': 1, 'cost': 50000}}
            }]),
            content_type='application/json'
        )
        req_vet.user = MagicMock(is_authenticated=True, username='test_user')
        req_vet.session = {}
        res_vet = budget_add_view(req_vet)
        self.assertEqual(res_vet.status_code, 200)
        res_vet_json = json.loads(res_vet.content)
        self.assertEqual(res_vet_json.get('status'), 'error')
        self.assertIn('ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกตำแหน่งจากรายการ Dropdown เท่านั้น', res_vet_json.get('message', ''))

        # NON VET test
        req_non_vet = factory.post(
            reverse('budget_add_non_vet'),
            data=json.dumps([{
                'cost_center_name': 'CC1',
                'position_name': 'เจ้าหน้าที่ชั่วคราว',
                'salary': 20000,
                'monthly_data': {'jan': {'headcount': 1, 'cost': 20000}}
            }]),
            content_type='application/json'
        )
        req_non_vet.user = MagicMock(is_authenticated=True, username='test_user')
        req_non_vet.session = {}
        res_non_vet = budget_add_non_vet_view(req_non_vet)
        self.assertEqual(res_non_vet.status_code, 200)
        res_nv_json = json.loads(res_non_vet.content)
        self.assertEqual(res_nv_json.get('status'), 'error')
        self.assertIn('ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกตำแหน่งจากรายการ Dropdown เท่านั้น', res_nv_json.get('message', ''))

    @patch('budget_app.models.SystemSettings.load')
    @patch('budget_app.services.BudgetService.get_master_fks_bulk')
    def test_position_adjustment_api_rejects_static_type_or_position(self, mock_fks, mock_settings):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.views import budget_add_adjustment_view

        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)
        mock_fks.return_value = {'ตำแหน่งเดิมแท้': (MagicMock(), 'GL01')}
        factory = RequestFactory()

        # Invalid adjustment_type
        req_type = factory.post(
            reverse('budget_add_adjustment'),
            data=json.dumps([{
                'cost_center_name': 'CC1',
                'adjustment_type': 'INVALID_TYPE',
                'old_position_name': 'ตำแหน่งเดิมแท้',
                'new_position_name': 'ตำแหน่งใหม่แท้',
                'old_salary': 30000,
                'old_allowance': 0,
                'new_salary': 40000,
                'new_allowance': 0,
                'monthly_data': {'jan': {'headcount': 1, 'cost': 10000}}
            }]),
            content_type='application/json'
        )
        req_type.user = MagicMock(is_authenticated=True, username='test_user')
        req_type.session = {}
        res_type = budget_add_adjustment_view(req_type)
        self.assertEqual(res_type.status_code, 200)
        self.assertIn('ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกประเภท (VET หรือ NON VET)', json.loads(res_type.content).get('message', ''))

        # Static position not in master data
        req_pos = factory.post(
            reverse('budget_add_adjustment'),
            data=json.dumps([{
                'cost_center_name': 'CC1',
                'adjustment_type': 'VET',
                'old_position_name': 'ตำแหน่งเดิมแท้',
                'new_position_name': 'ตำแหน่งพิมพ์เอง',
                'old_salary': 30000,
                'old_allowance': 0,
                'new_salary': 40000,
                'new_allowance': 0,
                'monthly_data': {'jan': {'headcount': 1, 'cost': 10000}}
            }]),
            content_type='application/json'
        )
        req_pos.user = MagicMock(is_authenticated=True, username='test_user')
        req_pos.session = {}
        res_pos = budget_add_adjustment_view(req_pos)
        self.assertEqual(res_pos.status_code, 200)
        self.assertIn('ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกตำแหน่งใหม่จากรายการ Dropdown เท่านั้น', json.loads(res_pos.content).get('message', ''))

    @patch('budget_app.models.SystemSettings.load')
    @patch('budget_app.services.BudgetService.get_master_fks_bulk')
    def test_fix_asset_equipment_api_rejects_static_item_not_in_dropdown(self, mock_fks, mock_settings):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.views import budget_add_computer_equipment_view

        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)
        mock_fks.return_value = {}  # Empty master data
        factory = RequestFactory()

        req = factory.post(
            reverse('budget_add_computer_equipment'),
            data=json.dumps([{
                'cost_center_name': 'CC1',
                'item_name': 'คอมพิวเตอร์ประกอบเอง',
                'purchase_price': 35000,
                'monthly_data': {'jan': {'headcount': 1, 'cost': 35000}}
            }]),
            content_type='application/json'
        )
        req.user = MagicMock(is_authenticated=True, username='test_user')
        req.session = {}
        res = budget_add_computer_equipment_view(req)
        self.assertEqual(res.status_code, 200)
        res_json = json.loads(res.content)
        self.assertEqual(res_json.get('status'), 'error')
        self.assertIn('ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกรายการจาก Dropdown เท่านั้น', res_json.get('message', ''))


class BudgetListDocumentPermissionTests(SimpleTestCase):
    """Test permission rules for editing and cancelling documents in budget list:
    - Regular users can edit/cancel only documents they created themselves.
    - Privileged users (nattchai_u, kanchana, kanchana_a, pattida_y, superuser)
      can edit/cancel both their own documents and other people's documents.
    """

    def test_constants_privileged_usernames(self):
        self.assertIn('nattchai_u', ALL_BRANCH_USERNAMES)
        self.assertIn('kanchana', ALL_BRANCH_USERNAMES)
        self.assertIn('kanchana_a', ALL_BRANCH_USERNAMES)
        self.assertIn('pattida_y', ALL_BRANCH_USERNAMES)

    @patch('budget_app.models.SystemSettings.load')
    def test_context_processor_permissions(self, mock_settings):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.context_processors import site_status

        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)
        factory = RequestFactory()

        # Anonymous user
        req_anon = factory.get('/')
        req_anon.user = MagicMock(is_authenticated=False)
        ctx_anon = site_status(req_anon)
        self.assertFalse(ctx_anon['can_edit_own_documents'])
        self.assertFalse(ctx_anon['is_privileged_user'])

        # Regular user
        req_reg = factory.get('/')
        req_reg.user = MagicMock(is_authenticated=True, username='somchai', is_superuser=False)
        req_reg.session = {'branch_info': {'is_executive_view_only': False}}
        ctx_reg = site_status(req_reg)
        self.assertTrue(ctx_reg['can_edit_own_documents'])
        self.assertFalse(ctx_reg['is_privileged_user'])

        # Privileged users
        for priv_username in ['nattchai_u', 'kanchana', 'kanchana_a', 'pattida_y']:
            req_priv = factory.get('/')
            req_priv.user = MagicMock(is_authenticated=True, username=priv_username, is_superuser=False)
            ctx_priv = site_status(req_priv)
            self.assertTrue(ctx_priv['can_edit_own_documents'])
            self.assertTrue(ctx_priv['is_privileged_user'], f"{priv_username} should be privileged")

        # Superuser
        req_admin = factory.get('/')
        req_admin.user = MagicMock(is_authenticated=True, username='admin', is_superuser=True)
        ctx_admin = site_status(req_admin)
        self.assertTrue(ctx_admin['can_edit_own_documents'])
        self.assertTrue(ctx_admin['is_privileged_user'])

    @patch('django.db.transaction.atomic')
    @patch('budget_app.models.SystemSettings.load')
    @patch('budget_app.views._resolve_model_class')
    def test_cancel_document_api_permissions(self, mock_resolve, mock_settings, mock_atomic):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.views import cancel_document_api

        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)
        mock_model = MagicMock()
        mock_resolve.return_value = mock_model
        factory = RequestFactory()

        # Doc created by 'user_a' in PENDING status
        mock_doc = MagicMock(create_eid='user_a', status='PENDING')
        mock_model.objects.filter.return_value.first.return_value = mock_doc

        # Regular user 'user_b' tries to cancel user_a's doc -> REJECTED
        req_b = factory.post('/api/document/cancel/VET/DOC001/', data=json.dumps({'cancel_reason': 'test'}), content_type='application/json')
        req_b.user = MagicMock(is_authenticated=True, username='user_b', is_superuser=False)
        req_b.session = {'branch_info': {'is_executive_view_only': False}}
        res_b = cancel_document_api(req_b, 'VET', 'DOC001')
        self.assertEqual(res_b.status_code, 200)
        self.assertEqual(json.loads(res_b.content).get('message'), 'คุณยกเลิกได้เฉพาะเอกสารที่ตัวเองสร้างเท่านั้น')

        # Regular user 'user_a' cancels their own doc -> ALLOWED
        req_a = factory.post('/api/document/cancel/VET/DOC001/', data=json.dumps({'cancel_reason': 'test'}), content_type='application/json')
        req_a.user = MagicMock(is_authenticated=True, username='user_a', is_superuser=False)
        req_a.session = {'branch_info': {'is_executive_view_only': False}}
        res_a = cancel_document_api(req_a, 'VET', 'DOC001')
        self.assertEqual(res_a.status_code, 200)
        self.assertEqual(json.loads(res_a.content).get('status'), 'success')

        # Privileged user 'nattchai_u' cancels user_a's doc -> ALLOWED
        req_priv = factory.post('/api/document/cancel/VET/DOC001/', data=json.dumps({'cancel_reason': 'test'}), content_type='application/json')
        req_priv.user = MagicMock(is_authenticated=True, username='nattchai_u', is_superuser=False)
        res_priv = cancel_document_api(req_priv, 'VET', 'DOC001')
        self.assertEqual(res_priv.status_code, 200)
        self.assertEqual(json.loads(res_priv.content).get('status'), 'success')

        # Privileged user 'kanchana' cancels user_a's doc -> ALLOWED
        req_kanchana = factory.post('/api/document/cancel/VET/DOC001/', data=json.dumps({'cancel_reason': 'test'}), content_type='application/json')
        req_kanchana.user = MagicMock(is_authenticated=True, username='kanchana', is_superuser=False)
        res_kanchana = cancel_document_api(req_kanchana, 'VET', 'DOC001')
        self.assertEqual(res_kanchana.status_code, 200)
        self.assertEqual(json.loads(res_kanchana.content).get('status'), 'success')

        # Privileged user 'pattida_y' cancels user_a's doc -> ALLOWED
        req_pattida = factory.post('/api/document/cancel/VET/DOC001/', data=json.dumps({'cancel_reason': 'test'}), content_type='application/json')
        req_pattida.user = MagicMock(is_authenticated=True, username='pattida_y', is_superuser=False)
        res_pattida = cancel_document_api(req_pattida, 'VET', 'DOC001')
        self.assertEqual(res_pattida.status_code, 200)
        self.assertEqual(json.loads(res_pattida.content).get('status'), 'success')

    @patch('budget_app.views.get_branch_info')
    @patch('budget_app.services.BudgetService.save_monthly_data')
    @patch('budget_app.services.BudgetService.get_master_fks_bulk')
    @patch('budget_app.models.ebudget_vet_manpower.objects')
    @patch('django.db.transaction.atomic')
    @patch('budget_app.models.SystemSettings.load')
    def test_update_document_api_permissions(self, mock_settings, mock_atomic, mock_objects, mock_fks, mock_save_monthly, mock_branch_info):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.views import update_document_api

        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)
        mock_branch_info.return_value = {'is_manager': True, 'branch_codes': ['B01'], 'needs_selection': False}
        mock_fks.return_value = {'Vet Nurse': (1, 1)}
        factory = RequestFactory()

        # Doc created by 'user_a' in PENDING status
        mock_doc = MagicMock(create_eid='user_a', status='PENDING', create_date='2026-01-01', department_id=1)
        mock_objects.filter.return_value.exists.return_value = True
        mock_objects.filter.return_value.first.return_value = mock_doc

        sample_data = [{
            'cost_center_name': 'CC1',
            'position_name': 'Vet Nurse',
            'salary': 15000,
            'position_allowance': 0,
            'monthly_data': {'jan': {'headcount': 1, 'cost': 15000}}
        }]

        # Regular user 'user_b' tries to update user_a's doc -> REJECTED
        req_b = factory.post('/api/document/update/VET/DOC001/', data=json.dumps(sample_data), content_type='application/json')
        req_b.user = MagicMock(is_authenticated=True, username='user_b', is_superuser=False)
        req_b.session = {'branch_info': {'is_executive_view_only': False}}
        res_b = update_document_api(req_b, 'VET', 'DOC001')
        self.assertEqual(res_b.status_code, 200)
        self.assertEqual(json.loads(res_b.content).get('message'), 'คุณแก้ไขได้เฉพาะเอกสารที่ตัวเองสร้างเท่านั้น')

        # Privileged user 'nattchai_u' updates user_a's doc -> ALLOWED past permission gate
        req_priv = factory.post('/api/document/update/VET/DOC001/', data=json.dumps(sample_data), content_type='application/json')
        req_priv.user = MagicMock(is_authenticated=True, username='nattchai_u', is_superuser=False)
        req_priv.session = {}
        res_priv = update_document_api(req_priv, 'VET', 'DOC001')
        self.assertEqual(res_priv.status_code, 200)
        self.assertEqual(json.loads(res_priv.content).get('status'), 'success', f"Got: {res_priv.content.decode('utf-8')}")

    def test_document_detail_modal_status_column_visibility_contract(self):
        """In document detail modals, the 'สถานะ' column must only be shown when the status
        is CANCELLED ('ยกเลิก'). For all other statuses (PENDING, APPROVED, etc.), the column
        must remain hidden."""
        html_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_list.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            html_content = f.read()

        # All 4 modals must have th and td hidden by default
        for th_id, td_id in [
            ('modalDocStatusTh', 'modalDocStatus'),
            ('adjModalDocStatusTh', 'adjModalDocStatus'),
            ('glModalDocStatusTh', 'glModalDocStatus'),
            ('glatModalDocStatusTh', 'glatModalDocStatus')
        ]:
            self.assertIn(f'<th id="{th_id}" style="display: none;">สถานะ</th>', html_content)
            self.assertIn(f'<td id="{td_id}" style="display: none;"></td>', html_content)

        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        # JavaScript helper must exist and specifically show only when CANCELLED
        self.assertIn('function renderModalDocStatus(thEl, tdEl, status)', js_content)
        self.assertIn("status === 'CANCELLED'", js_content)
        self.assertIn("thEl.style.display = ''", js_content)
        self.assertIn("tdEl.style.display = ''", js_content)
        self.assertIn("thEl.style.display = 'none'", js_content)
        self.assertIn("tdEl.style.display = 'none'", js_content)

    def test_budget_list_table_cancelled_badge_contract(self):
        """In the budget list table, cancelled documents must display a modern soft-red
        badge with an x-circle icon beside the Document No, strike through the budget
        amount, and keep the Action column cleanly centered with the view button."""
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        self.assertIn("const isCancelled = doc.status === 'CANCELLED';", js_content)
        self.assertIn("const docNoCell = isCancelled ?", js_content)
        self.assertIn('#fee2e2', js_content)
        self.assertIn('#dc2626', js_content)
        self.assertIn('data-feather="x-circle"', js_content)
        self.assertIn('ยกเลิก', js_content)
        self.assertIn('text-decoration-line-through text-muted', js_content)
        self.assertIn('<th class="text-center text-nowrap" style="width: 80px;">Action</th>', js_content)

    def test_add_budget_sticky_header_contract(self):
        """All 14 Add Budget pages must have their Save and Back buttons in the main table
        card header with the eb-sticky-header class, and not in the page-header banner."""
        import glob
        templates = sorted(glob.glob(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add*.html')))
        self.assertEqual(len(templates), 14, "Must cover all 14 Add Budget templates")

        for tmpl_path in templates:
            fname = os.path.basename(tmpl_path)
            with open(tmpl_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 1. Must use eb-sticky-header on card-header
            self.assertIn('eb-sticky-header', content, f"{fname} must have eb-sticky-header class on card-header")

            # 2. Page header banner must NOT contain save button
            ph_split = content.find('mt-n10')
            self.assertGreater(ph_split, 0, f"{fname} must have mt-n10 container divider")
            ph_content = content[:ph_split]
            self.assertNotIn('id="save-budget-btn"', ph_content, f"{fname} page-header must not contain save-budget-btn")

            # 3. Main card header must contain save button and back link
            self.assertIn('id="save-budget-btn"', content, f"{fname} must contain save-budget-btn")
            self.assertIn("href=\"{% url 'budget_list' %}\"", content, f"{fname} must contain back button to budget_list")

        # 4. polish.css must define eb-sticky-header with sticky positioning
        css_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'css', 'polish.css')
        with open(css_path, 'r', encoding='utf-8') as f:
            css_content = f.read()
        self.assertIn('.eb-sticky-header', css_content)
        self.assertIn('position: sticky;', css_content)
        self.assertIn('top: 3.625rem;', css_content)

    def test_budget_list_detail_modal_calculation_tables_readonly_contract(self):
        """In Budget List document detail modals, when entering edit mode, Table 2 (and Table 3
        in Position Adjustment) must strictly be read-only calculation tables that sync from
        Table 1, matching the Add Budget pages (calcColumns). They must not allow direct edits."""
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        # 1. Standard Detail Modal (toggleEditMode) Table 2:
        self.assertIn('modalTable2 = jspreadsheet(document.getElementById(\'modalSpreadsheet2\'), {', js_content)
        self.assertIn('columns: calcColumns,', js_content)
        self.assertIn('calcColumns.push({ type: \'numeric\', title: m, width: 85, readOnly: true, mask: isEquipment ? \'#,##0.00\' : \'#,##0\' });', js_content)

        # 2. Position Adjustment Modal (toggleAdjEditMode) Table 2 and Table 3:
        self.assertIn('adjTable2 = jspreadsheet(document.getElementById(\'adjModalSpreadsheet2\'), {', js_content)
        self.assertIn('columns: cols2,', js_content)
        self.assertIn('adjTable3 = jspreadsheet(document.getElementById(\'adjModalSpreadsheet3\'), {', js_content)
        self.assertIn('columns: cols3,', js_content)

        # Check cols2 and cols3 definitions have readOnly: true on all columns
        self.assertIn('{ type: \'numeric\', title: \'ผลต่างเงินเดือน\', width: 110, readOnly: true, mask: \'#,##0\' }', js_content)
        self.assertIn('{ type: \'numeric\', title: \'ผลต่างค่าตำแหน่ง\', width: 120, readOnly: true, mask: \'#,##0\' }', js_content)

        # 3. Both insert and delete row hooks must sync Table 1 to Table 2 and Table 3
        self.assertIn('if (adjTable2) adjTable2.deleteRow(rowNumber, numOfRows);', js_content)
        self.assertIn('if (adjTable3) adjTable3.deleteRow(rowNumber, numOfRows);', js_content)

    def test_budget_list_detail_modal_no_auto_open_dropdown_on_selection(self):
        """In Budget List detail modals, entering edit mode must not auto-open the dropdown
        via onselection or trap keyboard/mouse clicks in column 0 when clicking other columns."""
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()

        # Verify onselection is configured for targeted dropdown cells
        self.assertIn("onselection: function(el, x1, y1, x2, y2, origin) {", js_content)

        # Must have resetSelection and clean click listener bound for dropdown cells
        self.assertIn('modalTable1.resetSelection(true);', js_content)
        self.assertIn('adjTable1.resetSelection(true);', js_content)
        self.assertIn("e.target.closest('td.eb-dropdown-cell')", js_content)

    def test_position_adjustment_sticky_header_across_all_tables_contract(self):
        """In Position Adjustment Add page, Table 1, Table 2, and Table 3 must be unified
        inside #adjustment-tables-card with .eb-sticky-header as its primary header so that
        the sticky header and its action buttons (Back, Add Row, Save) remain frozen across
        all three tables when scrolling down to the bottom."""
        tmpl_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_adjustment.html')
        with open(tmpl_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 1. Must have unified card enclosing all tables
        self.assertIn('id="adjustment-tables-card"', content)
        self.assertIn('id="adjustment-sticky-title"', content)

        # 2. Section headers for Table 2 and Table 3 must be present inside the card
        self.assertIn('id="header-table-2"', content)
        self.assertIn('id="header-table-3"', content)

        # 3. Dynamic title update script must be present
        self.assertIn("updateStickyTitle", content)
        self.assertIn("headerTable2.getBoundingClientRect()", content)
        self.assertIn("headerTable3.getBoundingClientRect()", content)

    def test_add_budget_cost_center_dropdown_zindex_contract(self):
        """On all Add Budget pages, Cost Center / Configuration dropdowns must float cleanly
        above .eb-sticky-header (z-index: 1020) so that floating options are never covered
        or clipped by table headers. The selector card must have z-index: 1025 and dropdown
        z-index: 1030, which are also safely below .topnav (1039) for smooth page scrolling."""
        import glob
        templates = sorted(glob.glob(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add*.html')))
        self.assertEqual(len(templates), 14, "Must cover all 14 Add Budget templates")

        for tmpl_path in templates:
            fname = os.path.basename(tmpl_path)
            with open(tmpl_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Each template must include eb-cost-center-card on the card enclosing the selector body
            self.assertIn(
                'eb-cost-center-card',
                content,
                f"{fname} must have eb-cost-center-card class on the selector card"
            )

        # polish.css must define proper stacking context rules
        css_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'css', 'polish.css')
        with open(css_path, 'r', encoding='utf-8') as f:
            css = f.read()

        self.assertIn('.eb-cost-center-card', css)
        self.assertIn('.card:has(#cost-center-card-body)', css)
        self.assertIn('.card:has(#config-card-body)', css)
        self.assertIn('z-index: 1025;', css)
        self.assertIn('overflow: visible !important;', css)
        self.assertIn('#cost-center-card-body .ts-dropdown', css)
        self.assertIn('#config-card-body .ts-dropdown', css)
        self.assertIn('z-index: 1030 !important;', css)


class ImedxAuthBackendTests(SimpleTestCase):
    """Verifies that ImedxAuthBackend enforces presence of bank_sub_name
    and bank_account_note, checks active status, and avoids info leaks."""

    def test_missing_credentials_returns_none(self):
        backend = ImedxAuthBackend()
        self.assertIsNone(backend.authenticate(None, username=None, password='123'))
        self.assertIsNone(backend.authenticate(None, username='user', password=None))

    @patch('budget_app.backends.connections')
    def test_invalid_password_returns_none_without_setting_failure_reason(self, mock_connections):
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        correct_hash = hashlib.md5(b'correct_pw').hexdigest()
        mock_cursor.fetchone.return_value = ('emp01', correct_hash, 'นาย', 'สมชาย', 'ใจดี', '', '', '1')

        backend = ImedxAuthBackend()
        request = type('Request', (), {})()
        result = backend.authenticate(request, username='emp01', password='wrong_password')

        self.assertIsNone(result)
        self.assertFalse(hasattr(request, 'auth_failure_reason'))

    @patch('budget_app.backends.connections')
    def test_inactive_employee_blocked(self, mock_connections):
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        pw_hash = hashlib.md5(b'mypassword').hexdigest()
        mock_cursor.fetchone.return_value = ('emp01', pw_hash, 'นาย', 'สมชาย', 'ใจดี', 'BACK-IT', 'IT', '0')

        backend = ImedxAuthBackend()
        request = type('Request', (), {})()
        result = backend.authenticate(request, username='emp01', password='mypassword')

        self.assertIsNone(result)
        self.assertEqual(getattr(request, 'auth_failure_reason', None), 'inactive_employee')

    @patch('budget_app.backends.connections')
    @patch('budget_app.backends.User.objects.filter')
    def test_missing_both_fields_blocked(self, mock_user_filter, mock_connections):
        mock_user_filter.return_value.exists.return_value = False
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        pw_hash = hashlib.md5(b'mypassword').hexdigest()
        mock_cursor.fetchone.return_value = ('emp01', pw_hash, 'นาย', 'สมชาย', 'ใจดี', '', '   ', '1')

        backend = ImedxAuthBackend()
        request = type('Request', (), {})()
        result = backend.authenticate(request, username='emp01', password='mypassword')

        self.assertIsNone(result)
        self.assertEqual(getattr(request, 'auth_failure_reason', None), 'missing_imedx_profile')
        self.assertEqual(getattr(request, 'auth_missing_fields', []), ['bank_sub_name', 'bank_account_note'])

    @patch('budget_app.backends.connections')
    @patch('budget_app.backends.User.objects.filter')
    def test_missing_sub_name_only_blocked(self, mock_user_filter, mock_connections):
        mock_user_filter.return_value.exists.return_value = False
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        pw_hash = hashlib.md5(b'mypassword').hexdigest()
        mock_cursor.fetchone.return_value = ('emp01', pw_hash, 'นาย', 'สมชาย', 'ใจดี', None, 'IT', '1')

        backend = ImedxAuthBackend()
        request = type('Request', (), {})()
        result = backend.authenticate(request, username='emp01', password='mypassword')

        self.assertIsNone(result)
        self.assertEqual(getattr(request, 'auth_failure_reason', None), 'missing_imedx_profile')
        self.assertEqual(getattr(request, 'auth_missing_fields', []), ['bank_sub_name'])

    @patch('budget_app.backends.connections')
    @patch('budget_app.backends.User.objects.filter')
    def test_missing_account_note_only_blocked(self, mock_user_filter, mock_connections):
        mock_user_filter.return_value.exists.return_value = False
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        pw_hash = hashlib.md5(b'mypassword').hexdigest()
        mock_cursor.fetchone.return_value = ('emp01', pw_hash, 'นาย', 'สมชาย', 'ใจดี', 'BACK-IT', '', '1')

        backend = ImedxAuthBackend()
        request = type('Request', (), {})()
        result = backend.authenticate(request, username='emp01', password='mypassword')

        self.assertIsNone(result)
        self.assertEqual(getattr(request, 'auth_failure_reason', None), 'missing_imedx_profile')
        self.assertEqual(getattr(request, 'auth_missing_fields', []), ['bank_account_note'])

    @patch('budget_app.backends.connections')
    @patch('budget_app.backends.User.objects.filter')
    def test_superuser_with_missing_profile_is_blocked(self, mock_user_filter, mock_connections):
        mock_user_filter.return_value.exists.return_value = True
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        pw_hash = hashlib.md5(b'mypassword').hexdigest()
        mock_cursor.fetchone.return_value = ('superadmin', pw_hash, 'นาย', 'แอด', 'มิน', '', '', '1')

        backend = ImedxAuthBackend()
        request = type('Request', (), {})()
        result = backend.authenticate(request, username='superadmin', password='mypassword')

        self.assertIsNone(result)
        self.assertEqual(getattr(request, 'auth_failure_reason', None), 'missing_imedx_profile')
        self.assertEqual(getattr(request, 'auth_missing_fields', []), ['bank_sub_name', 'bank_account_note'])

    @patch('budget_app.backends.connections')
    @patch('budget_app.backends.User.objects.filter')
    @patch('budget_app.backends.User.objects.get_or_create')
    def test_valid_profile_authenticates_successfully(self, mock_get_or_create, mock_user_filter, mock_connections):
        mock_user_filter.return_value.exists.return_value = False
        mock_user = type('User', (), {'first_name': '', 'last_name': '', 'save': lambda self: None, 'set_unusable_password': lambda self: None})()
        mock_get_or_create.return_value = (mock_user, False)
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        pw_hash = hashlib.md5(b'mypassword').hexdigest()
        mock_cursor.fetchone.return_value = ('emp01', pw_hash, 'นาย', 'สมชาย', 'ใจดี', 'BACK-IT', 'IT', '1')

        backend = ImedxAuthBackend()
        request = type('Request', (), {})()
        result = backend.authenticate(request, username='emp01', password='mypassword')

        self.assertIsNotNone(result)


class LoginViewAuthWarningTests(SimpleTestCase):
    """Verifies that login_view renders appropriate professional warning
    popups when authentication fails due to missing profile fields or inactive status."""

    @patch('budget_app.views.authenticate')
    @patch('budget_app.views.messages.error')
    @patch('budget_app.views.render')
    def test_missing_profile_both_fields_warning_message(self, mock_render, mock_msg_error, mock_auth):
        def fake_auth(request, username=None, password=None):
            request.auth_failure_reason = 'missing_imedx_profile'
            request.auth_missing_fields = ['bank_sub_name', 'bank_account_note']
            return None
        mock_auth.side_effect = fake_auth

        factory = RequestFactory()
        request = factory.post(reverse('login'), {'employee_id': 'emp01', 'password': 'pass'})

        login_view(request)

        mock_msg_error.assert_called_once()
        args, kwargs = mock_msg_error.call_args
        msg = args[1]
        self.assertIn('bank_sub_name', msg)
        self.assertIn('bank_account_note', msg)
        self.assertIn('iMedX', msg)
        self.assertIn('E-Budget', msg)
        self.assertIn('imedx_profile', kwargs.get('extra_tags', ''))
        self.assertIn('warning', kwargs.get('extra_tags', ''))

    @patch('budget_app.views.authenticate')
    @patch('budget_app.views.messages.error')
    @patch('budget_app.views.render')
    def test_missing_sub_name_only_warning_message(self, mock_render, mock_msg_error, mock_auth):
        def fake_auth(request, username=None, password=None):
            request.auth_failure_reason = 'missing_imedx_profile'
            request.auth_missing_fields = ['bank_sub_name']
            return None
        mock_auth.side_effect = fake_auth

        factory = RequestFactory()
        request = factory.post(reverse('login'), {'employee_id': 'emp01', 'password': 'pass'})

        login_view(request)

        mock_msg_error.assert_called_once()
        args, kwargs = mock_msg_error.call_args
        msg = args[1]
        self.assertIn('bank_sub_name', msg)
        self.assertNotIn('bank_account_note', msg)

    @patch('budget_app.views.authenticate')
    @patch('budget_app.views.messages.error')
    @patch('budget_app.views.render')
    def test_missing_account_note_only_warning_message(self, mock_render, mock_msg_error, mock_auth):
        def fake_auth(request, username=None, password=None):
            request.auth_failure_reason = 'missing_imedx_profile'
            request.auth_missing_fields = ['bank_account_note']
            return None
        mock_auth.side_effect = fake_auth

        factory = RequestFactory()
        request = factory.post(reverse('login'), {'employee_id': 'emp01', 'password': 'pass'})

        login_view(request)

        mock_msg_error.assert_called_once()
        args, kwargs = mock_msg_error.call_args
        msg = args[1]
        self.assertNotIn('bank_sub_name', msg)
        self.assertIn('bank_account_note', msg)

    @patch('budget_app.views.authenticate')
    @patch('budget_app.views.messages.error')
    @patch('budget_app.views.render')
    def test_inactive_employee_warning_message(self, mock_render, mock_msg_error, mock_auth):
        def fake_auth(request, username=None, password=None):
            request.auth_failure_reason = 'inactive_employee'
            return None
        mock_auth.side_effect = fake_auth

        factory = RequestFactory()
        request = factory.post(reverse('login'), {'employee_id': 'emp01', 'password': 'pass'})

        login_view(request)

        mock_msg_error.assert_called_once()
        args, kwargs = mock_msg_error.call_args
        msg = args[1]
        self.assertIn('Inactive', msg)
        self.assertIn('imedx_inactive', kwargs.get('extra_tags', ''))

    @patch('budget_app.views.authenticate')
    @patch('budget_app.views.messages.error')
    @patch('budget_app.views.render')
    def test_standard_auth_failure_message(self, mock_render, mock_msg_error, mock_auth):
        mock_auth.return_value = None

        factory = RequestFactory()
        request = factory.post(reverse('login'), {'employee_id': 'emp01', 'password': 'pass'})

        login_view(request)

        mock_msg_error.assert_called_once()
        args, kwargs = mock_msg_error.call_args
        msg = args[1]
        self.assertIn('รหัสพนักงานหรือรหัสผ่านไม่ถูกต้อง', msg)
        self.assertEqual(kwargs.get('extra_tags', None), None)

    def test_login_template_swal_configuration(self):
        tmpl_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'login.html')
        with open(tmpl_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('Swal.fire', content)
        self.assertIn('imedx_profile', content)
        self.assertIn('imedx_inactive', content)
        self.assertIn('warning', content)
        self.assertIn('width: 520', content)
        self.assertIn('message|safe|escapejs', content)


class ImedxProfileValidationMiddlewareTests(SimpleTestCase):
    """Verifies that ImedxProfileValidationMiddleware intercepts active sessions
    and logs out users whose bank_sub_name or bank_account_note was deleted in iMedX,
    redirecting them to login with a warning popup message."""

    @patch('budget_app.middleware.connections')
    def test_anonymous_user_is_not_checked(self, mock_connections):
        from django.contrib.auth.models import AnonymousUser
        from django.http import HttpResponse
        from budget_app.middleware import ImedxProfileValidationMiddleware
        middleware = ImedxProfileValidationMiddleware(lambda r: HttpResponse('ok'))
        factory = RequestFactory()
        request = factory.get('/budget_list/')
        request.user = AnonymousUser()
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        mock_connections['imedx'].cursor.assert_not_called()

    @patch('budget_app.middleware.connections')
    def test_local_admin_bypasses_imedx_check(self, mock_connections):
        from django.http import HttpResponse
        from budget_app.middleware import ImedxProfileValidationMiddleware
        middleware = ImedxProfileValidationMiddleware(lambda r: HttpResponse('ok'))
        factory = RequestFactory()
        request = factory.get('/budget_list/')
        request.user = type('User', (), {'is_authenticated': True, 'username': 'admin'})()
        response = middleware(request)
        self.assertEqual(response.status_code, 200)
        mock_connections['imedx'].cursor.assert_not_called()

    @patch('budget_app.middleware.connections')
    @patch('budget_app.middleware.auth.logout')
    @patch('budget_app.middleware.messages.error')
    def test_user_with_deleted_bank_sub_name_is_logged_out_and_redirected(self, mock_msg, mock_logout, mock_connections):
        from django.http import HttpResponse
        from budget_app.middleware import ImedxProfileValidationMiddleware
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        # bank_sub_name is empty ''
        mock_cursor.fetchone.return_value = ('1', '', 'MANAGER')

        middleware = ImedxProfileValidationMiddleware(lambda r: HttpResponse('ok'))
        factory = RequestFactory()
        request = factory.get('/budget_list/')
        request.user = type('User', (), {'is_authenticated': True, 'username': 'nattchai_u'})()
        request.session = {}

        response = middleware(request)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('login'))
        mock_logout.assert_called_once_with(request)
        mock_msg.assert_called_once()
        self.assertIn('bank_sub_name', mock_msg.call_args[0][1])

    @patch('budget_app.middleware.connections')
    @patch('budget_app.middleware.auth.logout')
    def test_api_call_returns_403_json_when_profile_missing(self, mock_logout, mock_connections):
        from budget_app.middleware import ImedxProfileValidationMiddleware
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = ('1', '', '')

        middleware = ImedxProfileValidationMiddleware(lambda r: HttpResponse('ok'))
        factory = RequestFactory()
        request = factory.get('/api/get_documents/C01/')
        request.user = type('User', (), {'is_authenticated': True, 'username': 'emp01'})()
        request.session = {}

        response = middleware(request)
        self.assertEqual(response.status_code, 403)
        self.assertIn('application/json', response['content-type'])
        mock_logout.assert_called_once_with(request)


class ExecutiveViewOnlyRoleTests(SimpleTestCase):
    """Verifies that employees with bank_account_note in (CHRO, CFO, COO)
    have full visibility to all documents and can view details,
    but cannot cancel or edit documents (both server-side and client-side)."""

    def test_is_executive_role_matching(self):
        self.assertTrue(BudgetService.is_executive_role('CHRO'))
        self.assertTrue(BudgetService.is_executive_role('CFO'))
        self.assertTrue(BudgetService.is_executive_role('COO'))
        self.assertTrue(BudgetService.is_executive_role('chro'))
        self.assertTrue(BudgetService.is_executive_role('  cfo  '))
        self.assertFalse(BudgetService.is_executive_role('MANAGER'))
        self.assertFalse(BudgetService.is_executive_role('IT'))
        self.assertFalse(BudgetService.is_executive_role('ACC'))
        self.assertFalse(BudgetService.is_executive_role(None))
        self.assertFalse(BudgetService.is_executive_role(''))

    @patch('budget_app.services.connections')
    def test_get_branch_info_from_imedx_resolves_executive_flag(self, mock_connections):
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        # Case 1: CHRO
        mock_cursor.fetchone.return_value = ('BACK-ALL', 'CHRO', None)
        info_chro = BudgetService.get_branch_info_from_imedx('sutep')
        self.assertTrue(info_chro['is_executive_view_only'])
        self.assertEqual(info_chro['bank_account_note'], 'CHRO')

        # Case 2: Standard Manager
        mock_cursor.fetchone.return_value = ('BACK-IT', 'MANAGER', None)
        info_mgr = BudgetService.get_branch_info_from_imedx('mgr01')
        self.assertFalse(info_mgr['is_executive_view_only'])
        self.assertTrue(info_mgr['is_manager'])

    def test_is_executive_view_only_user_helper(self):
        factory = RequestFactory()
        user_chro = User(username='sutep')
        user_mgr = User(username='mgr01')
        super_user = User(username='admin', is_superuser=True)

        req_chro = factory.get('/')
        req_chro.user = user_chro
        req_chro.session = {'branch_info': {'is_executive_view_only': True}}
        self.assertTrue(is_executive_view_only_user(req_chro))

        req_mgr = factory.get('/')
        req_mgr.user = user_mgr
        req_mgr.session = {'branch_info': {'is_executive_view_only': False}}
        self.assertFalse(is_executive_view_only_user(req_mgr))

        # Superuser always bypasses
        req_admin = factory.get('/')
        req_admin.user = super_user
        req_admin.session = {'branch_info': {'is_executive_view_only': True}}
        self.assertFalse(is_executive_view_only_user(req_admin))

    def test_visibility_filter_returns_empty_dict_for_executive(self):
        factory = RequestFactory()
        user_chro = User(username='sutep')
        req = factory.get('/')
        req.user = user_chro
        req.session = {'branch_info': {'is_executive_view_only': True}}

        filter_kwargs = get_document_visibility_filter_kwargs(req)
        self.assertEqual(filter_kwargs, {}, "Executive users must have empty filter kwargs to see all documents")

    def test_visibility_filter_scopes_by_creator_for_regular_user(self):
        factory = RequestFactory()
        user_regular = User(username='regular_emp')
        req = factory.get('/')
        req.user = user_regular
        req.session = {'branch_info': {'is_executive_view_only': False}}

        filter_kwargs = get_document_visibility_filter_kwargs(req)
        self.assertEqual(filter_kwargs, {'create_eid': 'regular_emp'}, "Regular users must only see their own documents")

    @patch('budget_app.models.SystemSettings.load')
    def test_cancel_document_api_forbidden_for_executive(self, mock_load):
        mock_settings = type('Settings', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2026})()
        mock_load.return_value = mock_settings

        factory = RequestFactory()
        user_chro = User(username='sutep')
        req = factory.post('/api/document/cancel/VET/DOC001/', data=json.dumps({'cancel_reason': 'test'}), content_type='application/json')
        req.user = user_chro
        req.session = {'branch_info': {'is_executive_view_only': True}}

        response = cancel_document_api(req, 'VET', 'DOC001')
        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        self.assertIn('สิทธิ์ดูข้อมูลเท่านั้น', data['message'])
        self.assertIn('ไม่สามารถยกเลิกเอกสารได้', data['message'])

    @patch('budget_app.models.SystemSettings.load')
    def test_update_document_api_forbidden_for_executive(self, mock_load):
        mock_settings = type('Settings', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2026})()
        mock_load.return_value = mock_settings

        factory = RequestFactory()
        user_chro = User(username='sutep')
        req = factory.post('/api/document/update/VET/DOC001/', data=json.dumps([{'cost_center_name': 'CC1'}]), content_type='application/json')
        req.user = user_chro
        req.session = {'branch_info': {'is_executive_view_only': True}}

        response = update_document_api(req, 'VET', 'DOC001')
        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        self.assertIn('สิทธิ์ดูข้อมูลเท่านั้น', data['message'])
        self.assertIn('ไม่สามารถแก้ไขข้อมูลได้', data['message'])

    @patch('budget_app.models.SystemSettings.load')
    def test_site_status_context_processor_for_executive(self, mock_load):
        mock_settings = type('Settings', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2026})()
        mock_load.return_value = mock_settings

        factory = RequestFactory()
        user_chro = User(username='sutep')
        req = factory.get('/')
        req.user = user_chro
        req.session = {'branch_info': {'is_executive_view_only': True}}

        ctx = site_status(req)
        self.assertTrue(ctx['is_executive_view_only'])
        self.assertFalse(ctx['can_edit_own_documents'])
        self.assertFalse(ctx['is_privileged_user'])
        self.assertFalse(ctx['can_add_budget'])

        # Regular user when system is not frozen
        req_regular = factory.get('/')
        req_regular.user = User(username='reg01')
        req_regular.session = {'branch_info': {'is_executive_view_only': False}}
        ctx_reg = site_status(req_regular)
        self.assertTrue(ctx_reg['can_add_budget'])

    def test_base_and_budget_list_templates_executive_contract(self):
        base_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'base.html')
        with open(base_path, 'r', encoding='utf-8') as f:
            base_content = f.read()
        self.assertIn('data-executive-view-only', base_content)
        self.assertIn('{% if can_add_budget %}', base_content)

        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
        self.assertIn('isExecutiveViewOnly', js_content)
        self.assertIn('applyEditButtonVisibility', js_content)
        self.assertIn('applyCancelButtonVisibility', js_content)

    @patch('budget_app.models.SystemSettings.load')
    def test_base_template_renders_or_hides_add_budget(self, mock_load):
        mock_settings = type('Settings', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2026})()
        mock_load.return_value = mock_settings

        factory = RequestFactory()
        req = factory.get('/')
        req.user = User(username='sutep', first_name='Sutep')
        req.session = {'branch_info': {'is_executive_view_only': True}}

        ctx_base = {
            'user': req.user,
            'request': req,
            'system_frozen': 0,
            'session_idle_timeout_seconds': 1800,
            'active_budget_year': 2026,
            'frozen_message': '',
            'csrf_token': 'dummy',
        }

        # Executive view-only: Add Budget menu is hidden
        ctx_exec = dict(ctx_base, is_executive_view_only=True, can_add_budget=False, is_privileged_user=False)
        out_exec = render_to_string('budget_app/base.html', ctx_exec, request=req)
        self.assertNotIn('<a id="addBudgetToggle"', out_exec)
        self.assertNotIn('id="collapseAddBudget"', out_exec)

        # Normal user: Add Budget menu is visible
        ctx_normal = dict(ctx_base, is_executive_view_only=False, can_add_budget=True, is_privileged_user=False)
        out_normal = render_to_string('budget_app/base.html', ctx_normal, request=req)
        self.assertIn('<a id="addBudgetToggle"', out_normal)
        self.assertIn('id="collapseAddBudget"', out_normal)

    def test_budget_add_view_get_redirects_for_executive(self):
        factory = RequestFactory()
        req = factory.get(reverse('budget_add'))
        req.user = User(username='sutep')
        req.session = {'branch_info': {'is_executive_view_only': True}}

        response = budget_add_view(req)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('budget_list'))

    def test_budget_add_view_post_forbidden_for_executive(self):
        factory = RequestFactory()
        req = factory.post(reverse('budget_add'), data='{}', content_type='application/json')
        req.user = User(username='sutep')
        req.session = {'branch_info': {'is_executive_view_only': True}}

        response = budget_add_view(req)
        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        self.assertIn('สิทธิ์ดูข้อมูลเท่านั้น', data['message'])
        self.assertIn('ไม่สามารถสร้างเอกสารได้', data['message'])

    def test_equipment_add_view_blocked_for_executive(self):
        factory = RequestFactory()
        # GET
        req_get = factory.get(reverse('budget_add_medical_equipment'))
        req_get.user = User(username='sutep')
        req_get.session = {'branch_info': {'is_executive_view_only': True}}
        res_get = _budget_add_equipment_view(req_get, None, 'Medical Equipment', 'budget_app/budget_add_medical_equipment.html', 4)
        self.assertEqual(res_get.status_code, 302)

        # POST
        req_post = factory.post(reverse('budget_add_medical_equipment'), data='{}', content_type='application/json')
        req_post.user = User(username='sutep')
        req_post.session = {'branch_info': {'is_executive_view_only': True}}
        res_post = _budget_add_equipment_view(req_post, None, 'Medical Equipment', 'budget_app/budget_add_medical_equipment.html', 4)
        self.assertEqual(res_post.status_code, 403)
        data = json.loads(res_post.content)
        self.assertIn('สิทธิ์ดูข้อมูลเท่านั้น', data['message'])


class DistrictManagerViewOnlyTests(SimpleTestCase):
    """Verifies that employees with bank_account_note in ('DISTRICT MANAGER', 'DIRECTOR')
    have view-only access across the branches specified in bank_sub_name:
    1. See all documents across all branches listed in their bank_sub_name.
    2. Cannot create documents (Add Budget pages redirected on GET, 403 on POST; menu hidden).
    3. Cannot edit documents (403 on update_document_api, edit button hidden).
    4. Cannot cancel documents (403 on cancel_document_api, cancel button hidden)."""

    def test_is_district_and_view_only_role_matching(self):
        self.assertTrue(BudgetService.is_district_role('DISTRICT MANAGER'))
        self.assertTrue(BudgetService.is_district_role('DIRECTOR'))
        self.assertTrue(BudgetService.is_district_role('district manager'))
        self.assertTrue(BudgetService.is_district_role('  director  '))
        self.assertFalse(BudgetService.is_district_role('MANAGER'))
        self.assertFalse(BudgetService.is_district_role('CHRO'))
        self.assertFalse(BudgetService.is_district_role(''))
        self.assertFalse(BudgetService.is_district_role(None))

        # View-only role matches both Executive and District/Director
        self.assertTrue(BudgetService.is_view_only_role('DISTRICT MANAGER'))
        self.assertTrue(BudgetService.is_view_only_role('DIRECTOR'))
        self.assertTrue(BudgetService.is_view_only_role('CHRO'))
        self.assertTrue(BudgetService.is_view_only_role('CFO'))
        self.assertTrue(BudgetService.is_view_only_role('COO'))
        self.assertFalse(BudgetService.is_view_only_role('MANAGER'))
        self.assertFalse(BudgetService.is_view_only_role('STAFF'))

    @patch('budget_app.services.connections')
    def test_get_branch_info_from_imedx_resolves_district_flag_and_branches(self, mock_connections):
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        # Case: khanitta with DISTRICT MANAGER and multiple branches
        mock_cursor.fetchone.return_value = ('SR,R2,BN,TN,R8,PR,RS,R6,PK,R5', 'DISTRICT MANAGER', None)
        info = BudgetService.get_branch_info_from_imedx('khanitta')
        self.assertTrue(info['is_district_view_only'])
        self.assertTrue(info['is_view_only'])
        self.assertFalse(info['is_executive_view_only'])
        self.assertEqual(info['branches'], ['SR', 'R2', 'BN', 'TN', 'R8', 'PR', 'RS', 'R6', 'PK', 'R5'])
        self.assertEqual(info['bank_account_note'], 'DISTRICT MANAGER')

        # Case: Director
        mock_cursor.fetchone.return_value = ('HO,PM', 'DIRECTOR', None)
        info_dir = BudgetService.get_branch_info_from_imedx('dir01')
        self.assertTrue(info_dir['is_district_view_only'])
        self.assertTrue(info_dir['is_view_only'])
        self.assertFalse(info_dir['is_executive_view_only'])
        self.assertEqual(info_dir['branches'], ['HO', 'PM'])

    def test_is_district_view_only_user_helper(self):
        factory = RequestFactory()
        user_dm = User(username='khanitta')
        user_mgr = User(username='mgr01')
        super_user = User(username='admin', is_superuser=True)

        req_dm = factory.get('/')
        req_dm.user = user_dm
        req_dm.session = {'branch_info': {'is_district_view_only': True, 'is_view_only': True}}
        self.assertTrue(is_district_view_only_user(req_dm))
        self.assertTrue(is_view_only_user(req_dm))

        req_mgr = factory.get('/')
        req_mgr.user = user_mgr
        req_mgr.session = {'branch_info': {'is_district_view_only': False, 'is_view_only': False}}
        self.assertFalse(is_district_view_only_user(req_mgr))
        self.assertFalse(is_view_only_user(req_mgr))

        # Superuser / ALL_BRANCH_USERNAMES always bypass
        req_admin = factory.get('/')
        req_admin.user = super_user
        req_admin.session = {'branch_info': {'is_district_view_only': True, 'is_view_only': True}}
        self.assertFalse(is_district_view_only_user(req_admin))
        self.assertFalse(is_view_only_user(req_admin))

    def test_visibility_filter_scopes_by_branches_for_district_manager(self):
        factory = RequestFactory()
        user_dm = User(username='khanitta')
        req = factory.get('/')
        req.user = user_dm
        req.session = {
            'branch_info': {
                'is_district_view_only': True,
                'is_executive_view_only': False,
                'branches': ['SR', 'R2', 'BN', 'TN', 'R8', 'PR', 'RS', 'R6', 'PK', 'R5']
            }
        }

        filter_kwargs = get_document_visibility_filter_kwargs(req)
        self.assertEqual(filter_kwargs, {
            'base_branch_id__in': ['SR', 'R2', 'BN', 'TN', 'R8', 'PR', 'RS', 'R6', 'PK', 'R5']
        })

    @patch('budget_app.models.SystemSettings.load')
    def test_cancel_document_api_forbidden_for_district_manager(self, mock_load):
        mock_settings = type('Settings', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2026})()
        mock_load.return_value = mock_settings

        factory = RequestFactory()
        user_dm = User(username='khanitta')
        req = factory.post('/api/document/cancel/VET/DOC001/', data=json.dumps({'cancel_reason': 'test'}), content_type='application/json')
        req.user = user_dm
        req.session = {'branch_info': {'is_district_view_only': True, 'is_view_only': True}}

        response = cancel_document_api(req, 'VET', 'DOC001')
        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        self.assertIn('สิทธิ์ดูข้อมูลเท่านั้น', data['message'])
        self.assertIn('ไม่สามารถยกเลิกเอกสารได้', data['message'])

    @patch('budget_app.models.SystemSettings.load')
    def test_update_document_api_forbidden_for_district_manager(self, mock_load):
        mock_settings = type('Settings', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2026})()
        mock_load.return_value = mock_settings

        factory = RequestFactory()
        user_dm = User(username='khanitta')
        req = factory.post('/api/document/update/VET/DOC001/', data=json.dumps([{'cost_center_name': 'CC1'}]), content_type='application/json')
        req.user = user_dm
        req.session = {'branch_info': {'is_district_view_only': True, 'is_view_only': True}}

        response = update_document_api(req, 'VET', 'DOC001')
        self.assertEqual(response.status_code, 403)
        data = json.loads(response.content)
        self.assertEqual(data['status'], 'error')
        self.assertIn('สิทธิ์ดูข้อมูลเท่านั้น', data['message'])
        self.assertIn('ไม่สามารถแก้ไขข้อมูลได้', data['message'])

    @patch('budget_app.models.SystemSettings.load')
    def test_site_status_context_processor_for_district_manager(self, mock_load):
        mock_settings = type('Settings', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2026})()
        mock_load.return_value = mock_settings

        factory = RequestFactory()
        user_dm = User(username='khanitta')
        req = factory.get('/')
        req.user = user_dm
        req.session = {'branch_info': {'is_district_view_only': True, 'is_view_only': True, 'is_executive_view_only': False}}

        ctx = site_status(req)
        self.assertTrue(ctx['is_district_view_only'])
        self.assertTrue(ctx['is_view_only'])
        self.assertFalse(ctx['is_executive_view_only'])
        self.assertFalse(ctx['can_edit_own_documents'])
        self.assertFalse(ctx['is_privileged_user'])
        self.assertFalse(ctx['can_add_budget'])

    def test_budget_add_view_blocked_for_district_manager(self):
        factory = RequestFactory()
        # GET
        req_get = factory.get(reverse('budget_add'))
        req_get.user = User(username='khanitta')
        req_get.session = {'branch_info': {'is_district_view_only': True, 'is_view_only': True}}
        res_get = budget_add_view(req_get)
        self.assertEqual(res_get.status_code, 302)
        self.assertEqual(res_get.url, reverse('budget_list'))

        # POST
        req_post = factory.post(reverse('budget_add'), data='{}', content_type='application/json')
        req_post.user = User(username='khanitta')
        req_post.session = {'branch_info': {'is_district_view_only': True, 'is_view_only': True}}
        res_post = budget_add_view(req_post)
        self.assertEqual(res_post.status_code, 403)
        data = json.loads(res_post.content)
        self.assertEqual(data['status'], 'error')
        self.assertIn('สิทธิ์ดูข้อมูลเท่านั้น', data['message'])
        self.assertIn('ไม่สามารถสร้างเอกสารได้', data['message'])

    def test_equipment_add_view_blocked_for_district_manager(self):
        factory = RequestFactory()
        # GET
        req_get = factory.get(reverse('budget_add_medical_equipment'))
        req_get.user = User(username='khanitta')
        req_get.session = {'branch_info': {'is_district_view_only': True, 'is_view_only': True}}
        res_get = _budget_add_equipment_view(req_get, None, 'Medical Equipment', 'budget_app/budget_add_medical_equipment.html', 4)
        self.assertEqual(res_get.status_code, 302)

        # POST
        req_post = factory.post(reverse('budget_add_medical_equipment'), data='{}', content_type='application/json')
        req_post.user = User(username='khanitta')
        req_post.session = {'branch_info': {'is_district_view_only': True, 'is_view_only': True}}
        res_post = _budget_add_equipment_view(req_post, None, 'Medical Equipment', 'budget_app/budget_add_medical_equipment.html', 4)
        self.assertEqual(res_post.status_code, 403)
        data = json.loads(res_post.content)
        self.assertIn('สิทธิ์ดูข้อมูลเท่านั้น', data['message'])



class VetDocumentDetailModalTests(SimpleTestCase):
    """Verifies that in budget_list:
    1. Table 1 card header in detail modal is dynamically updated to 'ตารางส่วนแรก (กรอกจำนวนชั่วโมง)' for VET.
    2. Column header for VET rate is 'ค่าแรงรายชั่วโมง' with width 130 in both view mode and edit mode.
    3. Other doc types (Equipment, NON VET) retain their expected titles and widths."""

    def setUp(self):
        self.html_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_list.html')
        with open(self.html_path, 'r', encoding='utf-8') as f:
            self.html_content = f.read()

        self.js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(self.js_path, 'r', encoding='utf-8') as f:
            self.js_content = f.read()

    def test_modal_table1_header_has_id_in_html(self):
        self.assertIn('id="modalTable1HeaderTitle"', self.html_content)

    def test_js_updates_table1_header_for_vet(self):
        # Header update in viewDocumentDetails
        self.assertIn("modalTable1Header.innerText = 'ตารางส่วนแรก (กรอกจำนวนชั่วโมง)'", self.js_content)
        # Header update in toggleEditMode
        self.assertIn("modalTable1HeaderTitle", self.js_content)

    def test_js_vet_hourly_wage_column_title_and_width(self):
        # Column title for VET must be 'ค่าแรงรายชั่วโมง'
        self.assertIn("isVet ? 'ค่าแรงรายชั่วโมง' : 'เงินเดือน'", self.js_content)
        # Width for VET must be 150 to prevent text clipping
        self.assertIn("isVet ? 150 : 100", self.js_content)


class VetColumnWidthTests(SimpleTestCase):
    """Verifies that the VET Manpower 'ค่าแรงรายชั่วโมง' column width is 150px
    in both table 1 and table 2 of budget_add.html, and in budget_list.js,
    preventing any text clipping of the Thai characters."""

    def test_budget_add_html_vet_column_width(self):
        add_html_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add.html')
        with open(add_html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Both table 1 and table 2 must use width 150 for 'ค่าแรงรายชั่วโมง'
        self.assertIn("{ type: 'numeric', title: 'ค่าแรงรายชั่วโมง', width: 150, mask: '#,##0' }", content)
        self.assertIn("{ type: 'numeric', title: 'ค่าแรงรายชั่วโมง', width: 150, readOnly: true, mask: '#,##0' }", content)

    def test_budget_list_js_vet_column_width(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # rateOrPriceWidth must be 150 for VET
        self.assertIn("const rateOrPriceWidth = isVet ? 150 : 100;", content)


class DuplicateBudgetDocumentCheckTests(SimpleTestCase):
    """Verifies server-side duplicate budget document detection logic across
    BudgetService, views helper, and views POST handlers."""

    def test_find_existing_budget_document_validation(self):
        from budget_app.services import BudgetService
        # None or invalid parameters must return None immediately
        self.assertIsNone(BudgetService.find_existing_budget_document(None, 'user1', 2025, 'AP'))
        self.assertIsNone(BudgetService.find_existing_budget_document(MagicMock(), '', 2025, 'AP'))
        self.assertIsNone(BudgetService.find_existing_budget_document(MagicMock(), 'user1', 'invalid_year', 'AP'))
        self.assertIsNone(BudgetService.find_existing_budget_document(MagicMock(), 'user1', 2025, ''))

    def test_find_existing_budget_document_queries_correctly(self):
        from budget_app.services import BudgetService
        mock_model = MagicMock()
        mock_qs = MagicMock()
        mock_model.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.first.return_value = {
            'document_no': 'VET-202611-001',
            'budget_year': 2025,
            'base_branch_id': 'AP',
            'status': 'PENDING'
        }

        res = BudgetService.find_existing_budget_document(mock_model, 'nattchai_u', 2025, 'AP')
        self.assertIsNotNone(res)
        self.assertEqual(res['document_no'], 'VET-202611-001')
        mock_model.objects.filter.assert_called_with(
            create_eid__iexact='nattchai_u',
            budget_year=2025,
            base_branch_id__iexact='AP'
        )
        mock_qs.exclude.assert_called_with(status='CANCELLED')

    def test_check_duplicate_budget_document_helper_returns_json_on_duplicate(self):
        from budget_app.views import check_duplicate_budget_document
        with patch('budget_app.services.BudgetService.find_existing_budget_document') as mock_find:
            mock_find.return_value = {
                'document_no': 'VET-202611-001',
                'budget_year': 2025,
                'base_branch_id': 'AP',
                'status': 'PENDING'
            }

            resp = check_duplicate_budget_document(
                model_class=MagicMock(),
                doc_type='VET',
                create_eid='nattchai_u',
                budget_year=2025,
                base_branch_id='AP'
            )
            self.assertIsNotNone(resp)
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertEqual(data['status'], 'duplicate')
            self.assertEqual(data['doc_type'], 'VET')
            self.assertEqual(data['document_no'], 'VET-202611-001')
            self.assertEqual(data['budget_year'], 2025)
            self.assertEqual(data['branch_id'], 'AP')
            self.assertIn('พบเอกสาร VET เลขที่ VET-202611-001', data['message'])

    def test_check_duplicate_budget_document_helper_returns_none_when_no_duplicate(self):
        from budget_app.views import check_duplicate_budget_document
        with patch('budget_app.services.BudgetService.find_existing_budget_document') as mock_find:
            mock_find.return_value = None

            resp = check_duplicate_budget_document(
                model_class=MagicMock(),
                doc_type='VET',
                create_eid='nattchai_u',
                budget_year=2025,
                base_branch_id='AP'
            )
            self.assertIsNone(resp)

    def test_find_existing_budget_document_queries_with_cost_center(self):
        from budget_app.services import BudgetService
        mock_model = MagicMock()
        mock_qs = MagicMock()
        mock_model.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.first.return_value = {
            'document_no': 'VET-202611-001',
            'budget_year': 2025,
            'base_branch_id': 'AP',
            'cost_center_name': '0000: Center',
            'status': 'PENDING'
        }

        res = BudgetService.find_existing_budget_document(
            mock_model,
            create_eid='nattchai_u',
            budget_year=2025,
            base_branch_id='AP',
            cost_center_name='0000: Center'
        )
        self.assertIsNotNone(res)
        self.assertEqual(res['cost_center_name'], '0000: Center')
        mock_model.objects.filter.assert_called_with(
            create_eid__iexact='nattchai_u',
            budget_year=2025,
            base_branch_id__iexact='AP',
            cost_center_name__iexact='0000: Center'
        )

    def test_resolve_canonical_cost_center_name_variants(self):
        from budget_app.services import BudgetService
        from master_data.models import ebudget_cost_center_master

        mock_cc = MagicMock()
        mock_cc.cost_center_name = 'PH (Pet Hospital+Pet Taxi)'

        with patch.object(ebudget_cost_center_master.objects, 'filter') as mock_filter:
            mock_filter.return_value.first.return_value = mock_cc
            res = BudgetService.resolve_canonical_cost_center_name('PH')
            self.assertEqual(res, 'PH (Pet Hospital+Pet Taxi)')

        # None or empty returns as is
        self.assertIsNone(BudgetService.resolve_canonical_cost_center_name(None))
        self.assertIsNone(BudgetService.resolve_canonical_cost_center_name(''))

    def test_find_existing_budget_document_resolves_short_cost_center(self):
        from budget_app.services import BudgetService
        mock_model = MagicMock()
        mock_qs = MagicMock()
        mock_model.objects.filter.return_value = mock_qs
        mock_qs.exclude.return_value = mock_qs
        mock_qs.order_by.return_value = mock_qs
        mock_qs.values.return_value = mock_qs
        mock_qs.first.return_value = {
            'document_no': 'VET-202611-002',
            'budget_year': 2025,
            'base_branch_id': 'R2',
            'cost_center_name': 'PH (Pet Hospital+Pet Taxi)',
            'status': 'PENDING'
        }

        with patch.object(BudgetService, 'resolve_canonical_cost_center_name', return_value='PH (Pet Hospital+Pet Taxi)'):
            res = BudgetService.find_existing_budget_document(
                mock_model,
                create_eid='ebudget',
                budget_year=2025,
                base_branch_id='R2',
                cost_center_name='PH'
            )
            self.assertIsNotNone(res)
            self.assertEqual(res['document_no'], 'VET-202611-002')
            self.assertEqual(res['cost_center_name'], 'PH (Pet Hospital+Pet Taxi)')

    def test_check_duplicate_document_api_endpoint(self):
        from budget_app.views import check_duplicate_document_api
        from django.http import JsonResponse
        from django.test import RequestFactory
        from django.contrib.auth.models import AnonymousUser

        rf = RequestFactory()

        # 1. Duplicate found case
        req = rf.get('/api/check_duplicate_document/?doc_type=VET&branch_code=R2&cost_center=PH')
        user = MagicMock()
        user.is_authenticated = True
        user.username = 'ebudget'
        req.user = user

        mock_settings = MagicMock()
        mock_settings.active_budget_year = 2025
        with patch('budget_app.views.get_branch_info', return_value={'branches': ['R2'], 'needs_selection': False}), \
             patch('budget_app.models.SystemSettings.load', return_value=mock_settings), \
             patch('budget_app.views.check_duplicate_budget_document') as mock_check:
            mock_check.return_value = JsonResponse({
                'status': 'duplicate',
                'doc_type': 'VET',
                'document_no': 'VET-202611-002',
                'budget_year': 2025,
                'branch_id': 'R2',
                'cost_center_name': 'PH (Pet Hospital+Pet Taxi)',
                'message': 'Duplicate found'
            })
            resp = check_duplicate_document_api(req)
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertEqual(data['status'], 'duplicate')
            self.assertEqual(data['document_no'], 'VET-202611-002')

        # 2. No duplicate case
        with patch('budget_app.views.get_branch_info', return_value={'branches': ['R2'], 'needs_selection': False}), \
             patch('budget_app.models.SystemSettings.load', return_value=mock_settings), \
             patch('budget_app.views.check_duplicate_budget_document', return_value=None):
            resp2 = check_duplicate_document_api(req)
            self.assertEqual(resp2.status_code, 200)
            data2 = json.loads(resp2.content)
            self.assertEqual(data2['status'], 'ok')
            self.assertFalse(data2['is_duplicate'])

    def test_check_duplicate_budget_document_helper_includes_cost_center_in_response(self):
        from budget_app.views import check_duplicate_budget_document
        with patch('budget_app.services.BudgetService.find_existing_budget_document') as mock_find:
            mock_find.return_value = {
                'document_no': 'VET-202611-001',
                'budget_year': 2025,
                'base_branch_id': 'AP',
                'cost_center_name': '0000: Center',
                'status': 'PENDING'
            }

            resp = check_duplicate_budget_document(
                model_class=MagicMock(),
                doc_type='VET',
                create_eid='nattchai_u',
                budget_year=2025,
                base_branch_id='AP',
                cost_center_name='0000: Center'
            )
            self.assertIsNotNone(resp)
            self.assertEqual(resp.status_code, 200)
            data = json.loads(resp.content)
            self.assertEqual(data['status'], 'duplicate')
            self.assertEqual(data['cost_center_name'], '0000: Center')
            self.assertIn('Cost Center: 0000: Center', data['message'])


class DuplicateBudgetDocumentFrontendContractTests(SimpleTestCase):
    """Verifies that the duplicate check handling is correctly wired in
    base.html, budget_list.js, and across all 14 add-budget templates."""

    def test_base_html_defines_handle_duplicate_response(self):
        base_html_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'base.html')
        with open(base_html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('window.handleBudgetSaveDuplicateResponse = function', content)
        self.assertIn('Swal.fire', content)
        self.assertIn('ดูรายละเอียดเอกสาร', content)
        self.assertIn('open_doc_no=', content)
        self.assertIn('open_doc_type=', content)
        self.assertIn('costCenterName', content)
        self.assertIn('Cost Center:', content)

    def test_budget_list_js_auto_opens_duplicate_document(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn("urlParams.get('open_doc_no')", content)
        self.assertIn("urlParams.get('open_doc_type')", content)
        self.assertIn('fetchDocuments(catCode)', content)
        self.assertIn('viewDocumentDetails(openDocNo, openDocType)', content)
        self.assertIn('viewAdjustmentDetails(openDocNo)', content)
        self.assertIn('viewGeneralLedgerDocumentDetails(openDocNo, openDocType)', content)
        self.assertIn('viewGlatDocumentDetails(openDocNo)', content)
        self.assertIn('history.replaceState', content)

    def test_base_html_defines_check_duplicate_before_save(self):
        base_html_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'base.html')
        with open(base_html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('window.checkDuplicateBeforeSave = function', content)
        self.assertIn('window.handleBudgetSaveDuplicateResponse', content)
        self.assertIn('checkUrl', content)

    def test_all_14_add_templates_pre_check_duplicate_before_save(self):
        import glob
        templates_dir = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app')
        add_templates = glob.glob(os.path.join(templates_dir, 'budget_add*.html'))
        self.assertEqual(len(add_templates), 14, "Expected exactly 14 add-budget templates")

        for tmpl_path in add_templates:
            fname = os.path.basename(tmpl_path)
            with open(tmpl_path, 'r', encoding='utf-8') as f:
                content = f.read()

            self.assertIn("window.checkDuplicateBeforeSave", content, f"{fname} missing checkDuplicateBeforeSave call")
            self.assertIn("api_check_duplicate_document", content, f"{fname} missing api_check_duplicate_document url")
            self.assertIn("proceedWithSave", content, f"{fname} missing proceedWithSave callback")

    def test_all_14_add_templates_handle_duplicate_response(self):
        import glob
        templates_dir = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app')
        add_templates = glob.glob(os.path.join(templates_dir, 'budget_add*.html'))
        self.assertEqual(len(add_templates), 14, "Expected exactly 14 add-budget templates")

        for tmpl_path in add_templates:
            fname = os.path.basename(tmpl_path)
            with open(tmpl_path, 'r', encoding='utf-8') as f:
                content = f.read()

            self.assertIn("data.status === 'duplicate'", content, f"{fname} missing duplicate status branch")
            self.assertIn("handleBudgetSaveDuplicateResponse", content, f"{fname} missing handleBudgetSaveDuplicateResponse call")


class ZeroMonthlyDataValidationUnitTests(SimpleTestCase):
    """Verifies backend validation ensuring that rows with all-zero or empty
    monthly allocations are blocked on save."""

    def test_validate_nonzero_monthly_rows_valid(self):
        from budget_app.views import validate_nonzero_monthly_rows
        valid_data = [
            {
                'position_name': 'นายสัตวแพทย์ปฏิบัติการ',
                'monthly_data': {'jan': {'headcount': 1, 'cost': 35000}, 'feb': {'headcount': 0, 'cost': 0}}
            },
            {
                'position_name': 'ผู้ช่วยสัตวแพทย์',
                'monthly_data': {'jan': {'headcount': 0, 'cost': 0}, 'dec': {'headcount': 2, 'cost': 30000}}
            }
        ]
        self.assertIsNone(validate_nonzero_monthly_rows(valid_data, 'position_name'))

    def test_validate_nonzero_monthly_rows_single_zero_row(self):
        from budget_app.views import validate_nonzero_monthly_rows
        invalid_data = [
            {
                'position_name': 'นายสัตวแพทย์ปฏิบัติการ',
                'monthly_data': {'jan': {'headcount': 1, 'cost': 35000}}
            },
            {
                'position_name': 'ผู้ช่วยสัตวแพทย์',
                'monthly_data': {'jan': {'headcount': 0, 'cost': 0}, 'feb': {'headcount': 0, 'cost': 0}}
            }
        ]
        err = validate_nonzero_monthly_rows(invalid_data, 'position_name')
        self.assertIsNotNone(err)
        self.assertIn('แถวที่ 2: ผู้ช่วยสัตวแพทย์', err)
        self.assertIn('ค่าว่างหรือ 0 ทั้งหมด', err)

    def test_validate_nonzero_monthly_rows_multiple_zero_rows(self):
        from budget_app.views import validate_nonzero_monthly_rows
        invalid_data = [
            {
                'item_name': 'เครื่องตรวจคลื่นหัวใจ',
                'monthly_data': {'jan': {'headcount': 0}, 'feb': {'headcount': 0}}
            },
            {
                'item_name': 'เครื่องดมยาสลบ',
                'monthly_data': {'jan': {'headcount': 1}}
            },
            {
                'item_name': 'เครื่องอัลตราซาวด์',
                'monthly_data': {'jan': 0, 'feb': 0}
            }
        ]
        err = validate_nonzero_monthly_rows(invalid_data, 'item_name')
        self.assertIsNotNone(err)
        self.assertIn('แถวที่ 1: เครื่องตรวจคลื่นหัวใจ', err)
        self.assertIn('แถวที่ 3: เครื่องอัลตราซาวด์', err)
        self.assertNotIn('เครื่องดมยาสลบ', err)


class ZeroMonthlyDataFrontendContractTests(SimpleTestCase):
    """Verifies that client-side validation against all-zero monthly rows is present
    in base.html and across all 10 MANPOWER and FIX ASSET templates."""

    def test_base_html_defines_show_zero_monthly_rows_warning(self):
        base_html_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'base.html')
        with open(base_html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('window.showZeroMonthlyRowsWarning = function', content)
        self.assertIn('กรุณาระบุจำนวนในตารางส่วนแรก', content)
        self.assertIn('ยังไม่ได้ระบุจำนวนของทุกเดือน', content)
        self.assertIn('Swal.fire', content)

    def test_all_10_manpower_and_fix_asset_templates_have_zero_month_validation(self):
        templates_dir = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app')
        target_templates = [
            # MANPOWER
            'budget_add.html',
            'budget_add_non_vet.html',
            'budget_add_adjustment.html',
            # FIX ASSET
            'budget_add_medical_equipment.html',
            'budget_add_computer_equipment.html',
            'budget_add_furniture.html',
            'budget_add_tools_equipment.html',
            'budget_add_car.html',
            'budget_add_renovate.html',
            'budget_add_software.html'
        ]

        for tmpl_name in target_templates:
            tmpl_path = os.path.join(templates_dir, tmpl_name)
            with open(tmpl_path, 'r', encoding='utf-8') as f:
                content = f.read()

            self.assertIn('emptyMonthRows', content, f"{tmpl_name} must track emptyMonthRows")
            self.assertIn('showZeroMonthlyRowsWarning', content, f"{tmpl_name} must call showZeroMonthlyRowsWarning")

    def test_budget_list_js_has_zero_month_validation_for_edit_mode(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('emptyMonthRows', content)
        self.assertGreaterEqual(
            content.count('showZeroMonthlyRowsWarning(emptyMonthRows)'),
            2,
            "budget_list.js must validate zero-month rows in both saveDocument and saveAdjDocument"
        )

    def test_budget_list_js_clean_desc_scope_in_save_document(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        save_doc_idx = content.find('function saveDocument()')
        save_adj_idx = content.find('function saveAdjDocument()')
        self.assertNotEqual(save_doc_idx, -1)
        save_doc_code = content[save_doc_idx:save_adj_idx]

        self.assertIn('cleanDesc =', save_doc_code)
        self.assertIn('emptyMonthRows.push({ rowNumber: i + 1, name: position, desc: cleanDesc });', save_doc_code)
        desc_decl = "let cleanDesc = (description !== null && description !== undefined ? String(description) : '').trim();"
        self.assertIn(desc_decl, save_doc_code)


class FixAssetDuplicateRowValidationUnitTests(SimpleTestCase):
    """Verifies backend validation ensuring that within a FIX ASSET submission,
    no two rows have identical item_name and description, using category column label."""

    def test_validate_fix_asset_unique_rows_distinct_items(self):
        from budget_app.views import validate_fix_asset_unique_rows
        data = [
            {'item_name': 'Computer All in One', 'description': 'ห้องตรวจ 1'},
            {'item_name': 'Printer Laser', 'description': 'การเงิน'},
            {'item_name': 'UPS 1000VA', 'description': ''}
        ]
        self.assertIsNone(validate_fix_asset_unique_rows(data))

    def test_validate_fix_asset_unique_rows_same_item_different_descriptions_allowed(self):
        from budget_app.views import validate_fix_asset_unique_rows
        # Same item master but different descriptions must be ALLOWED
        data = [
            {'item_name': 'Computer All in One', 'description': 'ห้องตรวจ 1'},
            {'item_name': 'Computer All in One', 'description': 'ห้องตรวจ 2'}
        ]
        self.assertIsNone(validate_fix_asset_unique_rows(data))

    def test_validate_fix_asset_unique_rows_duplicate_with_description(self):
        from budget_app.views import validate_fix_asset_unique_rows
        data = [
            {'item_name': 'Computer All in One', 'description': 'ห้องตรวจ 1'},
            {'item_name': 'Printer Laser', 'description': 'การเงิน'},
            {'item_name': 'Computer All in One', 'description': 'ห้องตรวจ 1'}
        ]
        err = validate_fix_asset_unique_rows(data, item_label='เครื่องมือ')
        self.assertIsNotNone(err)
        self.assertIn('เครื่องมือ: "Computer All in One"', err)
        self.assertIn('รายละเอียด: "ห้องตรวจ 1"', err)
        self.assertIn('แถวที่ 1, แถวที่ 3', err)

    def test_validate_fix_asset_unique_rows_duplicate_with_empty_description(self):
        from budget_app.views import validate_fix_asset_unique_rows
        data = [
            {'item_name': 'Notebook Core i5', 'description': ''},
            {'item_name': 'Notebook Core i5', 'description': '   '}
        ]
        err = validate_fix_asset_unique_rows(data, item_label='เครื่องมือ')
        self.assertIsNotNone(err)
        self.assertIn('เครื่องมือ: "Notebook Core i5"', err)
        self.assertIn('รายละเอียด: (ไม่มีรายละเอียด / ค่าว่าง)', err)
        self.assertIn('แถวที่ 1, แถวที่ 2', err)

    def test_validate_fix_asset_unique_rows_with_category_specific_column_label(self):
        from budget_app.views import validate_fix_asset_unique_rows
        # CAR category uses 'รถยนต์' as column label
        car_data = [
            {'item_name': 'รถพยาบาลฉุกเฉิน', 'description': 'เวรดึก'},
            {'item_name': 'รถพยาบาลฉุกเฉิน', 'description': 'เวรดึก'}
        ]
        err = validate_fix_asset_unique_rows(car_data, item_label='รถยนต์')
        self.assertIsNotNone(err)
        self.assertIn('- รถยนต์: "รถพยาบาลฉุกเฉิน"', err)
        self.assertIn('ระบบตรวจพบว่ามีการระบุข้อมูล รถยนต์ และ รายละเอียด ซ้ำกันในเอกสาร:', err)

        # Software category uses 'Software' as column label
        sw_data = [
            {'item_name': 'Antivirus Server', 'description': 'Data Center'},
            {'item_name': 'Antivirus Server', 'description': 'Data Center'}
        ]
        err_sw = validate_fix_asset_unique_rows(sw_data, item_label='Software')
        self.assertIsNotNone(err_sw)
        self.assertIn('- Software: "Antivirus Server"', err_sw)
        self.assertIn('ระบบตรวจพบว่ามีการระบุข้อมูล Software และ รายละเอียด ซ้ำกันในเอกสาร:', err_sw)


class FixAssetDuplicateRowFrontendContractTests(SimpleTestCase):
    """Verifies that duplicate item master + description check is present
    in base.html, all 7 FIX ASSET templates, and budget_list.js edit mode."""

    def test_base_html_defines_show_duplicate_fix_asset_rows_warning(self):
        base_html_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'base.html')
        with open(base_html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('window.showDuplicateFixAssetRowsWarning = function(duplicateGroups, itemColLabel)', content)
        self.assertIn('พบรายการข้อมูลซ้ำซ้อนในตาราง', content)
        self.assertIn('colLabel', content)
        self.assertIn('รายละเอียด:', content)
        self.assertIn('Swal.fire', content)

    def test_all_7_fix_asset_templates_have_duplicate_detection_and_priority_order(self):
        templates_dir = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app')
        target_templates = [
            'budget_add_medical_equipment.html',
            'budget_add_computer_equipment.html',
            'budget_add_furniture.html',
            'budget_add_tools_equipment.html',
            'budget_add_car.html',
            'budget_add_renovate.html',
            'budget_add_software.html'
        ]

        for tmpl_name in target_templates:
            tmpl_path = os.path.join(templates_dir, tmpl_name)
            with open(tmpl_path, 'r', encoding='utf-8') as f:
                content = f.read()

            self.assertIn('seenFixAssetRows', content, f"{tmpl_name} must track seenFixAssetRows")
            self.assertIn('showDuplicateFixAssetRowsWarning(duplicateFixAssetGroups, itemColTitle)', content, f"{tmpl_name} must pass itemColTitle")
            self.assertIn('desc: cleanDesc', content, f"{tmpl_name} must pass desc to emptyMonthRows")

            # Duplicate check must run BEFORE zero-monthly warning
            dup_pos = content.find('duplicateFixAssetGroups.length > 0')
            empty_pos = content.find('emptyMonthRows.length > 0')
            self.assertNotEqual(dup_pos, -1, f"{tmpl_name} must check duplicateFixAssetGroups")
            self.assertNotEqual(empty_pos, -1, f"{tmpl_name} must check emptyMonthRows")
            self.assertLess(dup_pos, empty_pos, f"{tmpl_name} must evaluate duplicate check before empty months check")

    def test_budget_list_js_has_duplicate_detection_for_equipment(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        self.assertIn('seenEquipRows', content)
        self.assertIn('showDuplicateFixAssetRowsWarning(duplicateFixAssetGroups, colTitle)', content)












class PositionAdjustmentTypeRestrictionTests(SimpleTestCase):
    """Verifies that Position Adjustment (both create view template and budget_list modal)
    strictly requires choosing adjustment_type ('VET' or 'NON VET') before allowing selection
    of old/new positions, displays filtered positions by type, clears mismatched positions on type change,
    and validates type consistency on backend."""

    def test_adjustment_template_contract(self):
        tmpl_path = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_adjustment.html')
        with open(tmpl_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Datalists must only contain vet and non-vet, no unrestricted all-positions datalist
        self.assertNotIn("'adj-all-positions-datalist'", content)
        self.assertIn("'adj-vet-positions-datalist'", content)
        self.assertIn("'adj-non-vet-positions-datalist'", content)

        # Editor openEditor checks rowType and warns if missing
        self.assertIn('rowType !== \'VET\' && rowType !== \'NON VET\'', content)
        self.assertIn('กรุณาเลือกประเภท (VET หรือ NON VET) ในคอลัมน์ "ประเภท" ก่อนครับ', content)

        # Editor closeEditor validates position belongs to allowedList of rowType
        self.assertIn('allowedList = rowType === \'VET\' ? vetPositions : nonVetPositions', content)

        # onselection intercepts single-click on col 1 & 3
        self.assertIn('if (x1 === 1 || x1 === 3) {', content)
        self.assertIn('sheet.getValueFromCoords(0, y1)', content)

        # onchange x === 0 clears existing positions if mismatched
        self.assertIn("if (curOldPos !== '') {", content)
        self.assertIn('if (!allowedList.some(i => i.name === curOldPos)) {', content)
        self.assertIn("table1.setValueFromCoords(1, y, '', true);", content)
        self.assertIn("table1.setValueFromCoords(3, y, '', true);", content)

        # Save validation verifies against allowedList
        self.assertIn('allowedList = adjustmentType === \'VET\' ? vetPositions : nonVetPositions', content)

        # VET Allowance restriction contract
        self.assertIn('function showVetAllowanceAlert()', content)
        self.assertIn('ตำแหน่งประเภท VET ไม่มีค่าตำแหน่ง', content)
        self.assertIn('col === 6 || col === 9', content)

    def test_adjustment_modal_contract(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Datalists must not have unrestricted all-positions datalist
        self.assertNotIn("'modal-adj-all-positions-datalist'", content)
        self.assertIn("'modal-adj-vet-positions-datalist'", content)
        self.assertIn("'modal-adj-non-vet-positions-datalist'", content)

        # modalAdjPositionEditor checks rowType
        self.assertIn('rowType !== \'VET\' && rowType !== \'NON VET\'', content)
        self.assertIn('กรุณาเลือกประเภท (VET หรือ NON VET) ในคอลัมน์ "ประเภท" ก่อนครับ', content)

        # adjSheetContainer click listener guards col 1 & 3
        self.assertIn('if (x === 1 || x === 3) {', content)
        self.assertIn('rowType !== \'VET\' && rowType !== \'NON VET\'', content)

        # onAdjSpreadsheetChange clears mismatched positions on type change
        self.assertIn("adjTable1.setValueFromCoords(1, y, '', true);", content)
        self.assertIn("adjTable1.setValueFromCoords(3, y, '', true);", content)

        # Save validation uses allowedItems
        self.assertIn('allowedItems = adjustmentType === \'VET\' ? vetItems : nonVetItems', content)

        # VET Allowance restriction contract
        self.assertIn('function showVetAllowanceAlert()', content)
        self.assertIn('ตำแหน่งประเภท VET ไม่มีค่าตำแหน่ง', content)
        self.assertIn('col === 6 || col === 9', content)

    @patch('budget_app.models.SystemSettings.load')
    @patch('budget_app.services.BudgetService.get_master_fks_bulk')
    def test_backend_validation_rejects_position_mismatched_with_type(self, mock_fks, mock_settings):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.views import budget_add_adjustment_view

        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)

        def fks_side_effect(item_names, category_id=None, sub_category_id=None):
            if sub_category_id == 1:  # VET
                return {'สัตวแพทย์ปฏิบัติการ': (MagicMock(), 'GL_VET')}
            elif sub_category_id == 2:  # NON VET
                return {'เจ้าหน้าที่ธุรการ': (MagicMock(), 'GL_NONVET')}
            return {}

        mock_fks.side_effect = fks_side_effect
        factory = RequestFactory()

        # Item marked as VET but using NON VET position
        req_vet_with_nonvet = factory.post(
            reverse('budget_add_adjustment'),
            data=json.dumps([{
                'cost_center_name': 'CC1',
                'adjustment_type': 'VET',
                'old_position_name': 'สัตวแพทย์ปฏิบัติการ',
                'new_position_name': 'เจ้าหน้าที่ธุรการ',  # Invalid for VET
                'old_salary': 30000,
                'old_allowance': 0,
                'new_salary': 40000,
                'new_allowance': 0,
                'monthly_data': {'jan': {'headcount': 1, 'cost': 10000}}
            }]),
            content_type='application/json'
        )
        req_vet_with_nonvet.user = MagicMock(is_authenticated=True, username='test_user')
        req_vet_with_nonvet.session = {}

        res = budget_add_adjustment_view(req_vet_with_nonvet)
        self.assertEqual(res.status_code, 200)
        res_json = json.loads(res.content)
        self.assertEqual(res_json.get('status'), 'error')
        self.assertIn('ไม่อนุญาตให้พิมพ์ระบุข้อความเอง กรุณาเลือกตำแหน่งใหม่จากรายการ Dropdown เท่านั้น', res_json.get('message', ''))
        self.assertIn('ไม่มีอยู่ในรายการของประเภท VET', res_json.get('message', ''))



    @patch('budget_app.views.transaction.atomic')
    @patch('budget_app.services.BudgetService.resolve_canonical_cost_center_name', return_value='CC1')
    @patch('budget_app.models.SystemSettings.load')
    @patch('budget_app.services.BudgetService.get_master_fks_bulk')
    @patch('budget_app.views.ebudget_position_adjustment.objects.create')
    @patch('budget_app.services.BudgetService.save_monthly_data')
    @patch('budget_app.services.BudgetService.generate_document_no')
    @patch('budget_app.views.resolve_branch_for_create')
    @patch('budget_app.views.check_duplicate_budget_document')
    def test_backend_enforces_zero_allowance_for_vet(self, mock_dup, mock_branch, mock_doc_no, mock_save_monthly, mock_create, mock_fks, mock_settings, mock_cc, mock_atomic):
        from unittest.mock import MagicMock
        from django.test import RequestFactory
        from budget_app.views import budget_add_adjustment_view

        vet_pos_name = '\u0e19\u0e32\u0e22\u0e2a\u0e31\u0e15\u0e27\u0e41\u0e1e\u0e17\u0e22\u0e4c'
        mock_settings.return_value = MagicMock(is_frozen=0, active_budget_year=2026)
        mock_dup.return_value = None
        mock_branch.return_value = ('HO', None)
        mock_doc_no.return_value = 'ADJ-202611-999'
        mock_fks.return_value = {vet_pos_name: (MagicMock(), 'GL_VET')}

        factory = RequestFactory()
        req = factory.post(
            reverse('budget_add_adjustment'),
            data=json.dumps([{
                'cost_center_name': 'CC1',
                'adjustment_type': 'VET',
                'old_position_name': vet_pos_name,
                'new_position_name': vet_pos_name,
                'old_salary': 30000,
                'old_allowance': 5000,  # Should be forced to 0
                'new_salary': 40000,
                'new_allowance': 8000,  # Should be forced to 0
                'monthly_data': {'jan': {'headcount': 1, 'cost': 10000}}
            }]),
            content_type='application/json'
        )
        req.user = MagicMock(is_authenticated=True, username='test_user')
        req.session = {}

        res = budget_add_adjustment_view(req)
        self.assertEqual(res.status_code, 200)
        res_data = json.loads(res.content)
        self.assertEqual(res_data.get('status'), 'success')
        self.assertTrue(mock_create.called)
        create_kwargs = mock_create.call_args[1]
        self.assertEqual(create_kwargs.get('old_allowance'), 0)
        self.assertEqual(create_kwargs.get('new_allowance'), 0)


class BackOfficeBranchSelectionTests(SimpleTestCase):
    """Unit tests verifying branch selection resolution for back-office users with 'BACK-'
    in emp.bank_sub_name when real branch codes exist vs when only department codes exist."""

    @patch('budget_app.services.connections')
    def test_back_user_with_real_branches_resolves_selection_and_department(self, mock_connections):
        """User with BACK-MED,R2,AP should resolve branches=['R2', 'AP', 'HO'],
        needs_selection=True, and department_id='MED'."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ('BACK-MED,R2,AP', 'OFFICER', None)
        mock_cursor.fetchall.return_value = [('R2', 'สาขาพระราม2'), ('AP', 'สาขาอโศกประสานมิตร')]
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor

        info = BudgetService.get_branch_info_from_imedx('paiwan')
        self.assertEqual(info['branches'], ['R2', 'AP', 'HO'])
        self.assertTrue(info['needs_selection'])
        self.assertEqual(info['department_id'], 'MED')

    @patch('budget_app.services.connections')
    def test_back_user_without_branches_resolves_ho_only(self, mock_connections):
        """User with BACK-IT should resolve branches=['HO'], needs_selection=False,
        and department_id='IT'."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ('BACK-IT', 'OFFICER', None)
        mock_cursor.fetchall.return_value = []
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor

        info = BudgetService.get_branch_info_from_imedx('banchong')
        self.assertEqual(info['branches'], ['HO'])
        self.assertFalse(info['needs_selection'])
        self.assertEqual(info['department_id'], 'IT')

    @patch('budget_app.services.connections')
    def test_back_user_with_multiple_departments_no_branches(self, mock_connections):
        """User with BACK-ACC,FIN,PUR,STOCK,IA,PD has multiple departments but no real branches.
        Must resolve branches=['HO'], needs_selection=False, and department_id='ACC,FIN,PUR,STOCK,IA,PD'."""
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = ('BACK-ACC,FIN,PUR,STOCK,IA,PD', 'OFFICER', None)
        mock_cursor.fetchall.return_value = []
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor

        info = BudgetService.get_branch_info_from_imedx('watchana')
        self.assertEqual(info['branches'], ['HO'])
        self.assertFalse(info['needs_selection'])
        self.assertEqual(info['department_id'], 'ACC,FIN,PUR,STOCK,IA,PD')

    @patch('budget_app.services.connections')
    def test_paiwan_full_branch_list_resolution(self, mock_connections):
        """Full list from live DB: BACK-MED,AP,CA,CE,CM,EC,EV,PK,PR,PY,R2,R5,R6,R8,R9,RS,RY,SN,SR,SV,TN,TP.
        All branch codes should be recognized, 'HO' appended, needs_selection=True, department_id='MED'."""
        raw_val = 'BACK-MED,AP,CA,CE,CM,EC,EV,PK,PR,PY,R2,R5,R6,R8,R9,RS,RY,SN,SR,SV,TN,TP'
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (raw_val, 'OFFICER', None)
        mock_cursor.fetchall.return_value = [
            ('AP', 'สาขาอโศกประสานมิตร'), ('CA', 'สาขาเชียงใหม่แอร์พอร์ต'), ('CE', 'สาขาเซ็นทรัลอีสต์วิลล์'),
            ('CM', 'สาขาเชียงใหม่'), ('EC', 'Ecommerce'), ('EV', 'สาขาประดิษฐ์มนูธรรม'),
            ('PK', 'สาขาปิ่นเกล้า'), ('PR', 'สาขาประชาชื่น'), ('PY', 'สาขาพัทยา'),
            ('R2', 'สาขาพระราม2'), ('R5', 'สาขาพระราม5'), ('R6', 'สาขาพระราม6'),
            ('R8', 'สาขารามอินทรา'), ('R9', 'สาขาพระราม9'), ('RS', 'สาขารังสิต'),
            ('RY', 'สาขาระยอง'), ('SN', 'สาขาสาทรนราธิวาส'), ('SR', 'สาขาศรีนครินทร์'),
            ('SV', 'สาขาสุขุมวิท'), ('TN', 'สาขาติวานนท์'), ('TP', 'ทองหล่อฉลองภูเก็ต')
        ]
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor

        info = BudgetService.get_branch_info_from_imedx('paiwan')
        self.assertTrue(info['needs_selection'])
        self.assertEqual(info['department_id'], 'MED')
        self.assertIn('R2', info['branches'])
        self.assertIn('AP', info['branches'])
        self.assertIn('HO', info['branches'])
        self.assertEqual(info['branches'][-1], 'HO')

    @patch('budget_app.services.connections')
    def test_get_branch_names_from_imedx_maps_ho_to_head_office(self, mock_connections):
        """get_branch_names_from_imedx must always map 'HO' to 'สำนักงานใหญ่'
        even if not in base_site_branch."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('R2', 'สาขาพระราม2'), ('AP', 'สาขาอโศกประสานมิตร')]
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor
        names = BudgetService.get_branch_names_from_imedx(['R2', 'AP', 'HO'])
        self.assertEqual(names.get('HO'), 'สำนักงานใหญ่')
        self.assertIn('R2', names)
        self.assertIn('AP', names)

    def test_resolve_branch_for_create_with_back_selection(self):
        """resolve_branch_for_create should return the chosen branch and preserve department_id."""
        from budget_app.views import resolve_branch_for_create
        factory = RequestFactory()
        req = factory.post('/add/')
        req.session = {
            'branch_info': {
                'branches': ['R2', 'AP', 'HO'],
                'needs_selection': True,
                'department_id': 'MED'
            }
        }
        # Choose AP
        branch, dept = resolve_branch_for_create(req, [{'branch_code': 'AP'}])
        self.assertEqual(branch, 'AP')
        self.assertEqual(dept, 'MED')

        # Choose HO
        branch, dept = resolve_branch_for_create(req, [{'branch_code': 'HO'}])
        self.assertEqual(branch, 'HO')
        self.assertEqual(dept, 'MED')

        # Invalid choice raises ValueError
        with self.assertRaises(ValueError):
            resolve_branch_for_create(req, [{'branch_code': 'INVALID'}])

    def test_resolve_branch_for_update_with_back_selection(self):
        """resolve_branch_for_update should allow switching branch when needs_selection=True."""
        from budget_app.views import resolve_branch_for_update
        factory = RequestFactory()
        req = factory.post('/api/document/update/VET/DOC001/')
        req.session = {
            'branch_info': {
                'branches': ['R2', 'AP', 'HO'],
                'needs_selection': True,
                'department_id': 'MED'
            }
        }
        chosen = resolve_branch_for_update(req, [{'branch_code': 'AP'}], current_branch_id='R2')
        self.assertEqual(chosen, 'AP')

        # When needs_selection is False, it preserves current_branch_id
        req.session['branch_info']['needs_selection'] = False
        chosen = resolve_branch_for_update(req, [{'branch_code': 'AP'}], current_branch_id='HO')
        self.assertEqual(chosen, 'HO')

    @patch('budget_app.services.connections')
    def test_get_branch_names_from_base_sub_branch_including_bn(self, mock_connections):
        """get_branch_names_from_imedx must query base_sub_branch and correctly map BN to สาขาบางนา."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('BN', 'สาขาบางนา'), ('SR', 'สาขาศรีนครินทร์')]
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor

        names = BudgetService.get_branch_names_from_imedx(['SR', 'BN'])
        self.assertEqual(names.get('BN'), 'สาขาบางนา')
        self.assertEqual(names.get('SR'), 'สาขาศรีนครินทร์')

    @patch('budget_app.services.connections')
    def test_future_branch_in_base_sub_branch_resolves_correctly(self, mock_connections):
        """When a new branch is added to base_sub_branch in the future, it is resolved dynamically."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('NEW_BR', 'สาขาใหม่ในอนาคต')]
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor

        names = BudgetService.get_branch_names_from_imedx(['NEW_BR'])
        self.assertEqual(names.get('NEW_BR'), 'สาขาใหม่ในอนาคต')

    @patch('budget_app.views.get_branch_info')
    @patch('budget_app.services.connections')
    def test_get_branch_selection_context_for_bn_user(self, mock_connections, mock_get_branch_info):
        """A user with branch BN must receive option with code='BN' and name='สาขาบางนา'."""
        from budget_app.views import get_branch_selection_context
        mock_get_branch_info.return_value = {
            'branches': ['SR', 'BN'],
            'needs_selection': True,
            'department_id': None,
            'is_manager': True,
            'bank_account_note': 'MANAGER',
            'is_executive_view_only': False
        }
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('SR', 'สาขาศรีนครินทร์'), ('BN', 'สาขาบางนา')]
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor

        factory = RequestFactory()
        req = factory.get('/add/')
        req.session = {}

        ctx = get_branch_selection_context(req)
        self.assertTrue(ctx['needs_branch_selection'])
        options = ctx['branch_options_json']
        self.assertEqual(len(options), 2)
        bn_option = next((opt for opt in options if opt['code'] == 'BN'), None)
        self.assertIsNotNone(bn_option)
        self.assertEqual(bn_option['name'], 'สาขาบางนา')

    @patch('budget_app.services.connections')
    def test_get_all_branches_returns_base_sub_branch_data(self, mock_connections):
        """BudgetService.get_all_branches must return all branches from base_sub_branch."""
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = [('BN', 'สาขาบางนา'), ('HO', 'สำนักงานใหญ่')]
        mock_connections.__getitem__.return_value.cursor.return_value.__enter__.return_value = mock_cursor

        branches = BudgetService.get_all_branches()
        self.assertEqual(branches, [
            {'code': 'BN', 'name': 'สาขาบางนา'},
            {'code': 'HO', 'name': 'สำนักงานใหญ่'}
        ])


class MedicalEquipmentItemMasterReplacementTests(SimpleTestCase):
    """Unit tests verifying the Medical Equipment items loaded from
    'Data เครื่องมือแพทย์ For Budget 2027 By พี่หนึ่ง Update.xlsx'."""

    def test_migration_0026_contains_all_unique_items_and_other(self):
        """Verifies that the migration 0026 defines all 83 unique items from Update.xlsx
        and respects the GL price threshold."""
        import importlib
        mig_mod = importlib.import_module('master_data.migrations.0026_replace_medical_equipment_items')
        med_items = mig_mod.MEDICAL_EQUIPMENT_ITEMS
        self.assertEqual(mig_mod.CATEGORY_ID, 2)
        self.assertEqual(mig_mod.SUB_CATEGORY_ID, 4)
        self.assertEqual(len(med_items), 83)

        items_dict = {name: (price, gl) for name, price, gl in med_items}
        self.assertIn('Ultasound(Esaote_เช่าซื้อ)', items_dict)
        self.assertIn('ECT', items_dict)
        self.assertIn('TMS', items_dict)
        self.assertIn('เครื่องฟอกไต', items_dict)
        self.assertIn('VEP BAEP', items_dict)
        self.assertIn('Wood lamp', items_dict)
        self.assertIn('Phovia', items_dict)
        self.assertIn('ตู้ Intensive care(THX-ICU-02)', items_dict)
        self.assertIn('รถเข็นเวชภัณฑ์', items_dict)

        # Check GL mapping according to capitalization threshold
        for name, (price, gl) in items_dict.items():
            if price >= 5000:
                self.assertEqual(gl, '61300010', f"{name} should have GL 61300010 for price {price}")
            else:
                self.assertEqual(gl, '60300002', f"{name} should have GL 60300002 for price {price}")

    def test_excel_file_parsing_matches_migration_data(self):
        """Verifies that reading the actual Excel file 'Data เครื่องมือแพทย์ For Budget 2027 By พี่หนึ่ง Update.xlsx'
        yields the exact items present in migration 0026."""
        import openpyxl, glob, importlib
        mig_mod = importlib.import_module('master_data.migrations.0026_replace_medical_equipment_items')
        med_items = mig_mod.MEDICAL_EQUIPMENT_ITEMS

        excel_files = glob.glob(os.path.join(settings.BASE_DIR, '*เครื่องมือแพทย์*Update*.xlsx'))
        if not excel_files:
            self.skipTest("Medical Equipment Update.xlsx file not present in project directory, skipping excel comparison.")
        wb = openpyxl.load_workbook(excel_files[0], data_only=True)
        ws = wb.active

        excel_items = {}
        for r in range(3, ws.max_row + 1):
            name_val = ws.cell(row=r, column=3).value
            price_val = ws.cell(row=r, column=4).value
            if name_val is not None and str(name_val).strip():
                clean_name = ' '.join(str(name_val).split())
                if clean_name not in excel_items:
                    excel_items[clean_name] = round(float(price_val), 2)

        mig_dict = {name: price for name, price, _ in med_items}
        self.assertEqual(len(mig_dict), len(excel_items))
        for name, price in excel_items.items():
            self.assertIn(name, mig_dict)
            self.assertEqual(mig_dict[name], price)


class CumulativeDepreciationCalculationTests(SimpleTestCase):
    """Unit and contract tests for Fix Asset cumulative depreciation calculation,
    persistence, and frontend display."""

    def test_model_field_cumulative_depreciation_exists(self):
        """Verify that BudgetMonthlyDetail model has the cumulative_depreciation field."""
        from budget_app.models import BudgetMonthlyDetail
        field_names = [f.name for f in BudgetMonthlyDetail._meta.fields]
        self.assertIn('cumulative_depreciation', field_names)

    @patch('budget_app.models.BudgetMonthlyDetail.objects.create')
    @patch('budget_app.models.BudgetMonthlyDetail.objects.filter')
    def test_save_monthly_data_calculates_cumulative_depreciation(self, mock_filter, mock_create):
        """Verify running monthly cumulative depreciation calculation according to the SQL formula:
        ROUND(SUM(cost / (gl_depreciation * 12.0)) OVER (ORDER BY month ASC), 2)"""
        from decimal import Decimal
        from budget_app.services import BudgetService

        parent_mock = MagicMock()
        parent_mock.general_ledger_code = '61300010'

        # Mock gl_master lookup
        with patch('master_data.models.ebudget_general_ledger_master.objects.filter') as mock_gl:
            gl_entry = MagicMock()
            gl_entry.depreciation = Decimal('5.0')  # 5 years
            mock_gl.return_value.first.return_value = gl_entry

            # Monthly data with 120,000 cost in Mar (month 3) and 60,000 cost in Jul (month 7)
            monthly_data = {
                'jan': {'headcount': 0, 'cost': 0},
                'feb': {'headcount': 0, 'cost': 0},
                'mar': {'headcount': 1, 'cost': 120000},
                'apr': {'headcount': 0, 'cost': 0},
                'may': {'headcount': 0, 'cost': 0},
                'jun': {'headcount': 0, 'cost': 0},
                'jul': {'headcount': 1, 'cost': 60000},
                'aug': {'headcount': 0, 'cost': 0},
                'sep': {'headcount': 0, 'cost': 0},
                'oct': {'headcount': 0, 'cost': 0},
                'nov': {'headcount': 0, 'cost': 0},
                'dec': {'headcount': 0, 'cost': 0},
            }

            func = getattr(BudgetService.save_monthly_data, '__wrapped__', BudgetService.save_monthly_data)
            func(parent_mock, 'Medical Equipment', monthly_data)

            # 12 calls to BudgetMonthlyDetail.objects.create
            self.assertEqual(mock_create.call_count, 12)
            calls = mock_create.call_args_list

            # Month 1 (Jan): cost = 0, cum_dep = 0.0
            self.assertEqual(calls[0].kwargs['month'], 1)
            self.assertEqual(calls[0].kwargs['cumulative_depreciation'], 0.0)

            # Month 2 (Feb): cost = 0, cum_dep = 0.0
            self.assertEqual(calls[1].kwargs['month'], 2)
            self.assertEqual(calls[1].kwargs['cumulative_depreciation'], 0.0)

            # Month 3 (Mar): cost = 120000 / (5 * 12) = 2000.0
            self.assertEqual(calls[2].kwargs['month'], 3)
            self.assertEqual(calls[2].kwargs['cumulative_depreciation'], 2000.0)

            # Month 4-6 (Apr-Jun): cost = 0, cum_dep stays 2000.0
            for i in range(3, 6):
                self.assertEqual(calls[i].kwargs['cumulative_depreciation'], 2000.0)

            # Month 7 (Jul): cost 60000 -> +1000.0 = 3000.0
            self.assertEqual(calls[6].kwargs['month'], 7)
            self.assertEqual(calls[6].kwargs['cumulative_depreciation'], 3000.0)

            # Month 8-12 (Aug-Dec): cost = 0, cum_dep stays 3000.0
            for i in range(7, 12):
                self.assertEqual(calls[i].kwargs['cumulative_depreciation'], 3000.0)

    @patch('budget_app.models.BudgetMonthlyDetail.objects.create')
    @patch('budget_app.models.BudgetMonthlyDetail.objects.filter')
    def test_save_monthly_data_zero_depreciation_for_non_assets(self, mock_filter, mock_create):
        """Verify cumulative_depreciation is 0 when gl_depreciation is 0 or doc_type is non-asset."""
        from budget_app.services import BudgetService

        parent_mock = MagicMock()
        monthly_data = {
            'jan': {'headcount': 1, 'cost': 50000},
            'feb': {'headcount': 1, 'cost': 50000},
        }

        func = getattr(BudgetService.save_monthly_data, '__wrapped__', BudgetService.save_monthly_data)
        func(parent_mock, 'VET', monthly_data)
        calls = mock_create.call_args_list
        for call in calls:
            self.assertEqual(call.kwargs['cumulative_depreciation'], 0.0)

    def test_all_7_fix_asset_templates_do_not_contain_separate_cumulative_depreciation_column(self):
        """Verify that all 7 Add Budget templates in Fix Asset do NOT define 'ค่าเสื่อมสะสม'
        as a separate column in either Table 1 (columns) or Table 2 (calcColumns), as monthly
        depreciation is already displayed directly in the monthly columns (Jan-Dec)."""
        templates = [
            'budget_app/templates/budget_app/budget_add_medical_equipment.html',
            'budget_app/templates/budget_app/budget_add_computer_equipment.html',
            'budget_app/templates/budget_app/budget_add_furniture.html',
            'budget_app/templates/budget_app/budget_add_tools_equipment.html',
            'budget_app/templates/budget_app/budget_add_car.html',
            'budget_app/templates/budget_app/budget_add_renovate.html',
            'budget_app/templates/budget_app/budget_add_software.html',
        ]
        for tpl_path in templates:
            full_path = os.path.join(settings.BASE_DIR, tpl_path)
            self.assertTrue(os.path.exists(full_path), f"Template must exist: {tpl_path}")
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()

            self.assertNotIn('ค่าเสื่อมสะสม', content, f"Template must NOT contain 'ค่าเสื่อมสะสม' column in {tpl_path}")
            self.assertNotIn('setValueFromCoords(16, y,', content, f"Must not write to column 16 in {tpl_path}")
            self.assertIn('createInitialCalcData', content, f"createInitialCalcData missing in {tpl_path}")

    def test_budget_list_js_does_not_contain_cumulative_depreciation_column(self):
        """Verify that budget_list.js does NOT contain the separate 'ค่าเสื่อมสะสม' column in modal Table 2."""
        js_path = os.path.join(settings.BASE_DIR, 'budget_app/static/budget_app/js/budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertNotIn('ค่าเสื่อมสะสม', content)
        self.assertNotIn('modalTable2.setValueFromCoords(endCol + 2, y,', content)

    def test_all_7_fix_asset_templates_calculate_monthly_depreciation_in_table2(self):
        """Verify that in all 7 Fix Asset Add templates, Table 2 displays the monthly depreciation
        in month columns (columns 3-14) using mask '#,##0.00' and calculates mDep per month."""
        templates = [
            'budget_app/templates/budget_app/budget_add_medical_equipment.html',
            'budget_app/templates/budget_app/budget_add_computer_equipment.html',
            'budget_app/templates/budget_app/budget_add_furniture.html',
            'budget_app/templates/budget_app/budget_add_tools_equipment.html',
            'budget_app/templates/budget_app/budget_add_car.html',
            'budget_app/templates/budget_app/budget_add_renovate.html',
            'budget_app/templates/budget_app/budget_add_software.html',
        ]
        for tpl_path in templates:
            full_path = os.path.join(settings.BASE_DIR, tpl_path)
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()

            self.assertIn("table2.setValueFromCoords(i, y, mDep, true);", content, f"mDep table2 write missing in {tpl_path}")
            self.assertIn("mDep = Math.round((cumulativeUnits * sal / (depYears * 12)) * 100) / 100;", content, f"mDep formula missing in {tpl_path}")
            # Verify month mask '#,##0.00' in Table 2 calcColumns
            self.assertIn("{ type: 'numeric', title: 'Jan', width: 85, readOnly: true, mask: '#,##0.00' }", content)
            self.assertIn("{ type: 'numeric', title: 'Dec', width: 85, readOnly: true, mask: '#,##0.00' }", content)
            self.assertIn("{ type: 'numeric', title: 'รวม', width: 100, readOnly: true, mask: '#,##0.00' }", content)

    def test_budget_list_js_displays_monthly_depreciation_in_table2(self):
        """Verify that in budget_list.js, Table 2 (modalTable2) displays monthly depreciation
        in month columns for equipment in both view mode and edit mode."""
        js_path = os.path.join(settings.BASE_DIR, 'budget_app/static/budget_app/js/budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # In onSpreadsheetChange (edit mode)
        self.assertIn("modalTable2.setValueFromCoords(i, y, mDep, true);", content)
        self.assertIn("mDep = Math.round((cumulativeUnits * total_sal / (depYears * 12)) * 100) / 100;", content)
        # In viewDocumentDetails (view mode)
        self.assertIn("row2.push(mDep);", content)
        self.assertIn("mask: '#,##0.00'", content)

    def test_fix_asset_table2_renamed_to_calculate_depreciation(self):
        """Verify that in all 7 Fix Asset templates, budget_list.html, and budget_list.js,
        Table 2 is renamed to 'ตารางส่วนที่สอง (คำนวณค่าเสื่อม)'."""
        templates = [
            'budget_app/templates/budget_app/budget_add_medical_equipment.html',
            'budget_app/templates/budget_app/budget_add_computer_equipment.html',
            'budget_app/templates/budget_app/budget_add_furniture.html',
            'budget_app/templates/budget_app/budget_add_tools_equipment.html',
            'budget_app/templates/budget_app/budget_add_car.html',
            'budget_app/templates/budget_app/budget_add_renovate.html',
            'budget_app/templates/budget_app/budget_add_software.html',
        ]
        expected_title = 'ตารางส่วนที่สอง (คำนวณค่าเสื่อม)'
        for tpl_path in templates:
            full_path = os.path.join(settings.BASE_DIR, tpl_path)
            with open(full_path, 'r', encoding='utf-8') as f:
                c = f.read()
            self.assertIn(expected_title, c, f"Expected '{expected_title}' in {tpl_path}")
            self.assertNotIn('ตารางส่วนที่สอง (คำนวณงบประมาณ)', c, f"Old title must not be present in {tpl_path}")

        # Check budget_list.html
        html_path = os.path.join(settings.BASE_DIR, 'budget_app/templates/budget_app/budget_list.html')
        with open(html_path, 'r', encoding='utf-8') as f:
            html_c = f.read()
        self.assertIn('id="modalTable2HeaderTitle"', html_c)

        # Check budget_list.js
        js_path = os.path.join(settings.BASE_DIR, 'budget_app/static/budget_app/js/budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_c = f.read()
        self.assertIn("modalTable2Header.innerText = 'ตารางส่วนที่สอง (คำนวณค่าเสื่อม)';", js_c)


class MonthColumnsNumericOnlyEnforcementTests(SimpleTestCase):
    """Contract and unit tests to ensure month columns across Fix Asset and Manpower
    strictly accept numbers only (digits only, no letters or special characters)."""

    def test_month_columns_strictly_digits_only_in_all_add_templates(self):
        """Verify that all 7 Fix Asset templates and 3 Manpower templates strictly enforce
        digits only in month columns across keydown, input, onchange, and save validation."""
        templates = [
            'budget_app/templates/budget_app/budget_add_medical_equipment.html',
            'budget_app/templates/budget_app/budget_add_computer_equipment.html',
            'budget_app/templates/budget_app/budget_add_furniture.html',
            'budget_app/templates/budget_app/budget_add_tools_equipment.html',
            'budget_app/templates/budget_app/budget_add_car.html',
            'budget_app/templates/budget_app/budget_add_renovate.html',
            'budget_app/templates/budget_app/budget_add_software.html',
            'budget_app/templates/budget_app/budget_add.html',
            'budget_app/templates/budget_app/budget_add_non_vet.html',
            'budget_app/templates/budget_app/budget_add_adjustment.html',
        ]
        for tpl_path in templates:
            full_path = os.path.join(settings.BASE_DIR, tpl_path)
            self.assertTrue(os.path.exists(full_path), f"Template must exist: {tpl_path}")
            with open(full_path, 'r', encoding='utf-8') as f:
                c = f.read()

            self.assertIn("!/^[0-9]$/.test(e.key)", c, f"Digit-only keydown enforcement missing in {tpl_path}")
            self.assertIn("replace(/[^0-9]/g, '')", c, f"Digit-only input sanitization missing in {tpl_path}")
            self.assertIn("hasNonDigits", c, f"hasNonDigits check missing in onchange in {tpl_path}")
            self.assertIn("!/^\\d+$/.test(rawStr)", c, f"Digit-only save validation missing in {tpl_path}")

    def test_month_columns_strictly_digits_only_in_budget_list_js(self):
        """Verify that budget_list.js enforces digits only in month columns for both main
        modal and position adjustment modal across keydown, input, onchange, and save."""
        js_path = os.path.join(settings.BASE_DIR, 'budget_app/static/budget_app/js/budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            c = f.read()

        self.assertIn("!/^[0-9]$/.test(e.key)", c, "Digit-only keydown enforcement missing in budget_list.js")
        self.assertIn("replace(/[^0-9]/g, '')", c, "Digit-only input sanitization missing in budget_list.js")
        self.assertIn("hasNonDigits", c, "hasNonDigits check missing in budget_list.js")
        self.assertIn("!/^\\d+$/.test(rawStr)", c, "Digit-only save validation missing in budget_list.js")

    @patch('budget_app.models.BudgetMonthlyDetail.objects.create')
    @patch('budget_app.models.BudgetMonthlyDetail.objects.filter')
    def test_save_monthly_data_handles_negative_and_invalid_headcount(self, mock_filter, mock_create):
        """Verify that save_monthly_data sanitizes invalid or negative headcounts to 0."""
        from budget_app.services import BudgetService

        parent_mock = MagicMock()
        monthly_data = {
            'jan': {'headcount': -5, 'cost': 0},
            'feb': {'headcount': 'invalid_text', 'cost': 0},
            'mar': {'headcount': '10', 'cost': 1000},
        }

        func = getattr(BudgetService.save_monthly_data, '__wrapped__', BudgetService.save_monthly_data)
        func(parent_mock, 'VET', monthly_data)

        calls = mock_create.call_args_list
        # Month 1 (Jan): headcount -5 should become 0
        self.assertEqual(calls[0].kwargs['headcount'], 0)
        # Month 2 (Feb): headcount 'invalid_text' should become 0
        self.assertEqual(calls[1].kwargs['headcount'], 0)
        # Month 3 (Mar): headcount '10' should be 10
        self.assertEqual(calls[2].kwargs['headcount'], 10)


class DatabaseConfigurationAndConnectionTests(SimpleTestCase):
    """Verifies that database configuration and connection settings
    meet the environment specifications with appropriate search_path options."""

    def test_default_database_configuration(self):
        default_db = settings.DATABASES.get('default', {})
        self.assertEqual(default_db.get('NAME'), os.environ.get('DB_DEFAULT_NAME'))
        self.assertEqual(str(default_db.get('HOST')), os.environ.get('DB_DEFAULT_HOST'))
        self.assertEqual(str(default_db.get('PORT')), os.environ.get('DB_DEFAULT_PORT'))
        self.assertEqual(default_db.get('USER'), os.environ.get('DB_DEFAULT_USER'))
        options = default_db.get('OPTIONS', {})
        self.assertIn('-c search_path=intra_tl', options.get('options', ''))

    def test_imedx_database_configuration(self):
        imedx_db = settings.DATABASES.get('imedx', {})
        self.assertEqual(imedx_db.get('NAME'), os.environ.get('DB_IMEDX_NAME'))
        self.assertEqual(str(imedx_db.get('HOST')), os.environ.get('DB_IMEDX_HOST'))
        self.assertEqual(str(imedx_db.get('PORT')), os.environ.get('DB_IMEDX_PORT'))
        self.assertEqual(imedx_db.get('USER'), os.environ.get('DB_IMEDX_USER'))
        options = imedx_db.get('OPTIONS', {})
        self.assertIn('-c search_path=public', options.get('options', ''))


class LocalModelBackendTests(SimpleTestCase):
    """Verifies that LocalModelBackend strictly denies local password login
    for users who are active in iMedX, while allowing purely local accounts."""

    @patch('budget_app.backends.connections')
    def test_active_imedx_user_denied_local_password_login(self, mock_connections):
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = ('1',) # active employee

        from budget_app.backends import LocalModelBackend
        backend = LocalModelBackend()

        with patch('django.contrib.auth.backends.ModelBackend.authenticate') as mock_super_auth:
            result = backend.authenticate(None, username='nattchai_u', password='local_password')
            self.assertIsNone(result)
            mock_super_auth.assert_not_called()

    @patch('budget_app.backends.connections')
    def test_inactive_or_non_imedx_user_delegates_to_super(self, mock_connections):
        mock_cursor = mock_connections['imedx'].cursor.return_value.__enter__.return_value
        mock_cursor.fetchone.return_value = None # not in iMedX

        from budget_app.backends import LocalModelBackend
        backend = LocalModelBackend()

        mock_user = MagicMock()
        with patch('django.contrib.auth.backends.ModelBackend.authenticate', return_value=mock_user) as mock_super_auth:
            result = backend.authenticate(None, username='admin', password='local_admin_password')
            self.assertEqual(result, mock_user)
            mock_super_auth.assert_called_once()


class NonVetMonthlyDetailSalaryAllowanceTests(SimpleTestCase):
    """Unit tests verifying that BudgetMonthlyDetail has salary and position_allowance
    fields and that save_monthly_data calculates them as carry-forward (ขั้นบันได) for NON VET."""

    def test_budget_monthly_detail_has_salary_and_allowance_fields(self):
        from budget_app.models import BudgetMonthlyDetail
        field_names = [f.name for f in BudgetMonthlyDetail._meta.fields]
        self.assertIn('salary', field_names)
        self.assertIn('position_allowance', field_names)

    @patch('budget_app.models.BudgetMonthlyDetail.objects.create')
    @patch('budget_app.models.BudgetMonthlyDetail.objects.filter')
    def test_save_monthly_data_calculates_step_salary_and_allowance(self, mock_filter, mock_create):
        from budget_app.services import BudgetService

        parent_mock = MagicMock()
        parent_mock.salary = 20000.0
        parent_mock.position_allowance = 5000.0

        # Jan: 1 person, Feb: 0, Mar: 2 people
        monthly_data = {
            'jan': {'headcount': 1, 'cost': 25000},
            'feb': {'headcount': 0, 'cost': 25000},
            'mar': {'headcount': 2, 'cost': 75000},
            'apr': {'headcount': 0, 'cost': 75000},
            'may': {'headcount': 0, 'cost': 75000},
            'jun': {'headcount': 0, 'cost': 75000},
            'jul': {'headcount': 0, 'cost': 75000},
            'aug': {'headcount': 0, 'cost': 75000},
            'sep': {'headcount': 0, 'cost': 75000},
            'oct': {'headcount': 0, 'cost': 75000},
            'nov': {'headcount': 0, 'cost': 75000},
            'dec': {'headcount': 0, 'cost': 75000},
        }

        func = getattr(BudgetService.save_monthly_data, '__wrapped__', BudgetService.save_monthly_data)
        func(parent_mock, 'NON VET', monthly_data)

        self.assertEqual(mock_create.call_count, 12)
        calls = mock_create.call_args_list

        # Month 1 (Jan): running HC = 1 -> salary = 20000, allowance = 5000
        self.assertEqual(calls[0].kwargs['month'], 1)
        self.assertEqual(calls[0].kwargs['headcount'], 1)
        self.assertEqual(calls[0].kwargs['salary'], 20000.0)
        self.assertEqual(calls[0].kwargs['position_allowance'], 5000.0)

        # Month 2 (Feb): running HC = 1 -> salary = 20000, allowance = 5000
        self.assertEqual(calls[1].kwargs['month'], 2)
        self.assertEqual(calls[1].kwargs['headcount'], 0)
        self.assertEqual(calls[1].kwargs['salary'], 20000.0)
        self.assertEqual(calls[1].kwargs['position_allowance'], 5000.0)

        # Month 3 (Mar): running HC = 3 -> salary = 60000, allowance = 15000
        self.assertEqual(calls[2].kwargs['month'], 3)
        self.assertEqual(calls[2].kwargs['headcount'], 2)
        self.assertEqual(calls[2].kwargs['salary'], 60000.0)
        self.assertEqual(calls[2].kwargs['position_allowance'], 15000.0)

        # Month 4 (Apr): running HC = 3 -> salary = 60000, allowance = 15000
        self.assertEqual(calls[3].kwargs['month'], 4)
        self.assertEqual(calls[3].kwargs['headcount'], 0)
        self.assertEqual(calls[3].kwargs['salary'], 60000.0)
        self.assertEqual(calls[3].kwargs['position_allowance'], 15000.0)


class PositionAdjustmentMonthlyDetailSalaryAllowanceTests(SimpleTestCase):
    """Unit tests verifying that BudgetMonthlyDetail has new_salary and new_allowance
    fields and that save_monthly_data calculates them as carry-forward (ขั้นบันได)
    along with salary (old_salary) and position_allowance (old_allowance) for Position Adjustment."""

    def test_budget_monthly_detail_has_new_salary_and_new_allowance_fields(self):
        from budget_app.models import BudgetMonthlyDetail
        field_names = [f.name for f in BudgetMonthlyDetail._meta.fields]
        self.assertIn('salary', field_names)
        self.assertIn('position_allowance', field_names)
        self.assertIn('new_salary', field_names)
        self.assertIn('new_allowance', field_names)

    @patch('budget_app.models.BudgetMonthlyDetail.objects.create')
    @patch('budget_app.models.BudgetMonthlyDetail.objects.filter')
    def test_save_monthly_data_calculates_step_for_position_adjustment(self, mock_filter, mock_create):
        from budget_app.services import BudgetService

        parent_mock = MagicMock()
        parent_mock.old_salary = 30000.0
        parent_mock.old_allowance = 5000.0
        parent_mock.new_salary = 40000.0
        parent_mock.new_allowance = 8000.0

        monthly_data = {
            'jan': {'headcount': 1, 'cost': 13000},
            'feb': {'headcount': 0, 'cost': 13000},
            'mar': {'headcount': 1, 'cost': 26000},
            'apr': {'headcount': 0, 'cost': 26000},
            'may': {'headcount': 0, 'cost': 26000},
            'jun': {'headcount': 0, 'cost': 26000},
            'jul': {'headcount': 0, 'cost': 26000},
            'aug': {'headcount': 0, 'cost': 26000},
            'sep': {'headcount': 0, 'cost': 26000},
            'oct': {'headcount': 0, 'cost': 26000},
            'nov': {'headcount': 0, 'cost': 26000},
            'dec': {'headcount': 0, 'cost': 26000},
        }

        func = getattr(BudgetService.save_monthly_data, '__wrapped__', BudgetService.save_monthly_data)
        func(parent_mock, 'Position Adjustment', monthly_data)

        self.assertEqual(mock_create.call_count, 12)
        calls = mock_create.call_args_list

        # Month 1 (Jan): running HC = 1 -> old_salary = 30000, old_allowance = 5000, new_salary = 40000, new_allowance = 8000
        self.assertEqual(calls[0].kwargs['month'], 1)
        self.assertEqual(calls[0].kwargs['headcount'], 1)
        self.assertEqual(calls[0].kwargs['salary'], 30000.0)
        self.assertEqual(calls[0].kwargs['position_allowance'], 5000.0)
        self.assertEqual(calls[0].kwargs['new_salary'], 40000.0)
        self.assertEqual(calls[0].kwargs['new_allowance'], 8000.0)

        # Month 2 (Feb): running HC = 1 -> carry forward
        self.assertEqual(calls[1].kwargs['month'], 2)
        self.assertEqual(calls[1].kwargs['headcount'], 0)
        self.assertEqual(calls[1].kwargs['salary'], 30000.0)
        self.assertEqual(calls[1].kwargs['position_allowance'], 5000.0)
        self.assertEqual(calls[1].kwargs['new_salary'], 40000.0)
        self.assertEqual(calls[1].kwargs['new_allowance'], 8000.0)

        # Month 3 (Mar): running HC = 2 -> old_salary = 60000, old_allowance = 10000, new_salary = 80000, new_allowance = 16000
        self.assertEqual(calls[2].kwargs['month'], 3)
        self.assertEqual(calls[2].kwargs['headcount'], 1)
        self.assertEqual(calls[2].kwargs['salary'], 60000.0)
        self.assertEqual(calls[2].kwargs['position_allowance'], 10000.0)
        self.assertEqual(calls[2].kwargs['new_salary'], 80000.0)
        self.assertEqual(calls[2].kwargs['new_allowance'], 16000.0)

        # Month 4 (Apr): running HC = 2 -> carry forward
        self.assertEqual(calls[3].kwargs['month'], 4)
        self.assertEqual(calls[3].kwargs['headcount'], 0)
        self.assertEqual(calls[3].kwargs['salary'], 60000.0)
        self.assertEqual(calls[3].kwargs['position_allowance'], 10000.0)
        self.assertEqual(calls[3].kwargs['new_salary'], 80000.0)
        self.assertEqual(calls[3].kwargs['new_allowance'], 16000.0)


class InPlaceUpsertUnitTests(SimpleTestCase):
    """Unit tests verifying that get_document_detail_api returns item IDs,
    update_document_api performs in-place upsert (preserving existing item IDs
    and only deleting removed items), and save_monthly_data updates monthly
    detail records in-place without delete-recreate."""

    @patch('budget_app.models.ebudget_vet_manpower.objects.filter')
    def test_get_document_detail_api_includes_item_id(self, mock_filter):
        from budget_app.views import get_document_detail_api
        from django.test import RequestFactory

        mock_item = MagicMock()
        mock_item.id = 99
        mock_item.document_no = 'VET-202611-TEST'
        mock_item.create_date = None
        mock_item.create_eid = 'user1'
        mock_item.base_branch_id = 'HO'
        mock_item.cost_center_name = 'PH'
        mock_item.budget_year = 2026
        mock_item.status = 'PENDING'
        mock_item.cancel_reason = ''
        mock_item.position_name = 'Doctor'
        mock_item.description = 'Test note'
        mock_item.salary = 30000.0
        mock_item.monthly_data_dict = {}

        mock_qs = MagicMock()
        mock_qs.exists.return_value = True
        mock_qs.first.return_value = mock_item
        mock_qs.__iter__.return_value = [mock_item]
        mock_filter.return_value = mock_qs

        rf = RequestFactory()
        req = rf.get('/api/documents/VET/VET-202611-TEST/')
        req.user = MagicMock()
        req.user.username = 'user1'
        req.user.is_superuser = True
        req.session = {}

        func = getattr(get_document_detail_api, '__wrapped__', get_document_detail_api)
        resp = func(req, 'VET', 'VET-202611-TEST')
        data = json.loads(resp.content)

        self.assertEqual(data['status'], 'success')
        self.assertEqual(len(data['manpower_list']), 1)
        self.assertEqual(data['manpower_list'][0]['id'], 99)
        self.assertEqual(data['manpower_list'][0]['position_name'], 'Doctor')

    @patch('budget_app.models.BudgetMonthlyDetail.objects.filter')
    def test_save_monthly_data_updates_existing_details_in_place(self, mock_filter):
        from budget_app.services import BudgetService

        parent_mock = MagicMock()
        parent_mock.salary = 20000.0
        parent_mock.position_allowance = 5000.0

        existing_d1 = MagicMock()
        existing_d1.month = 1
        existing_d1.cost = 0.0

        mock_filter.return_value = [existing_d1]

        monthly_data = {
            'jan': {'headcount': 1, 'cost': 25000},
        }

        func = getattr(BudgetService.save_monthly_data, '__wrapped__', BudgetService.save_monthly_data)
        func(parent_mock, 'NON VET', monthly_data)

        # existing_d1 should be updated in-place with save(update_fields=...)
        existing_d1.save.assert_called_once()
        self.assertEqual(existing_d1.cost, 25000)
        self.assertEqual(existing_d1.salary, 20000.0)
        self.assertEqual(existing_d1.position_allowance, 5000.0)


class SessionTimeoutAndHybridAuthTests(SimpleTestCase):
    """Verifies session cookie age is 2 hours (7200s) and login_required_hybrid
    returns 401 JSON for AJAX/POST requests and 302 redirect for browser GET."""

    def test_session_cookie_age_is_two_hours(self):
        from django.conf import settings
        self.assertEqual(settings.SESSION_COOKIE_AGE, 7200)

    def test_session_idle_timeout_context_processor(self):
        from budget_app.context_processors import session_idle_timeout
        factory = RequestFactory()
        req = factory.get('/')
        ctx = session_idle_timeout(req)
        self.assertEqual(ctx.get('session_idle_timeout_seconds'), 7200)

    def test_unauthenticated_browser_get_redirects_to_login(self):
        from django.contrib.auth.models import AnonymousUser
        from budget_app.views import budget_add_gl_entry_view
        factory = RequestFactory()
        req = factory.get('/add_gl_entry/')
        req.user = AnonymousUser()
        resp = budget_add_gl_entry_view(req)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login/', resp.url)

    def test_unauthenticated_json_post_returns_401_json(self):
        from django.contrib.auth.models import AnonymousUser
        from budget_app.views import budget_add_gl_entry_view
        factory = RequestFactory()
        req = factory.post('/add_gl_entry/', data='[{"cost_center_name": "test"}]', content_type='application/json')
        req.user = AnonymousUser()
        resp = budget_add_gl_entry_view(req)
        self.assertEqual(resp.status_code, 401)
        data = json.loads(resp.content.decode('utf-8'))
        self.assertEqual(data.get('status'), 'error')
        self.assertEqual(data.get('code'), 'session_expired')
        self.assertIn('เซสชันหมดอายุ', data.get('message'))

    def test_unauthenticated_duplicate_api_returns_401_json(self):
        from django.contrib.auth.models import AnonymousUser
        from budget_app.views import check_duplicate_document_api
        factory = RequestFactory()
        req = factory.get('/api/check_duplicate_document/?doc_type=GL+Entry')
        req.user = AnonymousUser()
        resp = check_duplicate_document_api(req)
        self.assertEqual(resp.status_code, 401)
        data = json.loads(resp.content.decode('utf-8'))
        self.assertEqual(data.get('code'), 'session_expired')

    def test_unauthenticated_session_keepalive_returns_401(self):
        from django.contrib.auth.models import AnonymousUser
        from budget_app.views import session_keepalive_api
        factory = RequestFactory()
        req = factory.get('/api/session/keepalive/')
        req.user = AnonymousUser()
        resp = session_keepalive_api(req)
        self.assertEqual(resp.status_code, 401)
        data = json.loads(resp.content.decode('utf-8'))
        self.assertEqual(data.get('code'), 'session_expired')

    def test_authenticated_session_keepalive_returns_200_and_idle_timeout(self):
        from unittest.mock import MagicMock
        from django.contrib.auth.models import User
        from budget_app.views import session_keepalive_api
        factory = RequestFactory()
        req = factory.get('/api/session/keepalive/')
        req.user = User(username='test_user')
        mock_session = MagicMock()
        mock_session.modified = False
        req.session = mock_session
        resp = session_keepalive_api(req)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(req.session.modified)
        data = json.loads(resp.content.decode('utf-8'))
        self.assertEqual(data.get('status'), 'success')
        self.assertTrue(data.get('authenticated'))
        self.assertEqual(data.get('idle_timeout_seconds'), 7200)


class ItemMasterOrderByIdAscTests(SimpleTestCase):
    """Verifies that all item master options for budget add views and
    budget list edit modals are ordered by ID ascending, and that
    templates/JS do not re-sort them alphabetically."""

    def test_templates_do_not_alphabetically_sort_item_masters(self):
        template_files = [
            'budget_add.html',
            'budget_add_non_vet.html',
            'budget_add_medical_equipment.html',
            'budget_add_computer_equipment.html',
            'budget_add_furniture.html',
            'budget_add_tools_equipment.html',
            'budget_add_car.html',
            'budget_add_renovate.html',
            'budget_add_software.html',
            'budget_add_adjustment.html',
        ]
        base_dir = os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app')
        for filename in template_files:
            file_path = os.path.join(base_dir, filename)
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            self.assertNotIn(
                "itemNames = items.map(i => i.name).sort((a, b) => a.localeCompare(b, 'th'))",
                content,
                f"{filename} should not sort itemNames alphabetically"
            )
            self.assertNotIn(
                ".sort((a, b) => a.name.localeCompare(b.name, 'th'))",
                content,
                f"{filename} should not sort items alphabetically"
            )

    def test_budget_list_js_does_not_alphabetically_sort_item_masters(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertNotIn(
            "const itemNames = itemsList.map(i => i.name).sort((a, b) => a.localeCompare(b, 'th'))",
            content,
            "budget_list.js should not sort itemNames alphabetically"
        )
        self.assertNotIn(
            "allAdjItems.sort((a, b) => a.name.localeCompare(b.name, 'th'))",
            content,
            "budget_list.js should not sort allAdjItems alphabetically"
        )

    def test_views_order_by_id_in_queries(self):
        views_path = os.path.join(settings.BASE_DIR, 'budget_app', 'views.py')
        with open(views_path, 'r', encoding='utf-8') as f:
            content = f.read()
        # Ensure all ebudget_budget_item_master queries use order_by('id')
        self.assertIn("ebudget_budget_item_master.objects.filter(category_id=1, sub_category_id=1).order_by('id')", content)
        self.assertIn("ebudget_budget_item_master.objects.filter(category_id=1, sub_category_id=2).order_by('id')", content)
        self.assertIn("ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=4).order_by('id')", content)
        self.assertIn("ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=5).order_by('id')", content)
        self.assertIn("ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=6).order_by('id')", content)
        self.assertIn("ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=7).order_by('id')", content)
        self.assertIn("ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=8).order_by('id')", content)
        self.assertIn("ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=9).order_by('id')", content)
        self.assertIn("ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=10).order_by('id')", content)
        self.assertIn("ebudget_budget_item_master.objects.filter(category_id=2, sub_category_id=sub_category_id).order_by('id')", content)


class GlActualTemplateAccessControlTests(SimpleTestCase):
    """Verifies that the 'GL Actual Template' menu and add view are visible
    and accessible strictly to users nattchai_u, kanchana_a, and pattida_y."""

    def test_can_access_gl_actual_template_helper(self):
        from budget_app.services import can_access_gl_actual_template
        from django.contrib.auth.models import AnonymousUser
        factory = RequestFactory()

        for allowed in ['nattchai_u', 'kanchana_a', 'pattida_y', 'NATTCHAI_U', 'Pattida_Y']:
            req = factory.get('/')
            req.user = User(username=allowed)
            self.assertTrue(can_access_gl_actual_template(req), f"{allowed} should be allowed")

        for disallowed in ['kanchana', 'admin', 'sutep', 'khanitta', 'mgr01', 'regular_emp']:
            req = factory.get('/')
            req.user = User(username=disallowed, is_superuser=(disallowed == 'admin'))
            self.assertFalse(can_access_gl_actual_template(req), f"{disallowed} should NOT be allowed")

        req_anon = factory.get('/')
        req_anon.user = AnonymousUser()
        self.assertFalse(can_access_gl_actual_template(req_anon))

    @patch('budget_app.models.SystemSettings.load')
    def test_site_status_context_processor_gl_actual_template_flag(self, mock_load):
        mock_settings = type('Settings', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2026})()
        mock_load.return_value = mock_settings
        factory = RequestFactory()

        req_allowed = factory.get('/')
        req_allowed.user = User(username='pattida_y')
        req_allowed.session = {'branch_info': {'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False}}
        self.assertTrue(site_status(req_allowed)['can_access_gl_actual_template'])

        req_denied = factory.get('/')
        req_denied.user = User(username='mgr01')
        req_denied.session = {'branch_info': {'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False}}
        self.assertFalse(site_status(req_denied)['can_access_gl_actual_template'])

    @patch('budget_app.models.SystemSettings.load')
    def test_base_template_shows_or_hides_gl_actual_template_menu(self, mock_load):
        mock_settings = type('Settings', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2026})()
        mock_load.return_value = mock_settings
        factory = RequestFactory()

        for allowed_username in ['nattchai_u', 'kanchana_a', 'pattida_y']:
            req = factory.get('/')
            req.user = User(username=allowed_username, first_name=allowed_username)
            req.session = {'branch_info': {'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False}}
            out = render_to_string('budget_app/base.html', {'csrf_token': 'dummy'}, request=req)
            self.assertIn(reverse('budget_add_gl_actual_template'), out, f"{allowed_username} should see GL Actual Template menu")
            self.assertIn('GL Actual Template', out)

        for denied_username in ['mgr01', 'kanchana', 'sutep', 'khanitta']:
            req = factory.get('/')
            req.user = User(username=denied_username, first_name=denied_username)
            req.session = {'branch_info': {'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False}}
            out = render_to_string('budget_app/base.html', {'csrf_token': 'dummy'}, request=req)
            self.assertNotIn(reverse('budget_add_gl_actual_template'), out, f"{denied_username} should NOT see GL Actual Template menu")
            self.assertNotIn('GL Actual Template', out)

    @patch('budget_app.models.SystemSettings.load')
    def test_gl_actual_template_view_blocks_unauthorized_users(self, mock_load):
        from budget_app.views import budget_add_gl_actual_template_view
        mock_settings = type('Settings', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2026})()
        mock_load.return_value = mock_settings
        factory = RequestFactory()

        for denied_user in ['mgr01', 'kanchana', 'admin']:
            req_get = factory.get(reverse('budget_add_gl_actual_template'))
            req_get.user = User(username=denied_user, is_superuser=(denied_user == 'admin'))
            req_get.session = {'branch_info': {'is_view_only': False}}
            res_get = budget_add_gl_actual_template_view(req_get)
            self.assertEqual(res_get.status_code, 302)
            self.assertEqual(res_get.url, reverse('budget_list'))

            req_post = factory.post(reverse('budget_add_gl_actual_template'), data='[]', content_type='application/json')
            req_post.user = User(username=denied_user, is_superuser=(denied_user == 'admin'))
            req_post.session = {'branch_info': {'is_view_only': False}}
            res_post = budget_add_gl_actual_template_view(req_post)
            self.assertEqual(res_post.status_code, 403)
            data = json.loads(res_post.content)
            self.assertEqual(data['status'], 'error')
            self.assertIn('ไม่มีสิทธิ์', data['message'])



class DashboardAccessAndMatrixTests(SimpleTestCase):
    """Comprehensive tests for TLPH E-Budget Dashboard access control,
    single-branch and ALL-TLPH P&L calculation accuracy, 2-decimal rounding, and Excel (.xlsx) export."""

    def _mock_user(self, username, is_superuser=False):
        return User(username=username, is_superuser=is_superuser)

    @patch('budget_app.services.BudgetService.get_branch_names_from_imedx', return_value={
        'SR': 'สาขาศรีนครินทร์', 'PM': 'สาขาประดิษฐ์มนูธรรม', 'CA': 'สาขาเชียงใหม่แอร์พอร์ต', 'MY-BS': 'Moya Bangsaen',
    })
    @patch('budget_app.services.BudgetService.get_tlph_branches', return_value=[
        {'code': 'AP', 'name': 'สาขาอโศกประสานมิตร'},
        {'code': 'CA', 'name': 'สาขาเชียงใหม่แอร์พอร์ต'},
        {'code': 'PM', 'name': 'สาขาประดิษฐ์มนูธรรม'},
        {'code': 'R5', 'name': 'สาขาพระราม5'},
        {'code': 'SR', 'name': 'สาขาศรีนครินทร์'},
    ])
    def test_role_based_dashboard_access_and_branch_scopes(self, mock_tlph, mock_names):
        from budget_app.dashboard_service import (
            can_access_dashboard,
            can_view_all_branches_dashboard,
            get_allowed_branches_for_dashboard,
        )
        factory = RequestFactory()

        # 1. Special all-branch users (nattchai_u, pattida_y, kanchana_a) -> ALL + TLPH branches
        for uname in ('nattchai_u', 'pattida_y', 'kanchana_a'):
            req = factory.get('/dashboard/')
            req.user = self._mock_user(uname)
            req.session = {'branch_info': {'branches': ['HO'], 'is_manager': False, 'is_executive_view_only': False, 'is_district_view_only': False, 'bank_account_note': 'IT'}}
            self.assertTrue(can_access_dashboard(req), msg=f'{uname} must have dashboard access')
            self.assertTrue(can_view_all_branches_dashboard(req), msg=f'{uname} must have ALL branch option')
            self.assertEqual([b['code'] for b in get_allowed_branches_for_dashboard(req)], ['ALL', 'AP', 'CA', 'PM', 'R5', 'SR'])

        # 2. Executives (CHRO, CFO, COO) -> ALL + TLPH branches
        for role in ('CHRO', 'CFO', 'COO'):
            req = factory.get('/dashboard/')
            req.user = self._mock_user('exec_u')
            req.session = {'branch_info': {'branches': ['HO'], 'is_manager': False, 'is_executive_view_only': True, 'is_district_view_only': False, 'bank_account_note': role}}
            self.assertTrue(can_access_dashboard(req), msg=f'{role} must have dashboard access')
            self.assertTrue(can_view_all_branches_dashboard(req), msg=f'{role} must have ALL branch option')
            self.assertEqual([b['code'] for b in get_allowed_branches_for_dashboard(req)], ['ALL', 'AP', 'CA', 'PM', 'R5', 'SR'])

        # 3. DISTRICT MANAGER / DIRECTOR -> only configured TLPH bank_sub_name branches (no ALL, no MY-*)
        for role in ('DISTRICT MANAGER', 'DIRECTOR'):
            req = factory.get('/dashboard/')
            req.user = self._mock_user('khanitta')
            req.session = {'branch_info': {'branches': ['SR', 'PM', 'MY-BS'], 'is_manager': role == 'DISTRICT MANAGER', 'is_executive_view_only': False, 'is_district_view_only': True, 'bank_account_note': role}}
            self.assertTrue(can_access_dashboard(req))
            self.assertFalse(can_view_all_branches_dashboard(req))
            self.assertEqual([b['code'] for b in get_allowed_branches_for_dashboard(req)], ['PM', 'SR'])

        # 4. MANAGER -> only configured TLPH bank_sub_name / own branches (no ALL)
        req_mgr = factory.get('/dashboard/')
        req_mgr.user = self._mock_user('adjima_b')
        req_mgr.session = {'branch_info': {'branches': ['CA', 'MY-BS'], 'is_manager': True, 'is_executive_view_only': False, 'is_district_view_only': False, 'bank_account_note': 'MANAGER'}}
        self.assertTrue(can_access_dashboard(req_mgr))
        self.assertFalse(can_view_all_branches_dashboard(req_mgr))
        self.assertEqual([b['code'] for b in get_allowed_branches_for_dashboard(req_mgr)], ['CA'])

        # 5. Regular non-manager staff -> denied
        for role in ('FRONT', 'OPD', 'BOM', 'ช่างกอล์ฟ', ''):
            req_staff = factory.get('/dashboard/')
            req_staff.user = self._mock_user('staff01')
            req_staff.session = {'branch_info': {'branches': ['PM'], 'is_manager': False, 'is_executive_view_only': False, 'is_district_view_only': False, 'bank_account_note': role}}
            self.assertFalse(can_access_dashboard(req_staff), msg=f'{role} must not access dashboard')
            self.assertFalse(can_view_all_branches_dashboard(req_staff))
            self.assertEqual(get_allowed_branches_for_dashboard(req_staff), [])

    @patch('budget_app.models.SystemSettings.load')
    def test_sidebar_menu_shows_dashboard_only_to_authorized_roles(self, mock_load):
        from django.template.loader import render_to_string
        mock_load.return_value = type('S', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2025})()
        factory = RequestFactory()

        for allowed_session in (
            {'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False, 'is_manager': True},
            {'is_view_only': True, 'is_executive_view_only': True, 'is_district_view_only': False, 'is_manager': False},
            {'is_view_only': True, 'is_executive_view_only': False, 'is_district_view_only': True, 'is_manager': False},
        ):
            req = factory.get('/list/')
            req.user = self._mock_user('role_user')
            req.session = {'branch_info': allowed_session}
            html = render_to_string('budget_app/base.html', {}, request=req)
            self.assertIn('href="/dashboard/"', html)

        # Staff member with partial or non-manager session must NOT see Dashboard menu
        req_staff = factory.get('/list/')
        req_staff.user = self._mock_user('staff01')
        req_staff.session = {'branch_info': {'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False, 'is_manager': False}}
        html_staff = render_to_string('budget_app/base.html', {}, request=req_staff)
        self.assertNotIn('href="/dashboard/"', html_staff)

    @patch('budget_app.dashboard_service.build_dashboard_data', return_value={'branch': {'code': 'ALL', 'name': 'ทุกสาขา (TLPH ทั้งหมด)', 'is_all': True}, 'budget_year': 2025, 'rows': []})
    @patch('budget_app.models.SystemSettings.load')
    @patch('budget_app.services.BudgetService.get_branch_names_from_imedx', return_value={'CA': 'สาขาเชียงใหม่แอร์พอร์ต', 'MY-BS': 'Moya Bangsaen'})
    @patch('budget_app.services.BudgetService.get_tlph_branches', return_value=[
        {'code': 'CA', 'name': 'สาขาเชียงใหม่แอร์พอร์ต'},
        {'code': 'PM', 'name': 'สาขาประดิษฐ์มนูธรรม'},
    ])
    def test_api_enforces_single_branch_and_role_permissions(self, mock_tlph, mock_names, mock_load, mock_build):
        import json
        from budget_app.views import dashboard_data_api, dashboard_export_excel_api, dashboard_view
        mock_load.return_value = type('S', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2025})()
        factory = RequestFactory()

        # Unauthenticated -> 401 JSON
        req_anon = factory.get('/api/dashboard/data/?branch=PM&year=2025')
        req_anon.user = type('Anon', (), {'is_authenticated': False})()
        res_anon = dashboard_data_api(req_anon)
        self.assertEqual(res_anon.status_code, 401)

        # Regular staff -> 302 redirect on HTML view, 403 JSON on APIs
        staff_session = {'branch_info': {'branches': ['PM'], 'is_manager': False, 'is_executive_view_only': False, 'is_district_view_only': False, 'bank_account_note': 'FRONT'}}
        req_view = factory.get('/dashboard/')
        req_view.user = self._mock_user('front01')
        req_view.session = staff_session
        res_view = dashboard_view(req_view)
        self.assertEqual(res_view.status_code, 302)

        for view_fn, path in ((dashboard_data_api, '/api/dashboard/data/'), (dashboard_export_excel_api, '/api/dashboard/export/')):
            req_s = factory.get(f'{path}?branch=PM&year=2025')
            req_s.user = self._mock_user('front01')
            req_s.session = staff_session
            res_s = view_fn(req_s)
            self.assertEqual(res_s.status_code, 403)

        # Manager of CA cannot query ALL, comma list, blank, MY-*, or unauthorized TLPH branch PM
        mgr_session = {'branch_info': {'branches': ['CA'], 'is_manager': True, 'is_executive_view_only': False, 'is_district_view_only': False, 'bank_account_note': 'MANAGER'}}
        for bad_q, expected_code in (
            ('', 400),
            ('?branch=', 400),
            ('?branch=ALL', 400),
            ('?branch=CA,PM', 400),
            ('?branch=CA;PM', 400),
            ('?branch=PM', 403),
            ('?branch=MY-BS', 403),
        ):
            req_bad = factory.get(f'/api/dashboard/data/{bad_q}')
            req_bad.user = self._mock_user('mgr_ca')
            req_bad.session = mgr_session
            res_bad = dashboard_data_api(req_bad)
            self.assertEqual(res_bad.status_code, expected_code, msg=f'query={bad_q} body={res_bad.content}')
            self.assertEqual(json.loads(res_bad.content)['status'], 'error')

        # Privileged All-Branch user (nattchai_u / CFO) gets 200 on ?branch=ALL & TLPH branches, but 403 on non-TLPH MY-BS
        all_session = {'branch_info': {'branches': ['HO'], 'is_manager': False, 'is_executive_view_only': False, 'is_district_view_only': False, 'bank_account_note': 'IT'}}
        for ok_branch in ('ALL', 'PM', 'CA'):
            req_ok = factory.get(f'/api/dashboard/data/?branch={ok_branch}&year=2025')
            req_ok.user = self._mock_user('nattchai_u')
            req_ok.session = all_session
            res_ok = dashboard_data_api(req_ok)
            self.assertEqual(res_ok.status_code, 200, msg=f'branch={ok_branch} body={res_ok.content}')
        req_my = factory.get('/api/dashboard/data/?branch=MY-BS&year=2025')
        req_my.user = self._mock_user('nattchai_u')
        req_my.session = all_session
        self.assertEqual(dashboard_data_api(req_my).status_code, 403)

    @patch('budget_app.models.SystemSettings.load')
    @patch('budget_app.services.BudgetService.get_branch_names_from_imedx', return_value={'CA': 'สาขาเชียงใหม่แอร์พอร์ต', 'MY-BS': 'Moya Bangsaen'})
    @patch('budget_app.services.BudgetService.get_tlph_branches', return_value=[
        {'code': 'CA', 'name': 'สาขาเชียงใหม่แอร์พอร์ต'},
        {'code': 'PM', 'name': 'สาขาประดิษฐ์มนูธรรม'},
    ])
    @patch('budget_app.dashboard_service.get_dashboard_budget_years', return_value=[2025, 2026])
    def test_dashboard_html_has_no_status_filter_and_locks_single_branch(self, mock_yrs, mock_tlph, mock_names, mock_load):
        import os
        from django.conf import settings as dj_settings
        from budget_app.views import dashboard_view
        mock_load.return_value = type('S', (), {'is_frozen': 0, 'frozen_message': '', 'active_budget_year': 2025})()
        factory = RequestFactory()

        # Single-branch MANAGER -> locked to CA, no auto-load on initial entry, has fullscreen toggle & ?v=20261112_02
        req = factory.get('/dashboard/')
        req.user = self._mock_user('mgr_ca')
        req.session = {'branch_info': {'branches': ['CA'], 'is_manager': True, 'is_executive_view_only': False, 'is_district_view_only': False, 'bank_account_note': 'MANAGER'}}
        res = dashboard_view(req)
        self.assertEqual(res.status_code, 200)
        body = res.content.decode('utf-8')
        self.assertIn('id="dashboard-branch-locked" value="CA"', body)
        self.assertIn('"selected_branch": ""', body)
        self.assertIn('id="dashboard-matrix-card"', body)
        self.assertIn('id="btn-dashboard-fullscreen"', body)
        self.assertIn('id="dashboard-top-scroll"', body)
        self.assertIn('id="dashboard-row-count"', body)
        self.assertIn('class="dashboard-table-scroll preset-full"', body)
        self.assertNotIn('data-col-preset=', body)
        self.assertIn('?v=20261112_02', body)
        self.assertNotIn('dashboard-kpi-card', body)
        self.assertNotIn('kpi-rev-budget', body)
        self.assertNotIn('ALL_ACTIVE', body)
        self.assertNotIn('ทุกสาขา', body)

        # All-Branch user (nattchai_u / CFO) -> waits for user branch selection on initial entry (placeholder selected, ALL unselected)
        req_all = factory.get('/dashboard/')
        req_all.user = self._mock_user('nattchai_u')
        req_all.session = {'branch_info': {'branches': ['HO'], 'is_manager': False, 'is_executive_view_only': False, 'is_district_view_only': False, 'bank_account_note': 'IT'}}
        res_all = dashboard_view(req_all)
        self.assertEqual(res_all.status_code, 200)
        body_all = res_all.content.decode('utf-8')
        self.assertIn('<option value="" selected>-- กรุณาเลือกสาขา --</option>', body_all)
        self.assertNotIn('<option value="ALL" selected>', body_all)
        self.assertIn('"selected_branch": ""', body_all)
        self.assertIn('ทุกสาขา (TLPH ทั้งหมด)', body_all)
        self.assertIn('id="dashboard-top-scroll"', body_all)
        self.assertIn('id="btn-dashboard-fullscreen"', body_all)
        self.assertNotIn('dashboard-kpi-card', body_all)
        self.assertNotIn('MY-BS', body_all)

        # Explicit ?branch=ALL deep-link pre-selects ALL; unauthorized ?branch=MY-BS stays empty
        req_explicit = factory.get('/dashboard/?branch=ALL')
        req_explicit.user = self._mock_user('nattchai_u')
        req_explicit.session = req_all.session
        res_explicit = dashboard_view(req_explicit)
        self.assertEqual(res_explicit.status_code, 200)
        body_explicit = res_explicit.content.decode('utf-8')
        self.assertIn('<option value="ALL" selected>', body_explicit)
        self.assertIn('"selected_branch": "ALL"', body_explicit)

        req_unauth_branch = factory.get('/dashboard/?branch=MY-BS')
        req_unauth_branch.user = self._mock_user('nattchai_u')
        req_unauth_branch.session = req_all.session
        self.assertIn('"selected_branch": ""', dashboard_view(req_unauth_branch).content.decode('utf-8'))

        # Verify GL Actual document badge, fullscreen toggle, and idle initial load guard in dashboard.js
        js_path = os.path.join(dj_settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'dashboard.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_src = f.read()
        self.assertIn("GL Actual: ' + escapeHtml(doc.document_no)", js_src)
        self.assertNotIn('escapeHtml(doc.status)', js_src)
        self.assertNotIn('renderKpis', js_src)
        self.assertNotIn('setKpiText', js_src)
        self.assertIn('syncTopScrollBar', js_src)
        self.assertIn('setFullscreen', js_src)
        self.assertIn('renderIdleState', js_src)
        self.assertIn("config.selected_branch && String(config.selected_branch).trim()", js_src)

    def test_sql_filters_branch_year_and_excludes_cancelled(self):
        from budget_app.dashboard_service import _build_monthly_budget_sql_and_params
        sql, params = _build_monthly_budget_sql_and_params('PM', 2025)
        # Expect 15 UNION ALL branches (vet, nonvet sal, nonvet allow, posadj sal, posadj allow, 7 fix assets, gle, rev, bp)
        self.assertEqual(sql.count('UNION ALL'), 14)
        self.assertEqual(sql.count("COALESCE(v.status, '') <> %s"), 15)
        self.assertEqual(sql.count('= %s'), 30)
        self.assertEqual(params.count('PM'), 15)
        self.assertEqual(params.count(2025), 15)
        self.assertEqual(params.count('CANCELLED'), 15)

        # Multi-branch TLPH consolidated SQL uses = ANY(%s) per leg
        sql_multi, params_multi = _build_monthly_budget_sql_and_params(['PM', 'R5'], 2025)
        self.assertEqual(sql_multi.count('= ANY(%s)'), 15)
        self.assertEqual(sql_multi.count('= %s'), 15)
        self.assertEqual(params_multi.count(['PM', 'R5']), 15)
        self.assertEqual(params_multi.count(2025), 15)
        self.assertEqual(params_multi.count('CANCELLED'), 15)

    def _canonical_sample_outline(self):
        return [
            {'id': 1, 'row_order': 1, 'code': 'H1', 'label': 'รายได้', 'row_type': 'header'},
            {'id': 2, 'row_order': 2, 'code': 'H101', 'label': 'รายได้จากการขายและอื่นๆ', 'row_type': 'header'},
            {'id': 3, 'row_order': 3, 'code': '41100001', 'label': 'OPD/IPD', 'row_type': 'gl'},
            {'id': 4, 'row_order': 9, 'code': '41300001', 'label': 'หัก รับคืน', 'row_type': 'gl'},
            {'id': 5, 'row_order': 13, 'code': 'FH101', 'label': 'รวมรายได้', 'row_type': 'subtotal'},
            {'id': 6, 'row_order': 14, 'code': 'H2', 'label': 'ต้นทุนและค่าใช้จ่ายขาย', 'row_type': 'header'},
            {'id': 7, 'row_order': 15, 'code': 'H201', 'label': 'ต้นทุนขาย', 'row_type': 'header'},
            {'id': 8, 'row_order': 16, 'code': '51000002', 'label': 'ต้นทุนสินค้า', 'row_type': 'gl'},
            {'id': 9, 'row_order': 19, 'code': 'FH201', 'label': 'รวมต้นทุนขาย', 'row_type': 'subtotal'},
            {'id': 10, 'row_order': 20, 'code': 'H202', 'label': 'ค่าใช้จ่ายในการขาย', 'row_type': 'header'},
            {'id': 11, 'row_order': 28, 'code': '52000008', 'label': 'ค่าบริการวิชาชีพแพทย์', 'row_type': 'gl'},
            {'id': 12, 'row_order': 33, 'code': 'FH202', 'label': 'รวมค่าใช้จ่ายในการขาย', 'row_type': 'subtotal'},
            {'id': 13, 'row_order': 36, 'code': 'FH203', 'label': 'รวมค่ายานพาหนะ', 'row_type': 'subtotal'},
            {'id': 14, 'row_order': 37, 'code': 'FH2', 'label': 'รวมต้นทุนและค่าใช้จ่ายในการขาย', 'row_type': 'subtotal'},
            {'id': 15, 'row_order': 38, 'code': 'H3', 'label': 'ค่าใช้จ่ายบริหาร', 'row_type': 'header'},
            {'id': 16, 'row_order': 39, 'code': 'H301', 'label': 'เงินเดือน', 'row_type': 'header'},
            {'id': 17, 'row_order': 40, 'code': '60100001', 'label': 'เงินเดือน', 'row_type': 'gl'},
            {'id': 18, 'row_order': 58, 'code': 'FH301', 'label': 'รวมเงินเดือน', 'row_type': 'subtotal'},
            {'id': 19, 'row_order': 142, 'code': 'FH3', 'label': 'รวมค่าใช้จ่ายในการบริหาร', 'row_type': 'subtotal'},
            {'id': 20, 'row_order': 143, 'code': 'FH1-H3', 'label': 'EBITDA', 'row_type': 'subtotal'},
            {'id': 21, 'row_order': 144, 'code': 'H4', 'label': 'ค่าเสื่อมราคา', 'row_type': 'header'},
            {'id': 22, 'row_order': 147, 'code': '61300004', 'label': 'ค่าเสื่อมคอม', 'row_type': 'gl'},
            {'id': 23, 'row_order': 159, 'code': 'FH410', 'label': 'รวมค่าเสื่อม', 'row_type': 'subtotal'},
            {'id': 24, 'row_order': 163, 'code': 'FH401', 'label': 'รวม Asset Movement', 'row_type': 'subtotal'},
            {'id': 25, 'row_order': 164, 'code': 'SP-B', 'label': 'SP-B', 'row_type': 'subtotal'},
            {'id': 26, 'row_order': 166, 'code': '61400001', 'label': 'Back Office', 'row_type': 'gl'},
            {'id': 27, 'row_order': 168, 'code': 'FH5', 'label': 'รวมค่าใช้จ่ายระหว่างกัน', 'row_type': 'subtotal'},
            {'id': 28, 'row_order': 169, 'code': 'H6', 'label': 'EBIT', 'row_type': 'header'},
            {'id': 29, 'row_order': 170, 'code': '42000005', 'label': 'รายได้ค่าเช่า', 'row_type': 'gl'},
            {'id': 30, 'row_order': 172, 'code': '61500002', 'label': 'ดอกเบี้ย', 'row_type': 'gl'},
            {'id': 31, 'row_order': 178, 'code': 'FH7', 'label': 'รวมดอกเบี้ย', 'row_type': 'subtotal'},
            {'id': 32, 'row_order': 179, 'code': 'H8', 'label': 'EBT', 'row_type': 'header'},
            {'id': 33, 'row_order': 180, 'code': '61700001', 'label': 'ภาษีเงินได้', 'row_type': 'gl'},
            {'id': 34, 'row_order': 181, 'code': 'FH8', 'label': 'กำไรสุทธิ', 'row_type': 'subtotal'},
        ]

    @patch('budget_app.dashboard_service.fetch_branch_budget_by_gl')
    @patch('budget_app.dashboard_service.fetch_gl_actual_template_for_branch')
    @patch('budget_app.dashboard_service._get_template_outline')
    def test_pnl_math_rounding_actual_separation_and_xlsx_export(self, mock_outline, mock_actual, mock_budget):
        import io
        import warnings
        from decimal import Decimal
        import openpyxl
        from budget_app.dashboard_service import build_dashboard_data
        from budget_app.xlsx_export import build_dashboard_xlsx

        mock_outline.return_value = self._canonical_sample_outline()
        mock_actual.return_value = {
            'document': {'document_no': 'GLACT-202611-001', 'status': 'PENDING', 'actual_month_count': 9, 'growth_pct_1': 10.0, 'growth_pct_2': 5.0, 'growth_pct_3': 2.0},
            'by_code': {
                '41100001': {'actual_value': Decimal('1000.335'), 'per_month_value': Decimal('111.148'), 'annualized_value': Decimal('1333.784'), 'sales_ratio': Decimal('100.00'), 'growth_rate': Decimal('0.00')},
                'FH101': {'actual_value': Decimal('1000.34'), 'per_month_value': Decimal('111.15'), 'annualized_value': Decimal('1333.78'), 'sales_ratio': Decimal('100.00'), 'growth_rate': Decimal('0.00')},
                'FH8': {'actual_value': Decimal('200.555'), 'per_month_value': Decimal('22.284'), 'annualized_value': Decimal('267.405'), 'sales_ratio': Decimal('20.05'), 'growth_rate': Decimal('0.00')},
            },
            'by_row_order': {},
        }
        # Jan values + 0 for rest, testing P&L cascade, fractional rounding, and standalone 42000005 / 61700001
        zeros = [Decimal('0.00')] * 11
        mock_budget.return_value = {
            '41100001': [Decimal('1000.335')] + zeros,   # -> 1000.34
            '41300001': [Decimal('-100.114')] + zeros,   # -> -100.11  => FH101 = 900.23
            '51000002': [Decimal('200.00')] + zeros,     # => FH201 = 200.00
            '52000008': [Decimal('100.00')] + zeros,     # => FH202 = 100.00 => FH2 = 300.00
            '60100001': [Decimal('150.00')] + zeros,     # => FH301 = FH3 = 150.00 => FH1-H3 = 450.23
            '61300004': [Decimal('50.00')] + zeros,      # => FH410 = 50.00 => SP-B = 400.23
            '61400001': [Decimal('40.00')] + zeros,      # => FH5 = 40.00 => H6 = 360.23
            '42000005': [Decimal('25.00')] + zeros,      # Rental income (must NOT go into FH7!)
            '61500002': [Decimal('10.23')] + zeros,      # => FH7 = 10.23 => H8 = 360.23 + 25.00 - 10.23 = 375.00
            '61700001': [Decimal('75.00')] + zeros,      # => FH8 = 375.00 - 75.00 = 300.00
        }

        payload = build_dashboard_data({'code': 'PM', 'name': 'สาขาประดิษฐ์มนูธรรม'}, 2025)
        rows_by_code = {r['general_ledger_code']: r for r in payload['rows']}

        # No double counting on Actual snapshot
        self.assertNotIn('kpis', payload)
        self.assertEqual(rows_by_code['FH101']['actual_value'], 1000.34)
        self.assertEqual(rows_by_code['FH8']['actual_value'], 200.56)
        self.assertEqual(rows_by_code['41100001']['diff_vs_actual'], -333.44)  # total(1000.34) - raw ann(1333.784) -> -333.444 -> -333.44
        self.assertEqual(rows_by_code['FH8']['diff_vs_actual'], 32.6)          # total(300.00) - raw ann(267.405) -> 32.595 -> 32.60

        # P&L chain & HALF_UP 2dp rounding
        self.assertEqual(rows_by_code['41100001']['january'], 1000.34)
        self.assertEqual(rows_by_code['41300001']['january'], -100.11)
        self.assertEqual(rows_by_code['FH101']['january'], 900.23)
        self.assertEqual(rows_by_code['FH2']['january'], 300.0)
        self.assertEqual(rows_by_code['FH3']['january'], 150.0)
        self.assertEqual(rows_by_code['FH1-H3']['january'], 450.23)
        self.assertEqual(rows_by_code['SP-B']['january'], 400.23)
        self.assertEqual(rows_by_code['H6']['january'], 360.23)
        self.assertEqual(rows_by_code['FH7']['january'], 10.23)
        self.assertEqual(rows_by_code['H8']['january'], 375.0)
        self.assertEqual(rows_by_code['FH8']['january'], 300.0)

        # pct_jan checks (2dp)
        self.assertEqual(rows_by_code['41100001']['pct_jan'], 111.12)  # 1000.34 / 900.23 * 100 = 111.1204 -> 111.12
        self.assertEqual(rows_by_code['FH101']['pct_jan'], 100.0)
        self.assertEqual(rows_by_code['41100001']['pct_feb'], 0.0)     # zero division guard

        # Excel export validation with openpyxl (no warnings)
        xlsx_bytes = build_dashboard_xlsx(payload)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
            self.assertEqual([w for w in caught if 'default style' in str(w.message)], [])
        ws = wb.active
        self.assertEqual(ws.title, 'Dashboard')
        self.assertEqual(ws.max_column, 33)
        self.assertEqual(ws.max_row, len(payload['rows']) + 1)
        self.assertEqual(ws.cell(1, 1).value, 'row_order')
        self.assertEqual(ws.cell(1, 4).value, 'Act จริง')
        self.assertEqual(ws.cell(1, 21).value, 'total')
        self.assertEqual(ws.cell(1, 33).value, 'pct_dec')
        self.assertEqual(ws.freeze_panes, 'D2')
        # Verify final FH8 row values in Excel
        self.assertEqual(ws.cell(ws.max_row, 2).value, 'FH8')
        self.assertEqual(ws.cell(ws.max_row, 4).value, 200.56)
        self.assertEqual(ws.cell(ws.max_row, 9).value, 300.0)
        self.assertEqual(ws.cell(ws.max_row, 21).value, 300.0)

    @patch('budget_app.dashboard_service.fetch_branch_budget_by_gl')
    @patch('budget_app.dashboard_service.fetch_gl_actual_template_for_branch')
    @patch('budget_app.dashboard_service._get_template_outline')
    def test_consolidated_all_tlph_pnl_calculation_and_xlsx_export(self, mock_outline, mock_actual, mock_budget):
        import io
        import warnings
        from decimal import Decimal
        import openpyxl
        from budget_app.dashboard_service import build_dashboard_data
        from budget_app.xlsx_export import build_dashboard_xlsx

        mock_outline.return_value = self._canonical_sample_outline()
        mock_actual.return_value = {
            'document': {
                'document_no': 'รวม 2 สาขา TLPH',
                'status': 'CONSOLIDATED',
                'actual_month_count': 12,
                'growth_pct_1': 5.0,
                'growth_pct_2': 3.0,
                'growth_pct_3': 1.0,
            },
            'by_code': {
                '41100001': {'actual_value': Decimal('2000.00'), 'per_month_value': Decimal('166.67'), 'annualized_value': Decimal('2000.00'), 'sales_ratio': Decimal('100.00'), 'growth_rate': Decimal('2.50')},
                'FH101': {'actual_value': Decimal('2000.00'), 'per_month_value': Decimal('166.67'), 'annualized_value': Decimal('2000.00'), 'sales_ratio': Decimal('100.00'), 'growth_rate': Decimal('2.50')},
                '51000002': {'actual_value': Decimal('500.00'), 'per_month_value': Decimal('41.67'), 'annualized_value': Decimal('500.00'), 'sales_ratio': Decimal('25.00'), 'growth_rate': Decimal('1.00')},
            },
            'by_row_order': {},
        }
        zeros = [Decimal('0.00')] * 11
        mock_budget.return_value = {
            '41100001': [Decimal('2500.005')] + zeros,  # -> 2500.01
            '51000002': [Decimal('600.004')] + zeros,   # -> 600.00
        }

        payload = build_dashboard_data({
            'code': 'ALL',
            'name': 'ทุกสาขา (TLPH ทั้งหมด)',
            'is_all': True,
            'branch_codes': ['PM', 'R5'],
        }, 2025)
        mock_actual.assert_called_once_with(['PM', 'R5'], 2025)
        mock_budget.assert_called_once_with(['PM', 'R5'], 2025)
        self.assertEqual(payload['gl_actual_document']['document_no'], 'รวม 2 สาขา TLPH')

        rows_by_code = {r['general_ledger_code']: r for r in payload['rows']}
        self.assertEqual(rows_by_code['FH101']['january'], 2500.01)
        self.assertEqual(rows_by_code['FH2']['january'], 600.0)
        self.assertEqual(rows_by_code['FH8']['january'], 1900.01)
        self.assertEqual(rows_by_code['51000002']['pct_jan'], 100.0)

        xlsx_bytes = build_dashboard_xlsx(payload)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
            self.assertEqual([w for w in caught if 'default style' in str(w.message)], [])
        ws = wb.active
        self.assertEqual(ws.max_column, 33)
        self.assertEqual(ws.cell(ws.max_row, 2).value, 'FH8')
        self.assertEqual(ws.cell(ws.max_row, 21).value, 1900.01)

    def test_consolidated_gl_actual_computes_h6_h7_h8_sales_ratios(self):
        from datetime import datetime
        from unittest.mock import MagicMock
        from budget_app.dashboard_service import fetch_gl_actual_template_for_branch

        mock_cur = MagicMock()
        mock_cur.fetchall.side_effect = [
            [
                ('PM', 'GLACT-PM', 'APPROVED', 9, 5.0, 3.0, 2.0),
                ('R5', 'GLACT-R5', 'PENDING', 9, 4.0, 2.0, 1.0),
            ],
            [
                ('PM', 13, 'FH101', 'subtotal', 1000.00, 111.11, 1333.33, 100.00, 0.00),
                ('R5', 13, 'FH101', 'subtotal', 1000.00, 111.11, 1333.33, 100.00, 0.00),
                ('PM', 169, 'H6', 'header', 200.00, 22.22, 266.67, 20.00, 0.00),
                ('R5', 169, 'H6', 'header', 100.00, 11.11, 133.33, 10.00, 0.00),
                ('PM', 171, 'H7', 'header', 20.00, 2.22, 26.67, 2.00, 0.00),
                ('R5', 171, 'H7', 'header', 10.00, 1.11, 13.33, 1.00, 0.00),
                ('PM', 179, 'H8', 'header', 180.00, 20.00, 240.00, 18.00, 0.00),
                ('R5', 179, 'H8', 'header', 90.00, 10.00, 120.00, 9.00, 0.00),
            ],
        ]
        mock_ctx = MagicMock()
        mock_ctx.__enter__.return_value = mock_cur
        mock_ctx.__exit__.return_value = False
        with patch('budget_app.dashboard_service.connection') as mock_conn:
            mock_conn.cursor.return_value = mock_ctx
            res = fetch_gl_actual_template_for_branch(['PM', 'R5'], 2025)

        self.assertEqual(float(res['by_code']['FH101']['sales_ratio']), 100.00)
        self.assertEqual(float(res['by_code']['H6']['sales_ratio']), 15.00)
        self.assertEqual(float(res['by_code']['H7']['sales_ratio']), 1.50)
        self.assertEqual(float(res['by_code']['H8']['sales_ratio']), 13.50)


class BudgetCloseFreezeEnforcementTests(SimpleTestCase):
    """When budget close (SystemSettings.is_frozen=1) is active, non-exempt users
    must be completely blocked from creating, editing, and cancelling documents across
    UI (sidebar menu + detail modal buttons + client JS) and backend (all Gunicorn
    workers regardless of LocMemCache, both GET and POST), while exempt users
    (pattida_y, nattchai_u, kanchana_a) retain full access."""

    def _frozen_settings(self):
        return type('Settings', (), {
            'is_frozen': 1,
            'frozen_message': 'ระบบอยู่ระหว่างปิดงบประมาณชั่วคราว',
            'active_budget_year': 2026,
        })()

    @patch('budget_app.models.SystemSettings.load')
    def test_site_status_disables_create_and_edit_cancel_when_frozen_for_regular_users(self, mock_load):
        mock_load.return_value = self._frozen_settings()
        factory = RequestFactory()

        # Regular user while frozen -> cannot add, edit, or cancel
        req_reg = factory.get('/')
        req_reg.user = User(username='mgr01')
        req_reg.session = {'branch_info': {'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False}}
        ctx_reg = site_status(req_reg)
        self.assertTrue(ctx_reg['system_frozen'])
        self.assertFalse(ctx_reg['is_privileged_user'])
        self.assertFalse(ctx_reg['can_add_budget'])
        self.assertFalse(ctx_reg['can_edit_own_documents'])

        # Exempt users (including mixed-case variants) retain full capabilities while frozen
        for uname in ['pattida_y', 'nattchai_u', 'kanchana_a', 'Pattida_Y', 'NATTCHAI_U', 'Kanchana_A']:
            req_priv = factory.get('/')
            req_priv.user = User(username=uname)
            req_priv.session = {'branch_info': {'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False}}
            ctx_priv = site_status(req_priv)
            self.assertTrue(ctx_priv['is_privileged_user'], f"{uname} must stay privileged")
            self.assertTrue(ctx_priv['can_add_budget'], f"{uname} can still create when frozen")
            self.assertTrue(ctx_priv['can_edit_own_documents'], f"{uname} can still edit/cancel when frozen")

    @patch('budget_app.services.BudgetService.get_all_branches', return_value=[])
    @patch('master_data.models.ebudget_gl_actual_template_row.objects')
    @patch('master_data.models.ebudget_cost_center_master.objects')
    @patch('master_data.models.ebudget_budget_item_master.objects')
    @patch('master_data.models.ebudget_budget_category_master.objects')
    @patch('budget_app.models.SystemSettings.load')
    def test_budget_list_html_hides_edit_and_cancel_controls_when_frozen_for_regular_user(
        self, mock_load, mock_cat, mock_item, mock_cc, mock_glat_row, mock_branches
    ):
        mock_load.return_value = self._frozen_settings()
        mock_cats = MagicMock()
        mock_cats.exists.return_value = True
        mock_cats.__iter__.return_value = iter([])
        mock_cat.filter.return_value.order_by.return_value = mock_cats
        mock_item.filter.return_value.order_by.return_value.values.return_value = []
        mock_cc.values.return_value.order_by.return_value = []
        mock_glat_row.order_by.return_value.values.return_value = []

        from budget_app.views import budget_list_view
        factory = RequestFactory()

        # Regular user while frozen -> Edit, Save, Cancel buttons absent from all 4 modals + Add menu absent
        req_reg = factory.get('/')
        req_reg.user = User(username='mgr01', first_name='Mgr')
        req_reg.session = {'branch_info': {'branches': ['AP'], 'needs_selection': False, 'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False}}
        resp_reg = budget_list_view(req_reg)
        html_reg = resp_reg.content.decode('utf-8')
        self.assertIn('ปิดงบประมาณชั่วคราว', html_reg)
        self.assertIn('data-system-frozen="true"', html_reg)
        self.assertNotIn('id="addBudgetToggle"', html_reg)
        for btn_id in [
            'btnEditMode', 'btnSaveDocument', 'btnCancelDocument',
            'btnAdjEditMode', 'btnAdjSaveDocument', 'btnAdjCancelDocument',
            'btnGlEditMode', 'btnGlSaveDocument', 'btnGlCancelDocument',
            'btnGlatEditMode', 'btnGlatSaveDocument', 'btnGlatCancelDocument',
        ]:
            self.assertNotIn(f'id="{btn_id}"', html_reg, f"{btn_id} must be hidden when frozen for regular user")

        # Exempt users while frozen -> still have Add Budget menu and modal Edit/Cancel buttons
        for exempt_user in ['pattida_y', 'nattchai_u', 'kanchana_a']:
            req_priv = factory.get('/')
            req_priv.user = User(username=exempt_user, first_name=exempt_user)
            req_priv.session = {'branch_info': {'branches': ['AP'], 'needs_selection': False, 'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False}}
            resp_priv = budget_list_view(req_priv)
            html_priv = resp_priv.content.decode('utf-8')
            self.assertIn('id="addBudgetToggle"', html_priv, f"{exempt_user} must still see Add Budget menu")
            self.assertIn('id="btnEditMode"', html_priv)
            self.assertIn('id="btnCancelDocument"', html_priv)

    @patch('budget_app.models.SystemSettings.load')
    def test_require_not_frozen_blocks_create_get_and_post_plus_update_and_cancel_apis(self, mock_load):
        from budget_app.views import (
            budget_add_view,
            budget_add_non_vet_view,
            budget_add_adjustment_view,
            budget_add_medical_equipment_view,
            budget_add_gl_entry_view,
            budget_add_revenue_view,
            cancel_document_api,
            update_document_api,
        )
        mock_load.return_value = self._frozen_settings()
        factory = RequestFactory()
        reg_session = {'branch_info': {'branches': ['AP'], 'needs_selection': False, 'is_view_only': False, 'is_executive_view_only': False, 'is_district_view_only': False}}

        # 1. GET to add pages blocked via 302 redirect to budget_list while frozen
        for add_view in [
            budget_add_view,
            budget_add_non_vet_view,
            budget_add_adjustment_view,
            budget_add_medical_equipment_view,
            budget_add_gl_entry_view,
            budget_add_revenue_view,
        ]:
            req_get = factory.get('/')
            req_get.user = User(username='mgr01')
            req_get.session = reg_session
            res_get = add_view(req_get)
            self.assertEqual(res_get.status_code, 302, f"{add_view.__name__} GET must redirect when frozen")
            self.assertEqual(res_get.url, reverse('budget_list'))

        # 2. POST to create, update, cancel blocked with 403 JSON frozen message
        req_add_post = factory.post(reverse('budget_add'), data='[{}]', content_type='application/json')
        req_add_post.user = User(username='mgr01')
        req_add_post.session = reg_session
        res_add_post = budget_add_view(req_add_post)
        self.assertEqual(res_add_post.status_code, 403)
        self.assertEqual(json.loads(res_add_post.content)['message'], 'ระบบอยู่ระหว่างปิดงบประมาณชั่วคราว')

        req_upd = factory.post('/api/document/update/VET/DOC1/', data='[{}]', content_type='application/json')
        req_upd.user = User(username='mgr01')
        req_upd.session = reg_session
        res_upd = update_document_api(req_upd, 'VET', 'DOC1')
        self.assertEqual(res_upd.status_code, 403)
        self.assertEqual(json.loads(res_upd.content)['message'], 'ระบบอยู่ระหว่างปิดงบประมาณชั่วคราว')

        req_can = factory.post('/api/document/cancel/VET/DOC1/', data='{"cancel_reason":"x"}', content_type='application/json')
        req_can.user = User(username='mgr01')
        req_can.session = reg_session
        res_can = cancel_document_api(req_can, 'VET', 'DOC1')
        self.assertEqual(res_can.status_code, 403)
        self.assertEqual(json.loads(res_can.content)['message'], 'ระบบอยู่ระหว่างปิดงบประมาณชั่วคราว')

        # 3. Exempt users (exact and mixed case) pass @require_not_frozen on both create, update, and cancel
        for exempt in ['pattida_y', 'nattchai_u', 'kanchana_a', 'Pattida_Y', 'NATTCHAI_U', 'Kanchana_A']:
            with patch('budget_app.views._resolve_model_class', return_value=None):
                req_c = factory.post('/api/document/cancel/VET/DOC1/', data='{"cancel_reason":"test"}', content_type='application/json')
                req_c.user = User(username=exempt)
                req_c.session = reg_session
                res_c = cancel_document_api(req_c, 'VET', 'DOC1')
                self.assertNotEqual(res_c.status_code, 403, f"{exempt} must bypass freeze on cancel")

            with patch('budget_app.models.ebudget_vet_manpower.objects') as mock_objs:
                mock_objs.filter.return_value.exists.return_value = False
                req_u = factory.post('/api/document/update/VET/DOC1/', data='[{"cost_center_name":"CC1"}]', content_type='application/json')
                req_u.user = User(username=exempt)
                req_u.session = reg_session
                res_u = update_document_api(req_u, 'VET', 'DOC1')
                self.assertNotEqual(res_u.status_code, 403, f"{exempt} must bypass freeze on update")

            req_a = factory.post(reverse('budget_add'), data='[]', content_type='application/json')
            req_a.user = User(username=exempt)
            req_a.session = reg_session
            res_a = budget_add_view(req_a)
            self.assertNotEqual(res_a.status_code, 403, f"{exempt} must bypass freeze on add POST")

    def test_system_settings_load_ignores_stale_locmem_cache_across_workers(self):
        from django.core.cache import cache
        stale_unfrozen = SystemSettings(id=1, is_frozen=0, active_budget_year=2026)
        fresh_frozen = SystemSettings(id=2, is_frozen=1, active_budget_year=2026)

        cache.set('system_settings', stale_unfrozen, 300)
        try:
            with patch('budget_app.models.SystemSettings.objects') as mock_qs:
                mock_qs.order_by.return_value.first.return_value = fresh_frozen
                loaded = SystemSettings.load()
            self.assertEqual(loaded.is_frozen, 1, 'SystemSettings.load() must not return stale per-worker LocMemCache')
        finally:
            cache.delete('system_settings')

    def test_budget_list_js_checks_frozen_state_and_handles_403_json_message(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            js_content = f.read()
        self.assertIn('dataset.systemFrozen', js_content)
        self.assertIn('isSystemFrozen', js_content)
        self.assertIn('response.status === 403', js_content)
