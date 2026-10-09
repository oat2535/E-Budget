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
