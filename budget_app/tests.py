import json
import os
import re
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from budget_app.constants import (
    ALL_BRANCH_USERNAMES,
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
            self.assertIn('salary < 5000', content, f"{tpl} must enforce salary < 5000")
            self.assertIn('5,000 บาทขึ้นไป', content, f"{tpl} must contain formal 5000 THB warning")

    def test_budget_list_js_enforces_min_purchase_price_5000(self):
        js_path = os.path.join(settings.BASE_DIR, 'budget_app', 'static', 'budget_app', 'js', 'budget_list.js')
        with open(js_path, 'r', encoding='utf-8') as f:
            content = f.read()
        self.assertIn('isEquipment && salary < 5000', content)
        self.assertIn('5,000 บาทขึ้นไป', content)

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
        res_b = cancel_document_api(req_b, 'VET', 'DOC001')
        self.assertEqual(res_b.status_code, 200)
        self.assertEqual(json.loads(res_b.content).get('message'), 'คุณยกเลิกได้เฉพาะเอกสารที่ตัวเองสร้างเท่านั้น')

        # Regular user 'user_a' cancels their own doc -> ALLOWED
        req_a = factory.post('/api/document/cancel/VET/DOC001/', data=json.dumps({'cancel_reason': 'test'}), content_type='application/json')
        req_a.user = MagicMock(is_authenticated=True, username='user_a', is_superuser=False)
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
        req_b.session = {}
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
        self.assertIn('calcColumns.push({ type: \'numeric\', title: m, width: 85, readOnly: true, mask: \'#,##0\' });', js_content)

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

        # Must NOT have onselection auto-opening editors in modalTable1 or adjTable1
        self.assertNotIn("onselection: function(el, x1, y1, x2, y2, origin) {\n                    const sheet = (el && el.jexcel) || modalTable1;", js_content)
        self.assertNotIn("onselection: function(el, x1, y1, x2, y2, origin) {\n                    const sheet = (el && el.jexcel) || adjTable1;", js_content)

        # Must have resetSelection and clean click listener bound for dropdown cells
        self.assertIn('modalTable1.resetSelection(true);', js_content)
        self.assertIn('adjTable1.resetSelection(true);', js_content)
        self.assertIn("e.target.closest('td.eb-dropdown-cell')", js_content)


