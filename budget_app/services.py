from django.db import connections, transaction
import logging
from datetime import datetime
from budget_app.models import (
    ebudget_vet_manpower, ebudget_non_vet_manpower, ebudget_position_adjustment,
    ebudget_medical_equipment, ebudget_computer_equipment, ebudget_furniture, ebudget_tools_equipment, BudgetMonthlyDetail,
    ebudget_gl_entry, ebudget_gl_entry_monthly_detail,
    ebudget_budget_plan_item, ebudget_budget_plan_monthly_detail
)
from master_data.models import ebudget_budget_item_master, ebudget_general_ledger_master

logger = logging.getLogger(__name__)

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
    'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
}

class BudgetService:
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

        Also resolves 'is_manager': whether this employee's bank_account_note
        contains "MANAGER" (case-insensitive substring) — independent of
        the branch/BACK logic above, computed the same way regardless of
        which branch path below was taken. Used to let a manager edit
        documents they created themselves (see can_edit_document in
        views.py).

        Returns {'branches': [...], 'needs_selection': bool,
        'department_id': str|None, 'is_manager': bool}. An employee not
        found in imedx, or any DB error, returns branches=[] - matching the
        previous get_branch_id_from_imedx's fail-closed (None) behavior.
        """
        empty = {'branches': [], 'needs_selection': False, 'department_id': None, 'is_manager': False}
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
        is_manager = 'MANAGER' in (bank_account_note or '').upper()

        if bank_sub_name and 'BACK' in sub_name_upper:
            department_id = None
            marker = sub_name_upper.find('BACK-')
            if marker != -1:
                department_id = bank_sub_name[marker + len('BACK-'):].strip() or None
            return {'branches': ['HO'], 'needs_selection': False, 'department_id': department_id, 'is_manager': is_manager}

        if bank_sub_name and bank_sub_name.strip():
            branches = [b.strip() for b in bank_sub_name.split(',') if b.strip()]
            if branches:
                return {'branches': branches, 'needs_selection': len(branches) > 1, 'department_id': None, 'is_manager': is_manager}

        if fallback_branch_id:
            return {'branches': [fallback_branch_id], 'needs_selection': False, 'department_id': None, 'is_manager': is_manager}
        return {'branches': [], 'needs_selection': False, 'department_id': None, 'is_manager': is_manager}

    @staticmethod
    def get_branch_names_from_imedx(codes):
        """Bulk code->name lookup for the branch-picker dropdown (only
        needed for the rare multi-branch case) - one query for the whole
        list instead of one per code. Returns {code: name}; a code with no
        match in base_site_branch is simply absent."""
        codes = [c for c in set(codes) if c]
        if not codes:
            return {}
        try:
            with connections['imedx'].cursor() as cursor:
                cursor.execute(
                    "SELECT base_site_branch_id, description FROM base_site_branch WHERE base_site_branch_id = ANY(%s)",
                    [codes]
                )
                return {code: name for code, name in cursor.fetchall()}
        except Exception as e:
            logger.error(f"Error fetching branch names for {codes}: {e}")
            return {}

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
    def get_master_fks_bulk(item_names):
        """Batch version of get_master_fks: one query for a whole submitted
        document instead of one per line item. Returns
        {item_name: (master_obj, gl_code)}; a name with no master record is
        simply absent, so callers should look it up with
        `.get(name, (None, None))` to match get_master_fks's None fallback."""
        try:
            masters = ebudget_budget_item_master.objects.filter(
                item_name__in=set(item_names)
            )
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
            'GL Entry': 'GLE',
            'Budget Plan': 'PLAN'
        }
        model_map = {
            'VET': ebudget_vet_manpower,
            'NON VET': ebudget_non_vet_manpower,
            'Position Adjustment': ebudget_position_adjustment,
            'Medical Equipment': ebudget_medical_equipment,
            'Computer Equipment': ebudget_computer_equipment,
            'Furniture': ebudget_furniture,
            'Tools & Equipment': ebudget_tools_equipment,
            'GL Entry': ebudget_gl_entry,
            'Budget Plan': ebudget_budget_plan_item
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
            'Tools & Equipment': 'tools_equip'
        }
        fk_field = fk_field_map.get(doc_type)
        if not fk_field:
            return
            
        BudgetMonthlyDetail.objects.filter(**{fk_field: parent_obj}).delete()
        
        for month_str, data in monthly_data_dict.items():
            month_int = MONTH_MAP.get(month_str.lower())
            if not month_int:
                continue
                
            headcount = data.get('headcount') or data.get('count') or 0
            cost = data.get('cost') or 0
            
            BudgetMonthlyDetail.objects.create(
                month=month_int,
                headcount=headcount,
                cost=cost,
                **{fk_field: parent_obj}
            )

    @staticmethod
    @transaction.atomic
    def save_gl_entry_monthly_data(parent_obj, monthly_data_dict):
        """Same delete-and-recreate pattern as save_monthly_data, but for
        ebudget_gl_entry_monthly_detail's shape (detail_note/amount/
        cumulative_amount) — GL entries have no headcount concept, so they
        don't fit BudgetMonthlyDetail's {headcount, cost} columns."""
        ebudget_gl_entry_monthly_detail.objects.filter(gl_entry=parent_obj).delete()

        for month_str, data in monthly_data_dict.items():
            month_int = MONTH_MAP.get(month_str.lower())
            if not month_int:
                continue

            ebudget_gl_entry_monthly_detail.objects.create(
                month=month_int,
                detail_note=data.get('detail_note') or None,
                amount=data.get('amount') or 0,
                cumulative_amount=data.get('cumulative_amount') or 0,
                gl_entry=parent_obj
            )

    @staticmethod
    @transaction.atomic
    def save_budget_plan_monthly_data(parent_obj, monthly_data_dict):
        """Same delete-and-recreate pattern as save_gl_entry_monthly_data, but
        for ebudget_budget_plan_monthly_detail's shape: a single amount per
        month, no detail_note/cumulative_amount."""
        ebudget_budget_plan_monthly_detail.objects.filter(plan_item=parent_obj).delete()

        for month_str, data in monthly_data_dict.items():
            month_int = MONTH_MAP.get(month_str.lower())
            if not month_int:
                continue

            ebudget_budget_plan_monthly_detail.objects.create(
                month=month_int,
                amount=data.get('amount') or 0,
                plan_item=parent_obj
            )
