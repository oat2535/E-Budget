import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ebudget.settings')
django.setup()

from master_data.models import ebudget_budget_item_master

data_exact = [
    ("Note Book DELL Latitude3520 i5(สำหรับจุดบริการ)", 31500),
    ("Note Book DELL Latitude3520 i5(สำหรับ back)", 30500),
    ("Computer PC/All in One+E2422H Monitor  (FRONT+NURSE+PHA+PETSHOP)", 29000),
    ('Computer PC + E2422H Monitor "(EXAM+LAB+WARD)', 28000),
    ("เครื่องพิมพ์ฉลากยา", 9650),
    ("เครื่องพริ้น RICOH SP 3710 DN [A4,A5] (ทั่วไป)-เช่า", 12940),
    ("เครื่องพริ้น RICOH MP 305 (Front)-เช่า", 18000),
    ("เครื่องสำรองไฟ(UPS) for Server/Client", 4000),
    ("เครื่องสำรองไฟ(UPS) for Server/Client", 12000),
    ("เครื่องสแกนบำร์โค้ด(Barcode Scanner)", 3200),
    ("เครื่องอ่ำนบัตรประชำชน(Smart Card", 990),
    ("Digital Signage", 30000),
    ("Telephony IP Phone", 7250),
    ("ระบบบันทึก CCTV ข้อมูลอย่างต่า 30 วัน", 12000),
    ("กล้อง CCTV ภายในอาคาร 360อาศา", 3300),
    ("กล้อง CCTV ภายนอกอาคาร", 1250),
    ("Finger Scan ZKTECO", 5500),
    ("Note Book DELL Latitude3530 i7(สำหรับฝ่ายบริหาร)", 33500),
]

count = 0
for name, price in data_exact:
    obj, created = ebudget_budget_item_master.objects.get_or_create(
        category_id=2,
        sub_category_id=5,
        item_name=name.strip(),
        purchase_price=price,
        defaults={'salary': 0, 'estimated_shift_allowance': 0, 'position_allowance': 0, 'total_salary': 0}
    )
    if created:
        count += 1

print(f"Successfully imported {count} items.")
