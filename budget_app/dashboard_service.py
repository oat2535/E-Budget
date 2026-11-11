from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache

from django.db import connection

from budget_app.constants import (
    ALL_BRANCH_USERNAMES,
    STATUS_APPROVED,
    STATUS_CANCELLED,
)
from budget_app.models import (
    BudgetMonthlyDetail,
    SystemSettings,
    ebudget_budget_plan_item,
    ebudget_budget_plan_monthly_detail,
    ebudget_car,
    ebudget_computer_equipment,
    ebudget_furniture,
    ebudget_gl_actual_template,
    ebudget_gl_entry,
    ebudget_gl_entry_monthly_detail,
    ebudget_medical_equipment,
    ebudget_non_vet_manpower,
    ebudget_position_adjustment,
    ebudget_renovate,
    ebudget_revenue,
    ebudget_revenue_monthly_detail,
    ebudget_software,
    ebudget_tools_equipment,
    ebudget_vet_manpower,
)
from master_data.models import (
    ebudget_general_ledger_master,
    ebudget_gl_actual_template_row,
)

TWO_DP = Decimal('0.01')
ZERO = Decimal('0.00')
HUNDRED = Decimal('100.00')

MONTH_KEYS = (
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december',
)
PCT_KEYS = (
    'pct_jan', 'pct_feb', 'pct_mar', 'pct_apr', 'pct_may', 'pct_jun',
    'pct_jul', 'pct_aug', 'pct_sep', 'pct_oct', 'pct_nov', 'pct_dec',
)
ACTUAL_FIELD_KEYS = (
    'actual_value', 'per_month_value', 'annualized_value', 'sales_ratio', 'growth_rate',
)

# Section footer code -> inclusive (start_row_order, end_row_order) of GL leaves belonging to it.
# Derived strictly from ebudget_gl_actual_template_row outline (rows 1..181) so headers like H6/H8
# and standalone GL lines (42000005 under H6, 61700001 under H8) never bleed into neighboring sections.
SECTION_LEAF_BLOCKS = (
    ('FH101', 3, 12),
    ('FH201', 16, 18),
    ('FH202', 21, 32),
    ('FH203', 35, 35),
    ('FH301', 40, 57),
    ('FH302', 60, 62),
    ('FH303', 65, 68),
    ('FH304', 71, 73),
    ('FH305', 76, 78),
    ('FH306', 81, 83),
    ('FH307', 86, 92),
    ('FH308', 95, 105),
    ('FH309', 108, 110),
    ('FH310', 113, 115),
    ('FH311', 118, 126),
    ('FH312', 129, 135),
    ('FH313', 138, 140),
    ('FH410', 145, 158),
    ('FH401', 161, 162),
    ('FH5', 166, 167),
    ('FH7', 172, 177),
)

# Standalone GL leaves that sit outside H*..FH* section footers and participate directly in EBT / Net Profit.
STANDALONE_GL_CODES = {'42000005', '61700001'}

# Composite P&L summary codes rendered with emphasized highlighting in the UI and Excel export.
PNL_SUMMARY_CODES = {'FH101', 'FH2', 'FH3', 'FH1-H3', 'SP-B', 'H6', 'H8', 'FH8'}

# Fix Asset parent models using BudgetMonthlyDetail; tuple is (source_tag, ModelClass, fk_column_in_monthly_detail)
FIX_ASSET_SOURCES = (
    ('MED', ebudget_medical_equipment, 'med_equip_id'),
    ('COMP', ebudget_computer_equipment, 'comp_equip_id'),
    ('FURN', ebudget_furniture, 'furniture_equip_id'),
    ('TOOL', ebudget_tools_equipment, 'tools_equip_id'),
    ('CAR', ebudget_car, 'car_equip_id'),
    ('RENO', ebudget_renovate, 'renovate_equip_id'),
    ('SOFT', ebudget_software, 'software_equip_id'),
)

# All transactional budget models contributing to available budget years for a branch
ALL_BUDGET_YEAR_MODELS = (
    ebudget_vet_manpower,
    ebudget_non_vet_manpower,
    ebudget_position_adjustment,
    ebudget_medical_equipment,
    ebudget_computer_equipment,
    ebudget_furniture,
    ebudget_tools_equipment,
    ebudget_car,
    ebudget_renovate,
    ebudget_software,
    ebudget_gl_entry,
    ebudget_revenue,
    ebudget_budget_plan_item,
    ebudget_gl_actual_template,
)


def round2(val) -> Decimal:
    """Round any numeric input strictly to 2 decimal places using HALF_UP."""
    if val is None or val == '':
        return ZERO
    if not isinstance(val, Decimal):
        val = Decimal(str(val))
    return val.quantize(TWO_DP, rounding=ROUND_HALF_UP)


def _to_float2(val) -> float:
    return float(round2(val))


def _resolve_session_or_live_branch_info(request):
    """Return session branch_info dict if cached, avoiding redundant iMedX queries.

    Wait: Do NOT trigger live iMedX queries when request.session already holds
    'branch_info' (this preserves isolated unit tests mocking partial session dicts).
    """
    from budget_app.services import BudgetService

    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return None

    session = getattr(request, 'session', None)
    if session is not None and 'branch_info' in session:
        return session.get('branch_info') or {}

    return BudgetService.get_branch_info_from_imedx(user.username)


def _has_all_branch_dashboard_access(user, branch_info) -> bool:
    username = (getattr(user, 'username', '') or '').strip().lower()
    if getattr(user, 'is_superuser', False) or username in ALL_BRANCH_USERNAMES:
        return True
    if branch_info and branch_info.get('is_executive_view_only'):
        return True
    from budget_app.services import BudgetService
    note = (branch_info or {}).get('bank_account_note')
    return BudgetService.is_executive_role(note)


def can_access_dashboard(request) -> bool:
    """Return True if user is allowed to open the single-branch E-Budget Dashboard.

    Allowed roles per specification:
    - ALL_BRANCH_USERNAMES (pattida_y, nattchai_u, kanchana_a, kanchana) or superuser
    - Executive roles (CHRO, CFO, COO)
    - District roles (DISTRICT MANAGER, DIRECTOR)
    - Branch Managers ('MANAGER' in bank_account_note)
    """
    if not request:
        return False
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return False

    info = _resolve_session_or_live_branch_info(request)
    if _has_all_branch_dashboard_access(user, info):
        return True

    if not info:
        return False

    if info.get('is_district_view_only') or info.get('is_manager'):
        return True

    from budget_app.services import BudgetService
    note = info.get('bank_account_note')
    return BudgetService.is_district_role(note) or BudgetService.is_manager_role(note)


def get_allowed_branches_for_dashboard(request):
    """Return sorted list of {'code': str, 'name': str} branches the user can view (1 at a time)."""
    from budget_app.services import BudgetService

    if not can_access_dashboard(request):
        return []

    user = request.user
    # Always fetch fresh branch info when resolving actual branch list unless mocked cleanly
    session = getattr(request, 'session', None)
    info = session.get('branch_info') if (session is not None and 'branch_info' in session) else None
    if info is None:
        info = BudgetService.get_branch_info_from_imedx(user.username)

    if _has_all_branch_dashboard_access(user, info):
        return BudgetService.get_all_branches()

    raw_codes = list((info or {}).get('branches') or [])
    # Deduplicate preserving uppercase clean codes
    seen = set()
    clean_codes = []
    for c in raw_codes:
        code = (c or '').strip().upper()
        if code and code not in seen:
            seen.add(code)
            clean_codes.append(code)

    if not clean_codes:
        return []

    name_map = BudgetService.get_branch_names_from_imedx(clean_codes)
    # Use master order where available so dropdown stays predictable
    all_order = {b['code']: idx for idx, b in enumerate(BudgetService.get_all_branches())}
    result = [{'code': code, 'name': name_map.get(code, code)} for code in clean_codes]
    result.sort(key=lambda item: (all_order.get(item['code'], 999), item['code']))
    return result


def validate_single_branch(request, raw_branch):
    """Strictly validate that raw_branch is ONE branch code authorized for the user.

    Rejects blank, 'ALL', comma-separated multi-branch values, or unauthorized branches.
    Returns (branch_dict, error_message, http_status).
    """
    allowed = get_allowed_branches_for_dashboard(request)
    if not allowed:
        return None, 'บัญชีของท่านไม่มีสิทธิ์เข้าใช้งาน Dashboard หรือยังไม่ได้ตั้งค่าสาขาในระบบ', 403

    branch_code = (raw_branch or '').strip().upper()
    if not branch_code:
        return None, 'กรุณาเลือกสาขาที่ต้องการดูข้อมูล (ดูได้ครั้งละ 1 สาขาเท่านั้น)', 400

    if branch_code == 'ALL' or ',' in branch_code or ';' in branch_code or ' ' in branch_code:
        return None, 'ระบบอนุญาตให้เลือกดูข้อมูลได้ทีละ 1 สาขาเท่านั้น (ไม่รองรับการดูรวมทุกสาขา)', 400

    allowed_map = {b['code']: b for b in allowed}
    if branch_code not in allowed_map:
        return None, f'ท่านไม่มีสิทธิ์เข้าดูข้อมูล Dashboard ของสาขา {branch_code}', 403

    return allowed_map[branch_code], None, 200


def get_dashboard_budget_years():
    """Return sorted descending list of budget years relevant to the Dashboard."""
    settings_obj = SystemSettings.load()
    years = {int(settings_obj.active_budget_year)}

    # Collect years from transaction tables quickly without scanning details
    table_names = sorted({m._meta.db_table for m in ALL_BUDGET_YEAR_MODELS})
    if table_names:
        union_sql = ' UNION '.join(
            f'SELECT DISTINCT budget_year FROM {tbl} WHERE budget_year IS NOT NULL'
            for tbl in table_names
        )
        with connection.cursor() as cur:
            cur.execute(union_sql)
            for (yr,) in cur.fetchall():
                if yr is not None:
                    years.add(int(yr))

    return sorted(years, reverse=True)


def _get_template_outline():
    """Fetch canonical 181 template rows sorted by row_order."""
    rows = list(
        ebudget_gl_actual_template_row.objects
        .order_by('row_order')
        .values('id', 'row_order', 'code', 'label', 'row_type')
    )
    return rows


def _build_section_block_lookup(outline):
    """Build dynamic or fallback block lookup mapping row_order -> section footer row_order."""
    footer_order_by_code = {
        r['code']: r['row_order']
        for r in outline
        if r['code'] and r['row_type'] == 'subtotal'
    }
    leaf_to_footer = {}
    for footer_code, start_ord, end_ord in SECTION_LEAF_BLOCKS:
        footer_ord = footer_order_by_code.get(footer_code)
        if footer_ord is None:
            continue
        for ord_num in range(start_ord, end_ord + 1):
            leaf_to_footer[ord_num] = footer_ord
    return leaf_to_footer, footer_order_by_code


def fetch_gl_actual_template_for_branch(branch_code, budget_year):
    """Fetch the active non-CANCELLED GL Actual Template rows & metadata for one branch+year.

    Prefers APPROVED document over PENDING, and most recently modified document_no.
    Reads Actual columns directly per template row (preventing double-counting subtotals).
    """
    tbl = ebudget_gl_actual_template._meta.db_table
    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT document_no, status, actual_month_count, growth_pct_1, growth_pct_2, growth_pct_3
            FROM {tbl}
            WHERE base_branch_id = %s
              AND budget_year = %s
              AND COALESCE(status, '') <> %s
            ORDER BY CASE WHEN status = %s THEN 0 ELSE 1 END,
                     modify_date DESC NULLS LAST,
                     create_date DESC NULLS LAST,
                     id DESC
            LIMIT 1
            """,
            [branch_code, budget_year, STATUS_CANCELLED, STATUS_APPROVED],
        )
        header = cur.fetchone()
        if not header:
            return {'document': None, 'by_code': {}, 'by_row_order': {}}

        doc_no, doc_status, actual_months, gp1, gp2, gp3 = header
        cur.execute(
            f"""
            SELECT template_row_id, row_order, code,
                   COALESCE(actual_value, 0),
                   COALESCE(per_month_value, 0),
                   COALESCE(annualized_value, 0),
                   COALESCE(sales_ratio, 0),
                   COALESCE(growth_rate, 0)
            FROM {tbl}
            WHERE base_branch_id = %s
              AND budget_year = %s
              AND document_no = %s
              AND COALESCE(status, '') <> %s
            ORDER BY row_order ASC
            """,
            [branch_code, budget_year, doc_no, STATUS_CANCELLED],
        )
        rows = cur.fetchall()

    by_code = {}
    by_row_order = {}
    for _, row_order, code, act, per_m, ann, sr, gr in rows:
        entry = {
            'actual_value': round2(act),
            'per_month_value': round2(per_m),
            'annualized_value': round2(ann),
            'sales_ratio': round2(sr),
            'growth_rate': round2(gr),
        }
        if code:
            by_code[str(code).strip()] = entry
        if row_order is not None:
            by_row_order[int(row_order)] = entry

    doc_meta = {
        'document_no': doc_no,
        'status': doc_status,
        'actual_month_count': int(actual_months or 0),
        'growth_pct_1': _to_float2(gp1),
        'growth_pct_2': _to_float2(gp2),
        'growth_pct_3': _to_float2(gp3),
    }
    return {'document': doc_meta, 'by_code': by_code, 'by_row_order': by_row_order}


def _build_monthly_budget_sql_and_params(branch_code, budget_year):
    """Build parameterized single-branch monthly GL aggregation SQL across all 13 budget tables."""
    md_tbl = BudgetMonthlyDetail._meta.db_table
    gl_tbl = ebudget_general_ledger_master._meta.db_table
    vet_tbl = ebudget_vet_manpower._meta.db_table
    nonvet_tbl = ebudget_non_vet_manpower._meta.db_table
    posadj_tbl = ebudget_position_adjustment._meta.db_table
    gle_tbl = ebudget_gl_entry._meta.db_table
    gle_md_tbl = ebudget_gl_entry_monthly_detail._meta.db_table
    rev_tbl = ebudget_revenue._meta.db_table
    rev_md_tbl = ebudget_revenue_monthly_detail._meta.db_table
    bp_tbl = ebudget_budget_plan_item._meta.db_table
    bp_md_tbl = ebudget_budget_plan_monthly_detail._meta.db_table

    subqueries = []
    params = []

    # 1. Vet Manpower -> general_ledger_code, md.cost
    subqueries.append(
        f"""
        SELECT TRIM(v.general_ledger_code) AS gl_code,
               md.month AS month_num,
               COALESCE(md.cost, 0) AS amt
        FROM {vet_tbl} v
        INNER JOIN {md_tbl} md ON md.vet_budget_id = v.id
        WHERE v.base_branch_id = %s
          AND v.budget_year = %s
          AND COALESCE(v.status, '') <> %s
          AND v.general_ledger_code IS NOT NULL
          AND TRIM(v.general_ledger_code) <> ''
        """
    )
    params.extend([branch_code, budget_year, STATUS_CANCELLED])

    # 2a. Non-Vet Manpower -> salary_general_ledger_code, md.salary
    subqueries.append(
        f"""
        SELECT TRIM(v.salary_general_ledger_code) AS gl_code,
               md.month AS month_num,
               COALESCE(md.salary, 0) AS amt
        FROM {nonvet_tbl} v
        INNER JOIN {md_tbl} md ON md.non_vet_budget_id = v.id
        WHERE v.base_branch_id = %s
          AND v.budget_year = %s
          AND COALESCE(v.status, '') <> %s
          AND v.salary_general_ledger_code IS NOT NULL
          AND TRIM(v.salary_general_ledger_code) <> ''
        """
    )
    params.extend([branch_code, budget_year, STATUS_CANCELLED])

    # 2b. Non-Vet Manpower -> position_allowance_general_ledger_code, md.position_allowance
    subqueries.append(
        f"""
        SELECT TRIM(v.position_allowance_general_ledger_code) AS gl_code,
               md.month AS month_num,
               COALESCE(md.position_allowance, 0) AS amt
        FROM {nonvet_tbl} v
        INNER JOIN {md_tbl} md ON md.non_vet_budget_id = v.id
        WHERE v.base_branch_id = %s
          AND v.budget_year = %s
          AND COALESCE(v.status, '') <> %s
          AND v.position_allowance_general_ledger_code IS NOT NULL
          AND TRIM(v.position_allowance_general_ledger_code) <> ''
        """
    )
    params.extend([branch_code, budget_year, STATUS_CANCELLED])

    # 3a. Position Adjustment -> salary diff (new_salary - salary)
    subqueries.append(
        f"""
        SELECT TRIM(v.salary_general_ledger_code) AS gl_code,
               md.month AS month_num,
               COALESCE(md.new_salary, 0) - COALESCE(md.salary, 0) AS amt
        FROM {posadj_tbl} v
        INNER JOIN {md_tbl} md ON md.position_adj_id = v.id
        WHERE v.base_branch_id = %s
          AND v.budget_year = %s
          AND COALESCE(v.status, '') <> %s
          AND v.salary_general_ledger_code IS NOT NULL
          AND TRIM(v.salary_general_ledger_code) <> ''
        """
    )
    params.extend([branch_code, budget_year, STATUS_CANCELLED])

    # 3b. Position Adjustment -> position allowance diff (new_allowance - position_allowance)
    subqueries.append(
        f"""
        SELECT TRIM(v.allowance_general_ledger_code) AS gl_code,
               md.month AS month_num,
               COALESCE(md.new_allowance, 0) - COALESCE(md.position_allowance, 0) AS amt
        FROM {posadj_tbl} v
        INNER JOIN {md_tbl} md ON md.position_adj_id = v.id
        WHERE v.base_branch_id = %s
          AND v.budget_year = %s
          AND COALESCE(v.status, '') <> %s
          AND v.allowance_general_ledger_code IS NOT NULL
          AND TRIM(v.allowance_general_ledger_code) <> ''
        """
    )
    params.extend([branch_code, budget_year, STATUS_CANCELLED])

    # 4-10. Seven Fix Asset tables: use precomputed 2dp cumulative_depreciation when GL has depreciation > 0, else md.cost
    for _, fa_model, fk_col in FIX_ASSET_SOURCES:
        fa_tbl = fa_model._meta.db_table
        subqueries.append(
            f"""
            SELECT TRIM(v.general_ledger_code) AS gl_code,
                   md.month AS month_num,
                   CASE
                       WHEN COALESCE(gl.depreciation, 0) > 0 THEN COALESCE(md.cumulative_depreciation, 0)
                       ELSE COALESCE(md.cost, 0)
                   END AS amt
            FROM {fa_tbl} v
            INNER JOIN {md_tbl} md ON md.{fk_col} = v.id
            LEFT JOIN {gl_tbl} gl ON gl.gl_code = v.general_ledger_code
            WHERE v.base_branch_id = %s
              AND v.budget_year = %s
              AND COALESCE(v.status, '') <> %s
              AND v.general_ledger_code IS NOT NULL
              AND TRIM(v.general_ledger_code) <> ''
            """
        )
        params.extend([branch_code, budget_year, STATUS_CANCELLED])

    # 11. GL Entry
    subqueries.append(
        f"""
        SELECT TRIM(v.general_ledger_code) AS gl_code,
               md.month AS month_num,
               CASE
                   WHEN COALESCE(v.depreciation, 0) > 0 THEN COALESCE(md.cumulative_amount, 0)
                   ELSE COALESCE(md.amount, 0)
               END AS amt
        FROM {gle_tbl} v
        INNER JOIN {gle_md_tbl} md ON md.gl_entry_id = v.id
        WHERE v.base_branch_id = %s
          AND v.budget_year = %s
          AND COALESCE(v.status, '') <> %s
          AND v.general_ledger_code IS NOT NULL
          AND TRIM(v.general_ledger_code) <> ''
        """
    )
    params.extend([branch_code, budget_year, STATUS_CANCELLED])

    # 12. Revenue Entry
    subqueries.append(
        f"""
        SELECT TRIM(v.general_ledger_code) AS gl_code,
               md.month AS month_num,
               CASE
                   WHEN COALESCE(v.depreciation, 0) > 0 THEN COALESCE(md.cumulative_amount, 0)
                   ELSE COALESCE(md.amount, 0)
               END AS amt
        FROM {rev_tbl} v
        INNER JOIN {rev_md_tbl} md ON md.revenue_entry_id = v.id
        WHERE v.base_branch_id = %s
          AND v.budget_year = %s
          AND COALESCE(v.status, '') <> %s
          AND v.general_ledger_code IS NOT NULL
          AND TRIM(v.general_ledger_code) <> ''
        """
    )
    params.extend([branch_code, budget_year, STATUS_CANCELLED])

    # 13. Budget Plan Item
    subqueries.append(
        f"""
        SELECT TRIM(v.general_ledger_code) AS gl_code,
               md.month AS month_num,
               COALESCE(md.amount, 0) AS amt
        FROM {bp_tbl} v
        INNER JOIN {bp_md_tbl} md ON md.plan_item_id = v.id
        WHERE v.base_branch_id = %s
          AND v.budget_year = %s
          AND COALESCE(v.status, '') <> %s
          AND v.general_ledger_code IS NOT NULL
          AND TRIM(v.general_ledger_code) <> ''
        """
    )
    params.extend([branch_code, budget_year, STATUS_CANCELLED])

    union_body = '\nUNION ALL\n'.join(subqueries)
    month_pivots = ',\n'.join(
        f"ROUND(SUM(CASE WHEN u.month_num = {m} THEN u.amt ELSE 0 END), 2) AS {MONTH_KEYS[m - 1]}"
        for m in range(1, 13)
    )
    sql = f"""
        SELECT u.gl_code,
               {month_pivots}
        FROM (
            {union_body}
        ) u
        GROUP BY u.gl_code
    """
    return sql, params


def fetch_branch_budget_by_gl(branch_code, budget_year):
    """Execute single-branch SQL aggregation and return {gl_code: [jan..dec Decimal]}."""
    sql, params = _build_monthly_budget_sql_and_params(branch_code, budget_year)
    by_gl = {}
    with connection.cursor() as cur:
        cur.execute(sql, params)
        for row in cur.fetchall():
            gl_code = (row[0] or '').strip()
            if not gl_code:
                continue
            by_gl[gl_code] = [round2(val) for val in row[1:13]]
    return by_gl


def _zero_months():
    return [ZERO] * 12


def _add_months(a, b):
    return [round2(x + y) for x, y in zip(a, b)]


def _sub_months(a, b):
    return [round2(x - y) for x, y in zip(a, b)]


def build_dashboard_data(branch_info_dict, budget_year):
    """Assemble full 181-row P&L matrix, KPI cards, and metadata for one branch+year.

    All numeric values are rounded strictly to 2 decimal places.
    """
    branch_code = branch_info_dict['code']
    outline = _get_template_outline()
    actual_bundle = fetch_gl_actual_template_for_branch(branch_code, budget_year)
    budget_by_gl = fetch_branch_budget_by_gl(branch_code, budget_year)

    leaf_to_footer, _ = _build_section_block_lookup(outline)

    # First pass: build mutable month arrays per row_order for leaves & actual snapshots
    row_months = {}
    row_actuals = {}
    by_code_meta = {}

    for item in outline:
        ord_num = int(item['row_order'])
        code = (item['code'] or '').strip()
        row_type = item['row_type']
        if code:
            by_code_meta[code] = ord_num

        # Actual values from GL Actual Template (prefer code match, fallback row_order match)
        act_src = actual_bundle['by_code'].get(code) or actual_bundle['by_row_order'].get(ord_num)
        if act_src:
            row_actuals[ord_num] = dict(act_src)
        else:
            row_actuals[ord_num] = {k: ZERO for k in ACTUAL_FIELD_KEYS}

        if row_type == 'gl' and code:
            row_months[ord_num] = list(budget_by_gl.get(code, _zero_months()))
        else:
            row_months[ord_num] = _zero_months()

    # Second pass: aggregate GL leaf rows into each section subtotal (FH101, FH201..FH203, FH301..FH313, FH410, FH401, FH5, FH7)
    section_sums = defaultdict(_zero_months)
    for item in outline:
        ord_num = int(item['row_order'])
        if item['row_type'] != 'gl':
            continue
        footer_ord = leaf_to_footer.get(ord_num)
        if footer_ord is not None:
            section_sums[footer_ord] = _add_months(section_sums[footer_ord], row_months[ord_num])

    for footer_ord, months_list in section_sums.items():
        row_months[footer_ord] = months_list

    # Helper to read months safely by template code
    def months_of(code_key):
        ord_num = by_code_meta.get(code_key)
        return row_months[ord_num] if ord_num is not None else _zero_months()

    def set_months(code_key, values):
        ord_num = by_code_meta.get(code_key)
        if ord_num is not None:
            row_months[ord_num] = values

    # Third pass: compute composite P&L subtotals in exact accounting order
    # FH2 = FH201 + FH202 + FH203
    fh2_months = _add_months(_add_months(months_of('FH201'), months_of('FH202')), months_of('FH203'))
    set_months('FH2', fh2_months)

    # FH3 = SUM(FH301 .. FH313)
    fh3_months = _zero_months()
    for idx in range(301, 314):
        fh3_months = _add_months(fh3_months, months_of(f'FH{idx}'))
    set_months('FH3', fh3_months)

    # FH1-H3 (EBITDA) = FH101 - FH2 - FH3
    fh101_months = months_of('FH101')
    ebitda_months = _sub_months(_sub_months(fh101_months, fh2_months), fh3_months)
    set_months('FH1-H3', ebitda_months)

    # SP-B (Profit before Back Office) = FH1-H3 - FH410 - FH401
    sp_b_months = _sub_months(_sub_months(ebitda_months, months_of('FH410')), months_of('FH401'))
    set_months('SP-B', sp_b_months)

    # H6 (EBIT) = SP-B - FH5
    h6_months = _sub_months(sp_b_months, months_of('FH5'))
    set_months('H6', h6_months)

    # H8 (EBT) = H6 + 42000005 (Rental Income) - FH7 (Interest)
    h8_months = _sub_months(_add_months(h6_months, months_of('42000005')), months_of('FH7'))
    set_months('H8', h8_months)

    # FH8 (Net Profit) = H8 - 61700001 (Corporate Income Tax)
    fh8_months = _sub_months(h8_months, months_of('61700001'))
    set_months('FH8', fh8_months)

    # Fourth pass: serialize final 181 rows with 2dp rounding & pct_jan..pct_dec per query formula
    output_rows = []
    for item in outline:
        ord_num = int(item['row_order'])
        code = (item['code'] or '').strip()
        row_type = item['row_type']
        months = row_months[ord_num]
        budget_total = round2(sum(months, ZERO))
        actuals = row_actuals[ord_num]

        # Percentage columns following query_dashboard.txt semantics:
        # - Structural headers (H*): 0.00 (except H6/H8 still treated as header row_type in DB, keep 0.00 to match template)
        # - Subtotal (F*): 100.00 when month value != 0 else 0.00
        # - GL lines in a section block: (month / section_footer_month) * 100, else 0.00
        # - Standalone single-GL lines (42000005, 61700001): 100.00 when month != 0 else 0.00
        pcts = []
        if row_type == 'subtotal':
            for m_val in months:
                pcts.append(HUNDRED if m_val != ZERO else ZERO)
        elif row_type == 'gl':
            footer_ord = leaf_to_footer.get(ord_num)
            if footer_ord is not None:
                denom_months = row_months[footer_ord]
                for m_val, denom in zip(months, denom_months):
                    if denom != ZERO:
                        pcts.append(round2((m_val * HUNDRED) / denom))
                    else:
                        pcts.append(ZERO)
            elif code in STANDALONE_GL_CODES:
                for m_val in months:
                    pcts.append(HUNDRED if m_val != ZERO else ZERO)
            else:
                pcts = [ZERO] * 12
        else:
            pcts = [ZERO] * 12

        is_pnl_summary = code in PNL_SUMMARY_CODES
        ann_val = actuals['annualized_value']
        # Diff = Budget Total - Annualized Actual (x12) where helpful for UI display; Excel strictly exports 33 query cols
        diff_vs_actual = round2(budget_total - ann_val)

        has_nonzero = any(
            v != ZERO for v in (
                actuals['actual_value'],
                actuals['per_month_value'],
                actuals['annualized_value'],
                budget_total,
                *months,
            )
        )

        row_dict = {
            'row_order': ord_num,
            'general_ledger_code': code,
            'gl_name': item['label'] or '',
            'row_type': row_type,
            'is_pnl_summary': is_pnl_summary,
            'has_nonzero': has_nonzero,
            'actual_value': _to_float2(actuals['actual_value']),
            'per_month_value': _to_float2(actuals['per_month_value']),
            'annualized_value': _to_float2(actuals['annualized_value']),
            'sales_ratio': _to_float2(actuals['sales_ratio']),
            'growth_rate': _to_float2(actuals['growth_rate']),
            'total': _to_float2(budget_total),
            'diff_vs_actual': _to_float2(diff_vs_actual),
        }
        for key, m_val in zip(MONTH_KEYS, months):
            row_dict[key] = _to_float2(m_val)
        for key, p_val in zip(PCT_KEYS, pcts):
            row_dict[key] = _to_float2(p_val)

        output_rows.append(row_dict)

    row_by_code = {r['general_ledger_code']: r for r in output_rows if r['general_ledger_code']}

    kpis = _build_kpi_summary(row_by_code)
    return {
        'branch': branch_info_dict,
        'budget_year': int(budget_year),
        'gl_actual_document': actual_bundle['document'],
        'kpis': kpis,
        'rows': output_rows,
    }


def _build_kpi_summary(row_by_code):
    """Build 4 executive KPI summary metrics, all rounded to 2 decimal places."""
    rev_row = row_by_code.get('FH101', {})
    cogs_opex_fh2 = Decimal(str(row_by_code.get('FH2', {}).get('total', 0) or 0))
    cogs_opex_fh3 = Decimal(str(row_by_code.get('FH3', {}).get('total', 0) or 0))
    act_fh2 = Decimal(str(row_by_code.get('FH2', {}).get('annualized_value', 0) or 0))
    act_fh3 = Decimal(str(row_by_code.get('FH3', {}).get('annualized_value', 0) or 0))
    ebitda_row = row_by_code.get('FH1-H3', {})
    net_row = row_by_code.get('FH8', {})

    rev_budget = round2(rev_row.get('total', 0))
    rev_actual_ann = round2(rev_row.get('annualized_value', 0))
    rev_change_pct = round2(((rev_budget - rev_actual_ann) * HUNDRED) / abs(rev_actual_ann)) if rev_actual_ann else ZERO

    total_exp_budget = round2(cogs_opex_fh2 + cogs_opex_fh3)
    total_exp_actual_ann = round2(act_fh2 + act_fh3)
    exp_pct_sales = round2((total_exp_budget * HUNDRED) / rev_budget) if rev_budget else ZERO

    ebitda_budget = round2(ebitda_row.get('total', 0))
    ebitda_actual_ann = round2(ebitda_row.get('annualized_value', 0))
    ebitda_margin = round2((ebitda_budget * HUNDRED) / rev_budget) if rev_budget else ZERO

    net_budget = round2(net_row.get('total', 0))
    net_actual_ann = round2(net_row.get('annualized_value', 0))
    net_margin = round2((net_budget * HUNDRED) / rev_budget) if rev_budget else ZERO

    return {
        'revenue': {
            'budget_total': _to_float2(rev_budget),
            'actual_annualized': _to_float2(rev_actual_ann),
            'change_pct': _to_float2(rev_change_pct),
        },
        'expense': {
            'budget_total': _to_float2(total_exp_budget),
            'actual_annualized': _to_float2(total_exp_actual_ann),
            'pct_of_sales': _to_float2(exp_pct_sales),
        },
        'ebitda': {
            'budget_total': _to_float2(ebitda_budget),
            'actual_annualized': _to_float2(ebitda_actual_ann),
            'margin_pct': _to_float2(ebitda_margin),
        },
        'net_profit': {
            'budget_total': _to_float2(net_budget),
            'actual_annualized': _to_float2(net_actual_ann),
            'margin_pct': _to_float2(net_margin),
        },
    }
