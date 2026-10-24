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
        self.assertIn('modalEquipmentEditor', content)

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
        self.user = User.objects.create_user(username='test_officer', password='x')
        SystemSettings.objects.create(is_frozen=0, active_budget_year=2026)
        self.client.force_login(self.user)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
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
        car_item = ebudget_car.objects.get()
        self.assertEqual(car_item.item_name, 'รถกระบะขนส่ง')
        self.assertEqual(car_item.general_ledger_code, '61300013')
        self.assertIsNone(car_item.item_master)

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
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
        renovate_item = ebudget_renovate.objects.get()
        self.assertEqual(renovate_item.item_name, 'ปรับปรุงห้องผ่าตัด')
        self.assertEqual(renovate_item.general_ledger_code, '61300008')

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
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
        software_item = ebudget_software.objects.get()
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

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
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
        vet_obj = ebudget_vet_manpower.objects.get()
        self.assertEqual(vet_obj.position_name, 'สัตวแพทย์ที่ปรึกษาพิเศษ')
        self.assertIsNone(vet_obj.item_master)
        self.assertIsNone(vet_obj.item_master_id)
        self.assertEqual(vet_obj.general_ledger_code, '61300001')

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
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
        non_vet_obj = ebudget_non_vet_manpower.objects.get()
        self.assertEqual(non_vet_obj.position_name, 'เจ้าหน้าที่ประสานงานโครงการพิเศษ')
        self.assertIsNone(non_vet_obj.item_master)
        self.assertIsNone(non_vet_obj.item_master_id)
        self.assertEqual(non_vet_obj.salary_general_ledger_code, '61300002')
        self.assertEqual(non_vet_obj.position_allowance_general_ledger_code, '61300003')

    @patch('budget_app.services.BudgetService.get_branch_info_from_imedx', return_value={'branches': ['B001'], 'needs_selection': False, 'department_id': None})
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
        adj_obj = ebudget_position_adjustment.objects.get()
        self.assertEqual(adj_obj.old_position_name, 'เจ้าหน้าที่การตลาดเดิม')
        self.assertEqual(adj_obj.new_position_name, 'ผู้จัดการฝ่ายกลยุทธ์ใหม่')
        self.assertIsNone(adj_obj.item_master)
        self.assertIsNone(adj_obj.item_master_id)
        self.assertEqual(adj_obj.salary_general_ledger_code, '61300002')
        self.assertEqual(adj_obj.allowance_general_ledger_code, '61300003')

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

        revenue_html = open(os.path.join(settings.BASE_DIR, 'budget_app', 'templates', 'budget_app', 'budget_add_revenue.html'), encoding='utf-8').read()
        self.assertIn('gl-item-datalist', revenue_html)
        self.assertIn('glEditor', revenue_html)
        self.assertIn('eb-dropdown-cell', revenue_html)
        self.assertIn('onselection', revenue_html)

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


