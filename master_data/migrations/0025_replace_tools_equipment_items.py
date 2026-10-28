from django.db import migrations


# Master list of Tools & Equipment (เครื่องมือเครื่องใช้) items from user specification
# (item_name, purchase_price, general_ledger_code)
# Corporate accounting policy for Tools & Equipment (sub_category_id=7):
# - '61300011' (ค่าเสื่อมราคา - เครื่องมือเครื่องใช้) for purchase_price > 5000
# - '60300002' (ค่าอุปกรณ์สำนักงาน-ของใช้สิ้นเปลือง) for purchase_price <= 5000
TOOLS_EQUIPMENT_ITEMS = [
    ('ตู้เป่าขนสัตว์ ขนาดS 52.5*45*65cm', 27500.0, '61300011'),
    ('ตู้เป่าขนสัตว์ ขนาดM 53*68*84cm', 38500.0, '61300011'),
    ('ตู้เป่าขนสัตว์ ขนาดL 67*106*105cm', 68500.0, '61300011'),
    ('ตู้เป่าขนสัตว์ PD135', 13900.0, '61300011'),
    ('ไดร์เป่าไล่น้ำ 2 มอเตอร์รุ่น M2', 14500.0, '61300011'),
    ('ไดร์รีดน้ำรุ่น MON-16 Valiable', 8500.0, '61300011'),
    ('ไดร์เป่าขนรุ่น Conair-04', 26500.0, '61300011'),
    ('โต๊ะไฮดราลิคไฟฟ้าพร้อมเสาขาสแตนเลสขนาด 122x66x(20-95) cm.', 28500.0, '61300011'),
    ('โต๊ะตัดขนไฮโดรลิคไฟฟ้าขนาด 122x66x20-95 cm.', 24500.0, '61300011'),
    ('โต๊ะเป่าขน Top Plastic ขนาด126*65*75ซม._FT712', 5400.0, '61300011'),
    ('โต๊ะผ่าตัด ขนาด120*60*90 ซม.', 23000.0, '61300011'),
    ('โต๊ะตรวจที่อยู่ใน ward opd ขนาด60*110*90 ซม.', 13000.0, '61300011'),
    ('เครื่องซักผ้า', 23900.0, '61300011'),
    ('เครื่องอบผ้า', 35300.0, '61300011'),
    ('เครื่องพิมพ์ป้าย(Pet shop)', 7000.0, '61300011'),
]

CATEGORY_ID = 2       # Fix Asset / ครุภัณฑ์
SUB_CATEGORY_ID = 7   # Tools & Equipment / เครื่องมือเครื่องใช้


def replace_tools_equipment_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')

    # Delete all existing tools & equipment items EXCEPT 'OTHER'
    ItemMaster.objects.filter(
        sub_category_id=SUB_CATEGORY_ID
    ).exclude(
        item_name__iexact='OTHER'
    ).delete()

    # Ensure 'OTHER' exists for sub_category_id=7
    if not ItemMaster.objects.filter(category_id=CATEGORY_ID, sub_category_id=SUB_CATEGORY_ID, item_name__iexact='OTHER').exists():
        ItemMaster.objects.create(
            category_id=CATEGORY_ID,
            sub_category_id=SUB_CATEGORY_ID,
            item_name='OTHER',
            purchase_price=0.0,
            salary=0.0,
            position_allowance=0.0,
            estimated_shift_allowance=0.0,
            total_salary=0.0,
            general_ledger_code=None,
        )

    # Bulk create the new tools & equipment items
    to_create = [
        ItemMaster(
            category_id=CATEGORY_ID,
            sub_category_id=SUB_CATEGORY_ID,
            item_name=item_name,
            purchase_price=price,
            salary=0.0,
            position_allowance=0.0,
            estimated_shift_allowance=0.0,
            total_salary=0.0,
            general_ledger_code=gl_code,
        )
        for item_name, price, gl_code in TOOLS_EQUIPMENT_ITEMS
    ]
    ItemMaster.objects.bulk_create(to_create)

    # Keep serial sequence in sync in PostgreSQL
    table = ItemMaster._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )


def revert_tools_equipment_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    item_names = [name for name, _, _ in TOOLS_EQUIPMENT_ITEMS]
    ItemMaster.objects.filter(
        category_id=CATEGORY_ID,
        sub_category_id=SUB_CATEGORY_ID,
        item_name__in=item_names,
    ).delete()

    table = ItemMaster._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0024_replace_furniture_items'),
    ]

    operations = [
        migrations.RunPython(replace_tools_equipment_items, revert_tools_equipment_items),
    ]
