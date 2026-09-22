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
