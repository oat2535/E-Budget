from django.db import connections, transaction
import logging
from datetime import datetime
from budget_app.models import (
    ebudget_vet_manpower, ebudget_non_vet_manpower, ebudget_position_adjustment,
    ebudget_medical_equipment, ebudget_computer_equipment, ebudget_furniture, ebudget_tools_equipment, BudgetMonthlyDetail,
    ebudget_gl_entry, ebudget_gl_entry_monthly_detail,
    ebudget_budget_plan_item, ebudget_budget_plan_monthly_detail
)
from master_data.models import ebudget_budget_item_master

logger = logging.getLogger(__name__)

MONTH_MAP = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4,
    'may': 5, 'jun': 6, 'jul': 7, 'aug': 8,
    'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
}

class BudgetService:
    @staticmethod
    def get_branch_id_from_imedx(username):
        try:
            with connections['imedx'].cursor() as cursor:
                cursor.execute("""
                    SELECT bsp.base_site_branch_id
                    FROM employee emp 
                    LEFT JOIN base_service_point bsp ON emp.base_service_point_id = bsp.base_service_point_id
                    WHERE emp.employee_id = %s AND emp.active = '1'
                """, [username])
                row = cursor.fetchone()
                if row:
                    return row[0]
        except Exception as e:
            logger.error(f"Error fetching branch_id for {username}: {e}")
        return None

    @staticmethod
    def get_master_fks(item_name_val):
        try:
            master = ebudget_budget_item_master.objects.filter(item_name=item_name_val).first()
            if master:
                return master, master.general_ledger
        except Exception:
            pass
        return None, None

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
