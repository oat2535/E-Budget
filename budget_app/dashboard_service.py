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


def can_view_all_branches_dashboard(request) -> bool:
    """Return True if the authenticated user may select ALL TLPH branches combined."""
    if not request:
        return False
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return False
    info = _resolve_session_or_live_branch_info(request)
    return _has_all_branch_dashboard_access(user, info)


def get_allowed_branches_for_dashboard(request):
    """Return selectable Dashboard branch options filtered strictly to TLPH branches.

    Users in ALL_BRANCH_USERNAMES / superuser / CHRO / CFO / COO receive an explicit
    {'code': 'ALL', 'name': 'ทุกสาขา (TLPH ทั้งหมด)', 'is_all': True} entry at the top
    alongside every individual TLPH branch. District managers, directors, and branch
    managers receive only their own assigned TLPH branches (no 'ALL' option).
    """
    from budget_app.services import BudgetService

    if not can_access_dashboard(request):
        return []

    user = request.user
    session = getattr(request, 'session', None)
    info = session.get('branch_info') if (session is not None and 'branch_info' in session) else None
    if info is None:
        info = BudgetService.get_branch_info_from_imedx(user.username)

    tlph_branches = BudgetService.get_tlph_branches()
    tlph_map = {b['code']: b for b in tlph_branches}
    tlph_order = {b['code']: idx for idx, b in enumerate(tlph_branches)}

    if _has_all_branch_dashboard_access(user, info):
        return [
            {'code': 'ALL', 'name': 'ทุกสาขา (TLPH ทั้งหมด)', 'is_all': True},
            *tlph_branches,
        ]

    raw_codes = list((info or {}).get('branches') or [])
    seen = set()
    clean_codes = []
    for c in raw_codes:
        code = (c or '').strip().upper()
        # Keep only branches belonging to TLPH
        if code and code in tlph_map and code not in seen:
            seen.add(code)
            clean_codes.append(code)

    if not clean_codes:
        return []

    name_map = BudgetService.get_branch_names_from_imedx(clean_codes)
    result = [
        {'code': code, 'name': name_map.get(code) or tlph_map[code]['name']}
        for code in clean_codes
    ]
    result.sort(key=lambda item: (tlph_order.get(item['code'], 999), item['code']))
    return result


def validate_dashboard_branch(request, raw_branch):
    """Validate requested branch parameter according to user's TLPH / ALL role scope.

    - All-branch roles (pattida_y, nattchai_u, kanchana_a, CHRO, CFO, COO) may select
      'ALL' (resolves to all TLPH branch codes) or any single TLPH branch.
    - District managers, directors, and branch managers may select only 1 branch inside
      their assigned TLPH branches (ALL / comma lists / non-TLPH branches rejected).
    Returns (resolved_branch_dict, error_message, http_status).
    """
    allowed = get_allowed_branches_for_dashboard(request)
    if not allowed:
        return None, 'บัญชีของท่านไม่มีสิทธิ์เข้าใช้งาน Dashboard หรือยังไม่ได้ตั้งค่าสาขาในกลุ่ม TLPH', 403

    can_view_all = can_view_all_branches_dashboard(request)
    branch_code = (raw_branch or '').strip().upper()
    if not branch_code:
        msg = 'กรุณาเลือกสาขาที่ต้องการดูข้อมูล' if can_view_all else 'กรุณาเลือกสาขาที่ต้องการดูข้อมูล (ดูได้ครั้งละ 1 สาขาเท่านั้น)'
        return None, msg, 400

    if ',' in branch_code or ';' in branch_code or ' ' in branch_code:
        return None, 'กรุณาเลือกดูรายสาขา หรือเลือก "ทุกสาขา" จากตัวเลือกที่กำหนดเท่านั้น', 400

    allowed_map = {b['code']: b for b in allowed}

    if branch_code == 'ALL':
        if not can_view_all or 'ALL' not in allowed_map:
            return None, 'สิทธิ์ของท่านอนุญาตให้เลือกดูได้ทีละ 1 สาขาเท่านั้น (ไม่รองรับการดูทุกสาขารวม)', 400
        tlph_codes = [b['code'] for b in allowed if b['code'] != 'ALL']
        if not tlph_codes:
            return None, 'ไม่พบรายชื่อสาขาในกลุ่ม TLPH สำหรับแสดงผลรวม', 400
        resolved = dict(allowed_map['ALL'])
        resolved['branch_codes'] = tlph_codes
        return resolved, None, 200

    if branch_code not in allowed_map:
        return None, f'ท่านไม่มีสิทธิ์เข้าดูข้อมูล Dashboard ของสาขา {branch_code}', 403

    resolved = dict(allowed_map[branch_code])
    resolved['is_all'] = False
    resolved['branch_codes'] = [branch_code]
    return resolved, None, 200


# Preserve backwards-compatible symbol name
validate_single_branch = validate_dashboard_branch


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


def _normalize_branch_codes(branch_codes):
    """Normalize a single branch code string or iterable of branch codes into an ordered unique list."""
    if isinstance(branch_codes, str):
        raw = [branch_codes]
    else:
        raw = list(branch_codes or [])
    seen = set()
    codes = []
    for item in raw:
        c = (item or '').strip().upper()
        if c and c not in seen and c != 'ALL':
            seen.add(c)
            codes.append(c)
    return codes


def fetch_gl_actual_template_for_branch(branch_codes, budget_year):
    """Fetch active non-CANCELLED GL Actual Template data for 1 or many TLPH branches.

    Picks at most 1 winning document_no per branch (APPROVED preferred, then latest
    modify_date/create_date/id) and aggregates cleanly across branches without
    double-counting subtotals.
    """
    codes = _normalize_branch_codes(branch_codes)
    if not codes:
        return {'document': None, 'by_code': {}, 'by_row_order': {}}

    tbl = ebudget_gl_actual_template._meta.db_table
    with connection.cursor() as cur:
        cur.execute(
            f"""
            SELECT DISTINCT ON (base_branch_id)
                   base_branch_id, document_no, status, actual_month_count,
                   growth_pct_1, growth_pct_2, growth_pct_3
            FROM {tbl}
            WHERE base_branch_id = ANY(%s)
              AND budget_year = %s
              AND COALESCE(status, '') <> %s
            ORDER BY base_branch_id ASC,
                     CASE WHEN status = %s THEN 0 ELSE 1 END,
                     modify_date DESC NULLS LAST,
                     create_date DESC NULLS LAST,
                     id DESC
            """,
            [codes, budget_year, STATUS_CANCELLED, STATUS_APPROVED],
        )
        headers = cur.fetchall()
        if not headers:
            return {'document': None, 'by_code': {}, 'by_row_order': {}}

        doc_pairs = tuple((h[0], h[1]) for h in headers)
        cur.execute(
            f"""
            SELECT base_branch_id, row_order, code, row_type,
                   COALESCE(actual_value, 0),
                   COALESCE(per_month_value, 0),
                   COALESCE(annualized_value, 0),
                   COALESCE(sales_ratio, 0),
                   COALESCE(growth_rate, 0)
            FROM {tbl}
            WHERE budget_year = %s
              AND COALESCE(status, '') <> %s
              AND (base_branch_id, document_no) IN %s
            ORDER BY row_order ASC, base_branch_id ASC
            """,
            [budget_year, STATUS_CANCELLED, doc_pairs],
        )
        rows = cur.fetchall()

    # Single-document fast path (preserves exact saved sales_ratio / growth_rate)
    if len(headers) == 1:
        _, doc_no, doc_status, actual_months, gp1, gp2, gp3 = headers[0]
        by_code = {}
        by_row_order = {}
        for _, row_order, code, _, act, per_m, ann, sr, gr in rows:
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

    # Multi-branch consolidated path (ALL TLPH)
    agg_by_ord = {}
    branch_fh101_actual = {}
    for br_id, row_order, code, row_type, act, per_m, ann, _, gr in rows:
        if row_order is None:
            continue
        ord_num = int(row_order)
        clean_code = (str(code).strip() if code else '')
        act_d = round2(act)
        per_m_d = round2(per_m)
        ann_d = round2(ann)
        gr_d = round2(gr)

        if clean_code == 'FH101':
            branch_fh101_actual[br_id] = abs(act_d)

        slot = agg_by_ord.get(ord_num)
        if slot is None:
            slot = {
                'code': clean_code,
                'row_type': row_type,
                'actual_value': ZERO,
                'per_month_value': ZERO,
                'annualized_value': ZERO,
                'gr_weighted_num': ZERO,
                'gr_weight_den': ZERO,
                'gr_vals': [],
            }
            agg_by_ord[ord_num] = slot

        slot['actual_value'] += act_d
        slot['per_month_value'] += per_m_d
        slot['annualized_value'] += ann_d
        w = abs(act_d)
        if w > ZERO:
            slot['gr_weighted_num'] += gr_d * w
            slot['gr_weight_den'] += w
        if gr_d != ZERO:
            slot['gr_vals'].append(gr_d)

    # Combined FH101 actual sales for consolidated sales_ratio recomputation
    fh101_total_actual = ZERO
    for slot in agg_by_ord.values():
        if slot['code'] == 'FH101':
            fh101_total_actual = round2(slot['actual_value'])
            break

    by_code = {}
    by_row_order = {}
    for ord_num, slot in agg_by_ord.items():
        act_sum = round2(slot['actual_value'])
        per_m_sum = round2(slot['per_month_value'])
        ann_sum = round2(slot['annualized_value'])

        is_calculated_header = slot['code'] in ('H6', 'H8')
        if fh101_total_actual != ZERO and (slot['row_type'] != 'header' or is_calculated_header):
            sr = round2((act_sum * HUNDRED) / fh101_total_actual)
        else:
            sr = ZERO

        if slot['gr_weight_den'] > ZERO:
            gr = round2(slot['gr_weighted_num'] / slot['gr_weight_den'])
        elif slot['gr_vals']:
            gr = round2(sum(slot['gr_vals'], ZERO) / Decimal(len(slot['gr_vals'])))
        else:
            gr = ZERO

        entry = {
            'actual_value': act_sum,
            'per_month_value': per_m_sum,
            'annualized_value': ann_sum,
            'sales_ratio': sr,
            'growth_rate': gr,
        }
        if slot['code']:
            by_code[slot['code']] = entry
        by_row_order[ord_num] = entry

    # Consolidated doc metadata across participating TLPH branches
    total_w = sum(branch_fh101_actual.values(), ZERO)
    if total_w > ZERO:
        gp1_avg = sum((round2(h[4]) * branch_fh101_actual.get(h[0], ZERO) for h in headers), ZERO) / total_w
        gp2_avg = sum((round2(h[5]) * branch_fh101_actual.get(h[0], ZERO) for h in headers), ZERO) / total_w
        gp3_avg = sum((round2(h[6]) * branch_fh101_actual.get(h[0], ZERO) for h in headers), ZERO) / total_w
    else:
        n_docs = Decimal(len(headers))
        gp1_avg = sum((round2(h[4]) for h in headers), ZERO) / n_docs
        gp2_avg = sum((round2(h[5]) for h in headers), ZERO) / n_docs
        gp3_avg = sum((round2(h[6]) for h in headers), ZERO) / n_docs

    doc_meta = {
        'document_no': f'รวม {len(headers)} สาขา TLPH',
        'status': 'CONSOLIDATED',
        'actual_month_count': max(int(h[3] or 0) for h in headers),
        'growth_pct_1': _to_float2(gp1_avg),
        'growth_pct_2': _to_float2(gp2_avg),
        'growth_pct_3': _to_float2(gp3_avg),
    }
    return {'document': doc_meta, 'by_code': by_code, 'by_row_order': by_row_order}


def _build_monthly_budget_sql_and_params(branch_codes, budget_year):
    """Build parameterized monthly GL aggregation SQL across all 13 budget tables
    for either 1 branch or multiple TLPH branches uniformly."""
    codes = _normalize_branch_codes(branch_codes)
    if len(codes) == 1:
        branch_clause = 'v.base_branch_id = %s'
        branch_param = codes[0]
    else:
        branch_clause = 'v.base_branch_id = ANY(%s)'
        branch_param = codes

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

    def add_leg(gl_expr, amt_expr, from_clause, gl_not_null_expr):
        subqueries.append(
            f"""
            SELECT TRIM({gl_expr}) AS gl_code,
                   md.month AS month_num,
                   {amt_expr} AS amt
            {from_clause}
            WHERE {branch_clause}
              AND v.budget_year = %s
              AND COALESCE(v.status, '') <> %s
              AND {gl_not_null_expr} IS NOT NULL
              AND TRIM({gl_not_null_expr}) <> ''
            """
        )
        params.extend([branch_param, budget_year, STATUS_CANCELLED])

    # 1. Vet Manpower
    add_leg(
        'v.general_ledger_code',
        'COALESCE(md.cost, 0)',
        f'FROM {vet_tbl} v INNER JOIN {md_tbl} md ON md.vet_budget_id = v.id',
        'v.general_ledger_code',
    )
    # 2a/2b. Non-Vet Manpower (salary + position allowance)
    add_leg(
        'v.salary_general_ledger_code',
        'COALESCE(md.salary, 0)',
        f'FROM {nonvet_tbl} v INNER JOIN {md_tbl} md ON md.non_vet_budget_id = v.id',
        'v.salary_general_ledger_code',
    )
    add_leg(
        'v.position_allowance_general_ledger_code',
        'COALESCE(md.position_allowance, 0)',
        f'FROM {nonvet_tbl} v INNER JOIN {md_tbl} md ON md.non_vet_budget_id = v.id',
        'v.position_allowance_general_ledger_code',
    )
    # 3a/3b. Position Adjustment (salary diff + allowance diff)
    add_leg(
        'v.salary_general_ledger_code',
        'COALESCE(md.new_salary, 0) - COALESCE(md.salary, 0)',
        f'FROM {posadj_tbl} v INNER JOIN {md_tbl} md ON md.position_adj_id = v.id',
        'v.salary_general_ledger_code',
    )
    add_leg(
        'v.allowance_general_ledger_code',
        'COALESCE(md.new_allowance, 0) - COALESCE(md.position_allowance, 0)',
        f'FROM {posadj_tbl} v INNER JOIN {md_tbl} md ON md.position_adj_id = v.id',
        'v.allowance_general_ledger_code',
    )
    # 4-10. Seven Fix Asset tables
    for _, fa_model, fk_col in FIX_ASSET_SOURCES:
        fa_tbl = fa_model._meta.db_table
        add_leg(
            'v.general_ledger_code',
            'CASE WHEN COALESCE(gl.depreciation, 0) > 0 THEN COALESCE(md.cumulative_depreciation, 0) ELSE COALESCE(md.cost, 0) END',
            f'FROM {fa_tbl} v INNER JOIN {md_tbl} md ON md.{fk_col} = v.id LEFT JOIN {gl_tbl} gl ON gl.gl_code = v.general_ledger_code',
            'v.general_ledger_code',
        )
    # 11. GL Entry
    add_leg(
        'v.general_ledger_code',
        'CASE WHEN COALESCE(v.depreciation, 0) > 0 THEN COALESCE(md.cumulative_amount, 0) ELSE COALESCE(md.amount, 0) END',
        f'FROM {gle_tbl} v INNER JOIN {gle_md_tbl} md ON md.gl_entry_id = v.id',
        'v.general_ledger_code',
    )
    # 12. Revenue Entry
    add_leg(
        'v.general_ledger_code',
        'CASE WHEN COALESCE(v.depreciation, 0) > 0 THEN COALESCE(md.cumulative_amount, 0) ELSE COALESCE(md.amount, 0) END',
        f'FROM {rev_tbl} v INNER JOIN {rev_md_tbl} md ON md.revenue_entry_id = v.id',
        'v.general_ledger_code',
    )
    # 13. Budget Plan Item
    add_leg(
        'v.general_ledger_code',
        'COALESCE(md.amount, 0)',
        f'FROM {bp_tbl} v INNER JOIN {bp_md_tbl} md ON md.plan_item_id = v.id',
        'v.general_ledger_code',
    )

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


def fetch_branch_budget_by_gl(branch_codes, budget_year):
    """Execute monthly SQL aggregation and return {gl_code: [jan..dec Decimal]}."""
    codes = _normalize_branch_codes(branch_codes)
    if not codes:
        return {}
    sql, params = _build_monthly_budget_sql_and_params(codes, budget_year)
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
    """Assemble full 181-row P&L matrix, KPI cards, and metadata for 1 or ALL TLPH branches.

    All numeric values are rounded strictly to 2 decimal places.
    """
    target_codes = branch_info_dict.get('branch_codes') or [branch_info_dict['code']]
    outline = _get_template_outline()
    actual_bundle = fetch_gl_actual_template_for_branch(target_codes, budget_year)
    budget_by_gl = fetch_branch_budget_by_gl(target_codes, budget_year)

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

