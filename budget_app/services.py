from django.db import connections, transaction
from django.db.models import Q
import logging
from datetime import datetime
from budget_app.models import (
    ebudget_vet_manpower, ebudget_non_vet_manpower, ebudget_position_adjustment,
    ebudget_medical_equipment, ebudget_computer_equipment, ebudget_furniture, ebudget_tools_equipment, ebudget_car, ebudget_renovate, ebudget_software, BudgetMonthlyDetail,
    ebudget_gl_entry, ebudget_gl_entry_monthly_detail,
    ebudget_revenue, ebudget_revenue_monthly_detail,
    ebudget_budget_plan_item, ebudget_budget_plan_monthly_detail,
    ebudget_gl_actual_template
)
from master_data.models import ebudget_budget_item_master, ebudget_general_ledger_master, ebudget_cost_center_master
from budget_app.constants import EXECUTIVE_VIEW_ONLY_ROLES, STATUS_CANCELLED, GL_ACTUAL_TEMPLATE_BRANCHES

logger = logging.getLogger(__name__)

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
    'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
}

class BudgetService:
    @staticmethod
    def is_executive_role(bank_account_note):
        """Checks if a bank_account_note matches any executive view-only roles (CHRO, CFO, COO)."""
        if not bank_account_note:
            return False
        return (bank_account_note or '').strip().upper() in EXECUTIVE_VIEW_ONLY_ROLES

    @staticmethod
    def get_branch_info_from_imedx(username):
        """Resolves which branch(es) an employee belongs to, and whether the
        add-budget UI must ask which one to stamp. Field roles, confirmed
        with the business owner after real imedx data showed the "BACK-"
        marker actually lives in bank_sub_name (not bank_account_note, as
        first assumed — a real employee, 'banchong', has
        bank_sub_name='BACK-IT'): **bank_sub_name is always where branch
        info comes from** (plain codes, comma-separated multi-branch, or
        the "BACK-<dept>" back-office marker); **bank_account_note is
        always position/role info** (e.g. "MANAGER" — see is_manager
        below), never branch codes.

        Priority:
        1. bank_sub_name containing "BACK" (back-office staff) always wins
           over the plain-branch-code reading below: stamps
           base_branch_id='HO' and department_id from the substring after
           "BACK-".
        2. Otherwise, bank_sub_name if set: comma-separated branch codes.
           More than one means the caller must ask the user which branch
           to stamp.
        3. Falls back to the pre-existing base_service_point lookup when
           bank_sub_name is blank - true for ~91% of active employees
           today (checked directly against imedx), so this path has to
           keep behaving exactly as it did before this feature existed,
           or budget creation breaks for almost everyone.

        Also resolves 'is_manager' and 'is_executive_view_only':
        - 'is_manager': whether bank_account_note contains "MANAGER"
        - 'is_executive_view_only': whether bank_account_note matches
          CHRO, CFO, or COO (sees all documents, can view details, but
          cannot edit or cancel).

        Returns {'branches': [...], 'needs_selection': bool,
        'department_id': str|None, 'is_manager': bool,
        'bank_account_note': str|None, 'is_executive_view_only': bool}.
        An employee not found in imedx, or any DB error, returns branches=[] -
        matching the previous get_branch_id_from_imedx's fail-closed (None) behavior.
        """
        empty = {
            'branches': [],
            'needs_selection': False,
            'department_id': None,
            'is_manager': False,
            'bank_account_note': None,
            'is_executive_view_only': False,
        }
        try:
            with connections['imedx'].cursor() as cursor:
                cursor.execute("""
                    SELECT emp.bank_sub_name, emp.bank_account_note, bsp.base_site_branch_id
                    FROM employee emp
                    LEFT JOIN base_service_point bsp ON emp.base_service_point_id = bsp.base_service_point_id
                    WHERE emp.employee_id = %s AND emp.active = '1'
                """, [username])
                row = cursor.fetchone()
        except Exception as e:
            logger.error(f"Error fetching branch info for {username}: {e}")
            return empty

        if not row:
            return empty
        bank_sub_name, bank_account_note, fallback_branch_id = row
        sub_name_upper = (bank_sub_name or '').upper()
        note_clean = (bank_account_note or '').strip()
        is_manager = 'MANAGER' in note_clean.upper()
        is_executive = BudgetService.is_executive_role(note_clean)

        if bank_sub_name and 'BACK' in sub_name_upper:
            valid_branch_ids = {code for code, _ in GL_ACTUAL_TEMPLATE_BRANCHES if code != 'HO'}
            try:
                with connections['default'].cursor() as cursor:
                    cursor.execute("SELECT sub_branch_id FROM base_sub_branch")
                    for r in cursor.fetchall():
                        if r and r[0] and r[0].strip().upper() != 'HO':
                            valid_branch_ids.add(r[0].strip().upper())
            except Exception as e:
                logger.warning(f"Error fetching base_sub_branch for BACK user parsing: {e}")
            try:
                with connections['imedx'].cursor() as cursor:
                    cursor.execute("SELECT base_site_branch_id FROM base_site_branch")
                    for r in cursor.fetchall():
                        if r and r[0]:
                            valid_branch_ids.add(r[0].strip().upper())
            except Exception as e:
                logger.warning(f"Error fetching base_site_branch for BACK user parsing: {e}")

            raw_tokens = [t.strip() for t in bank_sub_name.split(',') if t.strip()]
            branch_codes = []
            dept_tokens = []

            for token in raw_tokens:
                token_upper = token.upper()
                marker = token_upper.find('BACK-')
                if marker != -1:
                    dept_part = token[marker + len('BACK-'):].strip()
                    if dept_part:
                        dept_tokens.append(dept_part)
                elif token_upper == 'BACK':
                    continue
                elif token_upper == 'HO' or token_upper in valid_branch_ids:
                    if token_upper not in branch_codes:
                        branch_codes.append(token_upper)
                else:
                    dept_tokens.append(token)

            department_id = ','.join(dept_tokens).strip() or None

            if branch_codes:
                branches = list(branch_codes)
                if 'HO' not in branches:
                    branches.append('HO')
                return {
                    'branches': branches,
                    'needs_selection': len(branches) > 1,
                    'department_id': department_id,
                    'is_manager': is_manager,
                    'bank_account_note': note_clean,
                    'is_executive_view_only': is_executive,
                }
            else:
                return {
                    'branches': ['HO'],
                    'needs_selection': False,
                    'department_id': department_id,
                    'is_manager': is_manager,
                    'bank_account_note': note_clean,
                    'is_executive_view_only': is_executive,
                }

        if bank_sub_name and bank_sub_name.strip():
            branches = [b.strip() for b in bank_sub_name.split(',') if b.strip()]
            if branches:
                return {
                    'branches': branches,
                    'needs_selection': len(branches) > 1,
                    'department_id': None,
                    'is_manager': is_manager,
                    'bank_account_note': note_clean,
                    'is_executive_view_only': is_executive,
                }

        if fallback_branch_id:
            return {
                'branches': [fallback_branch_id],
                'needs_selection': False,
                'department_id': None,
                'is_manager': is_manager,
                'bank_account_note': note_clean,
                'is_executive_view_only': is_executive,
            }
        return {
            'branches': [],
            'needs_selection': False,
            'department_id': None,
            'is_manager': is_manager,
            'bank_account_note': note_clean,
            'is_executive_view_only': is_executive,
        }

    @staticmethod
    def get_branch_names_from_imedx(codes):
        """Bulk code->name lookup for the branch-picker dropdown.
        Fetches code and description from base_sub_branch in the default database,
        with fallback/enrichment from imedx base_site_branch and
        GL_ACTUAL_TEMPLATE_BRANCHES (ensuring 'BN' -> 'สาขาบางนา', 'HO' -> 'สำนักงานใหญ่', etc.)."""
        codes = [c for c in set(codes) if c]
        if not codes:
            return {}
        result = {}
        fallback_map = dict(GL_ACTUAL_TEMPLATE_BRANCHES)
        for code in codes:
            if code in fallback_map:
                result[code] = fallback_map[code]

        # Primary lookup from base_sub_branch (default database)
        try:
            with connections['default'].cursor() as cursor:
                cursor.execute(
                    "SELECT sub_branch_id, sub_branch_name FROM base_sub_branch WHERE sub_branch_id = ANY(%s)",
                    [codes]
                )
                for code, name in cursor.fetchall():
                    if name:
                        result[code] = name.strip()
        except Exception as e:
            logger.warning(f"Error fetching branch names from base_sub_branch for {codes}: {e}")

        # Fallback/enrichment from imedx base_site_branch if any codes are still missing
        missing = [c for c in codes if c not in result]
        if missing:
            try:
                with connections['imedx'].cursor() as cursor:
                    cursor.execute(
                        "SELECT base_site_branch_id, description FROM base_site_branch WHERE base_site_branch_id = ANY(%s)",
                        [missing]
                    )
                    for code, name in cursor.fetchall():
                        if name and code not in result:
                            result[code] = name.strip()
            except Exception as e:
                logger.warning(f"Error fetching branch names from base_site_branch for {missing}: {e}")
        return result

    get_branch_names = get_branch_names_from_imedx

    @staticmethod
    def get_all_branches():
        """Returns all branches (code and name) from base_sub_branch in the default database,
        falling back to GL_ACTUAL_TEMPLATE_BRANCHES if table is unavailable."""
        branches = []
        try:
            with connections['default'].cursor() as cursor:
                cursor.execute(
                    "SELECT sub_branch_id, sub_branch_name FROM base_sub_branch ORDER BY sub_branch_id"
                )
                rows = cursor.fetchall()
                if rows:
                    for code, name in rows:
                        if code and name:
                            branches.append({'code': code.strip(), 'name': name.strip()})
                    return branches
        except Exception as e:
            logger.warning(f"Error fetching all branches from base_sub_branch: {e}")
        return [{'code': code, 'name': name} for code, name in GL_ACTUAL_TEMPLATE_BRANCHES]

    @staticmethod
    def get_master_fks(item_name_val):
        try:
            master = ebudget_budget_item_master.objects.filter(item_name=item_name_val).first()
            if master:
                return master, master.general_ledger_code
        except Exception:
            pass
        return None, None

    @staticmethod
    def get_master_fks_bulk(item_names, category_id=None, sub_category_id=None):
        """Batch version of get_master_fks: one query for a whole submitted
        document instead of one per line item. Returns
        {item_name: (master_obj, gl_code)}; a name with no master record is
        simply absent, so callers should look it up with
        `.get(name, (None, None))` to match get_master_fks's None fallback."""
        try:
            masters = ebudget_budget_item_master.objects.filter(
                item_name__in=set(item_names)
            )
            if category_id is not None:
                masters = masters.filter(category_id=category_id)
            if sub_category_id is not None:
                masters = masters.filter(sub_category_id=sub_category_id)
            return {m.item_name: (m, m.general_ledger_code) for m in masters}
        except Exception:
            return {}

    @staticmethod
    def get_gl_master_fields_bulk(gl_codes):
        """Batch lookup of proportion/depreciation from GL master, keyed by
        gl_code — one query per submitted document instead of one per line
        item. Returns {gl_code: (proportion, depreciation)}; a code with no
        master record is simply absent, so callers should look it up with
        `.get(code, (0, 0))`. These values are snapshotted onto ebudget_gl_entry
        at save time and are never trusted from the client — always
        recomputed here from general_ledger_code so they can't drift from
        GL master or be spoofed by a crafted request."""
        try:
            masters = ebudget_general_ledger_master.objects.filter(
                gl_code__in=set(filter(None, gl_codes))
            )
            return {m.gl_code: (m.proportion, m.depreciation) for m in masters}
        except Exception:
            return {}

    @staticmethod
    def generate_document_no(doc_type):
        prefix_map = {
            'VET': 'VET',
            'NON VET': 'NONVET',
            'Position Adjustment': 'ADJ',
            'Medical Equipment': 'MED',
            'Computer Equipment': 'COM',
            'Furniture': 'FUR',
            'Tools & Equipment': 'TEQ',
            'CAR': 'CAR',
            'Renovate': 'REN',
            'Software': 'SW',
            'GL Entry': 'GLE',
            'Revenue': 'REV',
            'Budget Plan': 'PLAN',
            'GL Actual Template': 'GLACT'
        }
        model_map = {
            'VET': ebudget_vet_manpower,
            'NON VET': ebudget_non_vet_manpower,
            'Position Adjustment': ebudget_position_adjustment,
            'Medical Equipment': ebudget_medical_equipment,
            'Computer Equipment': ebudget_computer_equipment,
            'Furniture': ebudget_furniture,
            'Tools & Equipment': ebudget_tools_equipment,
            'CAR': ebudget_car,
            'Renovate': ebudget_renovate,
            'Software': ebudget_software,
            'GL Entry': ebudget_gl_entry,
            'Revenue': ebudget_revenue,
            'Budget Plan': ebudget_budget_plan_item,
            'GL Actual Template': ebudget_gl_actual_template
        }
        
        prefix_code = prefix_map.get(doc_type, 'DOC')
        today_str = datetime.now().strftime('%Y%m')
        prefix = f"{prefix_code}-{today_str}-"
        
        model_class = model_map.get(doc_type)
        if not model_class:
            return f"{prefix}001"
            
        last_doc = model_class.objects.filter(document_no__startswith=prefix).order_by('-document_no').first()
        if last_doc and last_doc.document_no:
            last_number_str = last_doc.document_no.split('-')[-1]
            try:
                new_number = int(last_number_str) + 1
            except ValueError:
                new_number = 1
        else:
            new_number = 1
            
        return f"{prefix}{new_number:03d}"

    @staticmethod
    @transaction.atomic
    def save_monthly_data(parent_obj, doc_type, monthly_data_dict):
        fk_field_map = {
            'VET': 'vet_budget',
            'NON VET': 'non_vet_budget',
            'Position Adjustment': 'position_adj',
            'Medical Equipment': 'med_equip',
            'Computer Equipment': 'comp_equip',
            'Furniture': 'furniture_equip',
            'Tools & Equipment': 'tools_equip',
            'CAR': 'car_equip',
            'Renovate': 'renovate_equip',
            'Software': 'software_equip'
        }
        fk_field = fk_field_map.get(doc_type)
        if not fk_field:
            return

        is_fix_asset = doc_type in (
            'Medical Equipment', 'Computer Equipment', 'Furniture',
            'Tools & Equipment', 'CAR', 'Renovate', 'Software'
        )
        gl_depreciation = 0.0
        if is_fix_asset:
            gl_code = getattr(parent_obj, 'general_ledger_code', None)
            if gl_code:
                try:
                    from master_data.models import ebudget_general_ledger_master
                    gl_master = ebudget_general_ledger_master.objects.filter(gl_code=gl_code).first()
                    if gl_master and gl_master.depreciation:
                        gl_depreciation = float(gl_master.depreciation)
                except Exception:
                    gl_depreciation = 0.0

        sorted_months = []
        for month_str, data in monthly_data_dict.items():
            month_int = MONTH_MAP.get(month_str.lower())
            if month_int:
                sorted_months.append((month_int, data))
        sorted_months.sort(key=lambda x: x[0])

        running_dep = 0.0
        running_headcount = 0.0
        row_salary = float(getattr(parent_obj, 'salary', 0) or 0)
        row_allowance = float(getattr(parent_obj, 'position_allowance', 0) or 0)
        old_salary = float(getattr(parent_obj, 'old_salary', 0) or 0)
        old_allowance = float(getattr(parent_obj, 'old_allowance', 0) or 0)
        new_salary = float(getattr(parent_obj, 'new_salary', 0) or 0)
        new_allowance = float(getattr(parent_obj, 'new_allowance', 0) or 0)

        existing_details = {d.month: d for d in BudgetMonthlyDetail.objects.filter(**{fk_field: parent_obj})}

        for month_int, data in sorted_months:
            headcount = data.get('headcount') or data.get('count') or 0
            if doc_type in (
                'VET', 'NON VET', 'Position Adjustment',
                'Medical Equipment', 'Computer Equipment', 'Furniture',
                'Tools & Equipment', 'CAR', 'Renovate', 'Software'
            ):
                try:
                    headcount = max(0, int(round(float(headcount))))
                except (ValueError, TypeError):
                    headcount = 0
            cost = data.get('cost') or 0
            try:
                cost_num = float(cost)
            except (ValueError, TypeError):
                cost_num = 0.0

            cum_dep = 0.0
            if is_fix_asset and gl_depreciation > 0:
                running_dep += cost_num / (gl_depreciation * 12.0)
                cum_dep = round(running_dep, 2)

            m_salary = 0.0
            m_allowance = 0.0
            m_new_salary = 0.0
            m_new_allowance = 0.0
            if doc_type == 'NON VET':
                running_headcount += headcount
                m_salary = round(running_headcount * row_salary, 2)
                m_allowance = round(running_headcount * row_allowance, 2)
            elif doc_type == 'Position Adjustment':
                running_headcount += headcount
                m_salary = round(running_headcount * old_salary, 2)
                m_allowance = round(running_headcount * old_allowance, 2)
                m_new_salary = round(running_headcount * new_salary, 2)
                m_new_allowance = round(running_headcount * new_allowance, 2)

            if month_int in existing_details:
                detail = existing_details[month_int]
                detail.headcount = headcount
                detail.cost = cost
                detail.salary = m_salary
                detail.position_allowance = m_allowance
                detail.new_salary = m_new_salary
                detail.new_allowance = m_new_allowance
                detail.cumulative_depreciation = cum_dep
                detail.save(update_fields=[
                    'headcount', 'cost', 'salary', 'position_allowance',
                    'new_salary', 'new_allowance', 'cumulative_depreciation'
                ])
            else:
                BudgetMonthlyDetail.objects.create(
                    month=month_int,
                    headcount=headcount,
                    cost=cost,
                    salary=m_salary,
                    position_allowance=m_allowance,
                    new_salary=m_new_salary,
                    new_allowance=m_new_allowance,
                    cumulative_depreciation=cum_dep,
                    **{fk_field: parent_obj}
                )

    @staticmethod
    @transaction.atomic
    def save_gl_entry_monthly_data(parent_obj, monthly_data_dict):
        """In-place upsert for ebudget_gl_entry_monthly_detail — preserves
        existing record IDs when editing to prevent sequence churn."""
        existing_details = {d.month: d for d in ebudget_gl_entry_monthly_detail.objects.filter(gl_entry=parent_obj)}

        for month_str, data in monthly_data_dict.items():
            month_int = MONTH_MAP.get(month_str.lower())
            if not month_int:
                continue

            detail_note = data.get('detail_note') or None
            amount = data.get('amount') or 0
            cumulative_amount = data.get('cumulative_amount') or 0

            if month_int in existing_details:
                d = existing_details[month_int]
                d.detail_note = detail_note
                d.amount = amount
                d.cumulative_amount = cumulative_amount
                d.save(update_fields=['detail_note', 'amount', 'cumulative_amount'])
            else:
                ebudget_gl_entry_monthly_detail.objects.create(
                    month=month_int,
                    detail_note=detail_note,
                    amount=amount,
                    cumulative_amount=cumulative_amount,
                    gl_entry=parent_obj
                )

    @staticmethod
    @transaction.atomic
    def save_revenue_monthly_data(parent_obj, monthly_data_dict):
        """In-place upsert for ebudget_revenue_monthly_detail — preserves
        existing record IDs when editing to prevent sequence churn."""
        existing_details = {d.month: d for d in ebudget_revenue_monthly_detail.objects.filter(revenue_entry=parent_obj)}

        for month_str, data in monthly_data_dict.items():
            month_int = MONTH_MAP.get(month_str.lower())
            if not month_int:
                continue

            detail_note = data.get('detail_note') or None
            amount = data.get('amount') or 0
            cumulative_amount = data.get('cumulative_amount') or 0

            if month_int in existing_details:
                d = existing_details[month_int]
                d.detail_note = detail_note
                d.amount = amount
                d.cumulative_amount = cumulative_amount
                d.save(update_fields=['detail_note', 'amount', 'cumulative_amount'])
            else:
                ebudget_revenue_monthly_detail.objects.create(
                    month=month_int,
                    detail_note=detail_note,
                    amount=amount,
                    cumulative_amount=cumulative_amount,
                    revenue_entry=parent_obj
                )

    @staticmethod
    @transaction.atomic
    def save_budget_plan_monthly_data(parent_obj, monthly_data_dict):
        """In-place upsert for ebudget_budget_plan_monthly_detail — preserves
        existing record IDs when editing to prevent sequence churn."""
        existing_details = {d.month: d for d in ebudget_budget_plan_monthly_detail.objects.filter(plan_item=parent_obj)}

        for month_str, data in monthly_data_dict.items():
            month_int = MONTH_MAP.get(month_str.lower())
            if not month_int:
                continue

            amount = data.get('amount') or 0

            if month_int in existing_details:
                d = existing_details[month_int]
                d.amount = amount
                d.save(update_fields=['amount'])
            else:
                ebudget_budget_plan_monthly_detail.objects.create(
                    month=month_int,
                    amount=amount,
                    plan_item=parent_obj
                )

    @staticmethod
    def resolve_canonical_cost_center_name(raw_name):
        """Resolves any cost center identifier (code '0001', abbreviation 'PH',
        composite '0001: PH (Pet Hospital+Pet Taxi)', or full name
        'PH (Pet Hospital+Pet Taxi)') to its canonical master cost_center_name.
        Returns the canonical name if resolved, or the stripped input string."""
        if not raw_name:
            return None
        val = str(raw_name).strip()
        if not val:
            return None
        try:
            # 1. Exact match on cost_center_name
            cc = ebudget_cost_center_master.objects.filter(cost_center_name__iexact=val).first()
            if cc:
                return cc.cost_center_name

            # 2. Exact match on cost_center_code
            cc = ebudget_cost_center_master.objects.filter(cost_center_code__iexact=val).first()
            if cc:
                return cc.cost_center_name

            # 3. Formats with colon e.g. "0001: PH (Pet Hospital+Pet Taxi)"
            if ':' in val:
                code_part, name_part = val.split(':', 1)
                code_part = code_part.strip()
                name_part = name_part.strip()
                cc = ebudget_cost_center_master.objects.filter(
                    Q(cost_center_code__iexact=code_part) |
                    Q(cost_center_name__iexact=name_part) |
                    Q(cost_center_name__istartswith=name_part)
                ).first()
                if cc:
                    return cc.cost_center_name

            # 4. Matches prefix e.g. "PH" -> "PH (Pet Hospital+Pet Taxi)"
            cc = ebudget_cost_center_master.objects.filter(
                Q(cost_center_name__istartswith=f"{val} ") |
                Q(cost_center_name__istartswith=f"{val}(") |
                Q(cost_center_name__istartswith=val)
            ).first()
            if cc:
                return cc.cost_center_name

            # 5. Fallback contains match
            cc = ebudget_cost_center_master.objects.filter(cost_center_name__icontains=val).first()
            if cc:
                return cc.cost_center_name
        except Exception as e:
            logger.warning(f"Error resolving canonical cost center name: {e}")
        return val

    @staticmethod
    def find_existing_budget_document(model_class, create_eid, budget_year, base_branch_id, cost_center_name=None):
        """Checks if an active (non-cancelled) budget document already exists
        for the given creator, budget year, branch, and cost center.
        Returns a dict of document info if found, or None."""
        if not model_class or not create_eid or not budget_year or not base_branch_id:
            return None
        try:
            year_val = int(budget_year)
        except (ValueError, TypeError):
            return None

        filter_kwargs = {
            'create_eid__iexact': str(create_eid).strip(),
            'budget_year': year_val,
            'base_branch_id__iexact': str(base_branch_id).strip(),
        }

        has_cc_field = False
        try:
            model_class._meta.get_field('cost_center_name')
            has_cc_field = True
        except Exception:
            has_cc_field = False

        if has_cc_field and cost_center_name:
            raw_cc = str(cost_center_name).strip()
            canonical_cc = BudgetService.resolve_canonical_cost_center_name(raw_cc)
            if canonical_cc and canonical_cc != raw_cc:
                cc_query = Q(cost_center_name__iexact=raw_cc) | Q(cost_center_name__iexact=canonical_cc) | Q(cost_center_name__istartswith=raw_cc)
                if '(' in canonical_cc:
                    short_prefix = canonical_cc.split('(')[0].strip()
                    if short_prefix:
                        cc_query |= Q(cost_center_name__iexact=short_prefix)
                qs = model_class.objects.filter(cc_query, **filter_kwargs).exclude(status=STATUS_CANCELLED)
            else:
                filter_kwargs['cost_center_name__iexact'] = raw_cc
                qs = model_class.objects.filter(**filter_kwargs).exclude(status=STATUS_CANCELLED)
        else:
            qs = model_class.objects.filter(**filter_kwargs).exclude(status=STATUS_CANCELLED)

        qs = qs.order_by('-create_date')

        values_fields = ['document_no', 'budget_year', 'base_branch_id', 'status']
        if has_cc_field:
            values_fields.append('cost_center_name')

        return qs.values(*values_fields).first()


def is_executive_view_only_user(request):
    """Returns True if the authenticated user has an executive view-only role
    (CHRO, CFO, COO) based on their iMedX bank_account_note. Local superusers
    and ALL_BRANCH_USERNAMES bypass this to preserve admin/privileged capabilities."""
    if not request or not getattr(request, 'user', None) or not request.user.is_authenticated:
        return False
    from budget_app.constants import ALL_BRANCH_USERNAMES
    if request.user.is_superuser or request.user.username in ALL_BRANCH_USERNAMES:
        return False
    session = getattr(request, 'session', None)
    if session is not None:
        info = session.get('branch_info')
        if info is None or 'is_executive_view_only' not in info:
            info = BudgetService.get_branch_info_from_imedx(request.user.username)
            session['branch_info'] = info
        return bool(info.get('is_executive_view_only', False))
    info = BudgetService.get_branch_info_from_imedx(request.user.username)
    return bool(info.get('is_executive_view_only', False))

