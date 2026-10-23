# Usernames allowed to view/edit budget documents across every branch,
# freeze the system, and change the active budget year — the one and only
# permission tier that exists in this app today (no Django Groups/is_staff
# in use anywhere). Lives here (not in views.py) so both views.py and
# context_processors.py can import it without a backwards views->context
# import.
ALL_BRANCH_USERNAMES = {'nattchai_u', 'kanchana_a', 'pattida_y'}

DEFAULT_FROZEN_MESSAGE = (
    "ระบบอยู่ระหว่างปิดงบประมาณชั่วคราว ไม่สามารถเพิ่มหรือแก้ไขข้อมูลได้ในขณะนี้ "
    "หากมีข้อสงสัยกรุณาติดต่อฝ่ายบัญชี"
)

# Document approval workflow. Lives here for the same reason
# ALL_BRANCH_USERNAMES does — models.py and views.py both need it without a
# circular import.
STATUS_PENDING = 'PENDING'
STATUS_APPROVED = 'APPROVED'
STATUS_CANCELLED = 'CANCELLED'

DOCUMENT_STATUS_CHOICES = [
    (STATUS_PENDING, 'รออนุมัติ'),
    (STATUS_APPROVED, 'อนุมัติแล้ว'),
    (STATUS_CANCELLED, 'ยกเลิก'),
]

# GL codes hidden from the dropdown on the "EXPENSE" (formerly "GL Entry")
# add-budget page specifically — requested removal list. The underlying
# ebudget_general_ledger_master rows stay untouched/active: existing
# documents that already reference one of these codes (e.g. GLE-202609-004
# -> 61300005) keep resolving their name/proportion/depreciation normally.
# This only narrows what's offered when picking a GL for a *new* line on
# that one page — Budget Plan's own GL dropdown is intentionally unaffected.
EXPENSE_PAGE_EXCLUDED_GL_CODES = {
    '61300006', '61300009', '61300002', '61300004', '61300005', '61300008',
    '61300011', '61300012', '61300013', '61300007', '61300010',
    '61100003', '61100007',
    '41100001', '41200001', '41100002', '41200004', '41200002', '41200003',
    '42000001', '42000019', '42000005',
    # Added in a follow-up round: ค่าเสื่อมราคา-สินทรัพย์สิทธิการใช้ (right-of-use
    # asset depreciation) and its -IP variants.
    '61300014', '61300016', '61300015',
}

# GL code stamped onto a VET Manpower line item when the entered ตำแหน่ง
# (position) isn't found in ebudget_budget_item_master — covers a custom/
# one-off position typed in free-hand via the dropdown's autocomplete,
# which would otherwise resolve to no GL code at all (see
# BudgetService.get_master_fks_bulk — a miss returns (None, None)).
# Already a real, active row in ebudget_general_ledger_master
# ("ค่าบริการวิชาชีพแพทย์", master_data/migrations/0008_seed_general_ledger_master.py)
# — no master-data change needed to use it as a fallback.
VET_CUSTOM_POSITION_GL_CODE = '52000008'

# GL codes for NON VET Manpower line items — fixed by accounting policy,
# not resolved per-position like VET's does: salary and the grade/position
# allowance (ค่าวัดระดับ/ตำแหน่ง) are always two separate expense categories,
# so every NON VET line stamps both codes regardless of which position was
# picked (or whether it's even in master data at all). Both already exist
# as real, active rows in ebudget_general_ledger_master — seeded in
# master_data/migrations/0008_seed_general_ledger_master.py with names that
# match exactly ("เงินเดือน" / "ค่าวัดระดับ/ค่าตำแหน่ง").
NON_VET_SALARY_GL_CODE = '60100001'
NON_VET_ALLOWANCE_GL_CODE = '60100002'

# GL codes for Medical Equipment line items — chosen by the document's
# actual entered purchase_price (a capitalization-threshold policy), not
# looked up from master data (which has no GL column for this category).
# Both are real, active rows in ebudget_general_ledger_master.
MEDICAL_EQUIPMENT_GL_CODE_HIGH = '61300010'  # ค่าเสื่อมราคา - เครื่องมือแพทย์ (purchase_price > 5000)
MEDICAL_EQUIPMENT_GL_CODE_LOW = '60300002'   # ค่าอุปกรณ์สำนักงาน-ของใช้สิ้นเปลือง (purchase_price < 5000)
MEDICAL_EQUIPMENT_GL_PRICE_THRESHOLD = 5000

# Same purchase_price capitalization-threshold policy as Medical Equipment
# (see resolve_price_threshold_gl_code), applied to Computer Equipment with
# its own GL codes. The low-value code happens to match Medical Equipment's
# today, but is kept as its own constant since the two categories' policies
# are independent and may diverge later.
COMPUTER_EQUIPMENT_GL_CODE_HIGH = '61300004'  # ค่าเสื่อมราคา - คอมพิวเตอร์ (purchase_price > 5000)
COMPUTER_EQUIPMENT_GL_CODE_LOW = '60300002'   # ค่าอุปกรณ์สำนักงาน-ของใช้สิ้นเปลือง (purchase_price < 5000)
COMPUTER_EQUIPMENT_GL_PRICE_THRESHOLD = 5000

# Same purchase_price capitalization-threshold policy, applied to Furniture
# with its own GL codes.
FURNITURE_GL_CODE_HIGH = '61300012'  # ค่าเสื่อมราคา - เฟอร์นิเจอร์ & เครื่องใช้สำนักงาน (purchase_price > 5000)
FURNITURE_GL_CODE_LOW = '60600003'   # ค่าซ่อมแซมเครื่องตกแต่งและติดตั้ง (purchase_price < 5000)
FURNITURE_GL_PRICE_THRESHOLD = 5000

# Same purchase_price capitalization-threshold policy, applied to Tools &
# Equipment with its own GL codes.
TOOLS_EQUIPMENT_GL_CODE_HIGH = '61300011'  # ค่าเสื่อมราคา - เครื่องมือเครื่องใช้ (purchase_price > 5000)
TOOLS_EQUIPMENT_GL_CODE_LOW = '60300002'   # ค่าอุปกรณ์สำนักงาน-ของใช้สิ้นเปลือง (purchase_price < 5000)
TOOLS_EQUIPMENT_GL_PRICE_THRESHOLD = 5000

# The 22-branch picker for the "GL Actual Template" page specifically. Every
# other add-budget page resolves the CURRENT USER's own branch live from
# imedx (BudgetService.get_branch_info_from_imedx) — there is no canonical
# all-branches list anywhere else in this codebase. This page is different
# by design: it's a branch-level summary template the user can fill in for
# ANY branch, not just their own, so it needs the full static list.
GL_ACTUAL_TEMPLATE_BRANCHES = [
    ('AP', 'สาขาอโศกประสานมิตร'),
    ('CA', 'สาขาเชียงใหม่แอร์พอร์ต'),
    ('CE', 'สาขาเซ็นทรัลอีสต์วิลล์'),
    ('CM', 'สาขาเชียงใหม่'),
    ('EC', 'โรงพยาบาลสัตว์ทองหล่อ Ecommerce'),
    ('PK', 'สาขาปิ่นเกล้า'),
    ('PR', 'สาขาประชาชื่น'),
    ('PY', 'สาขาพัทยา'),
    ('R2', 'สาขาพระราม2'),
    ('R5', 'สาขาพระราม5'),
    ('R6', 'สาขาพระราม6'),
    ('R8', 'สาขารามอินทรา'),
    ('R9', 'สาขาพระราม9'),
    ('RS', 'สาขารังสิต'),
    ('RY', 'สาขาระยอง'),
    ('SN', 'สาขาสาทรนราธิวาส'),
    ('SR', 'สาขาศรีนครินทร์'),
    ('SV', 'สาขาสุขุมวิท'),
    ('TN', 'สาขาติวานนท์'),
    ('TP', 'ทองหล่อฉลองภูเก็ต'),
    ('PM', 'สาขาประดิษฐ์มนูธรรม'),
    ('HO', 'สำนักงานใหญ่'),
]
