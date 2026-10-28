from django.db import migrations


# Master list of Furniture (เฟอร์นิเจอร์) items from user specification
# (item_name, purchase_price, general_ledger_code)
# GL codes follow corporate policy:
# - '61300012' (สินทรัพย์ - เฟอร์นิเจอร์ & เครื่องใช้สำนักงาน) for purchase_price > 5000
# - '60600003' (ค่าซ่อมแซมเครื่องตกแต่งและติดตั้ง / ค่าซื้อของใช้ติดเคาน์เตอร์) for purchase_price <= 5000
FURNITURE_ITEMS = [
    ('เก้าอี้บาร์กลม', 2700.0, '60600003'),
    ('เก้าอี้พนักงาน', 2500.0, '60600003'),
    ('ทีวี 55"', 12000.0, '61300012'),
    ('ทีวี 43"', 8600.0, '61300012'),
    ('ทีวี 32"', 5600.0, '61300012'),
    ('เครื่องปรับอากาศ 34000 BTU', 58000.0, '61300012'),
    ('เครื่องปรับอากาศ 36100 BTU', 77500.0, '61300012'),
    ('ตู้แช่ยา 2 ชั้น ฟรีซล่าง', 22000.0, '61300012'),
    ('ตู้แช่แข็งใส่ร่าง 13.4 Q', 13700.0, '61300012'),
    ('ตู้แช่เย็น 10.8 Q', 10200.0, '61300012'),
    ('ตู้แช่เย็น 8.9 Q', 8600.0, '61300012'),
    ('ตู้แช่เย็น 6.4 Q', 6400.0, '61300012'),
]

CATEGORY_ID = 2       # Fix Asset / ครุภัณฑ์
SUB_CATEGORY_ID = 6   # Furniture / เฟอร์นิเจอร์


def replace_furniture_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')

    # Delete all existing furniture items EXCEPT 'OTHER'
    ItemMaster.objects.filter(
        sub_category_id=SUB_CATEGORY_ID
    ).exclude(
        item_name__iexact='OTHER'
    ).delete()

    # Ensure 'OTHER' exists for sub_category_id=6
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

    # Bulk create the new furniture items
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
        for item_name, price, gl_code in FURNITURE_ITEMS
    ]
    ItemMaster.objects.bulk_create(to_create)

    # Keep serial sequence in sync in PostgreSQL
    table = ItemMaster._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )


def revert_furniture_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    item_names = [name for name, _, _ in FURNITURE_ITEMS]
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
        ('master_data', '0023_add_other_to_fix_assets'),
    ]

    operations = [
        migrations.RunPython(replace_furniture_items, revert_furniture_items),
    ]
