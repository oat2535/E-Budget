from django.db import migrations


# (item_name, purchase_price) from "Data Car For Budget 2027.xlsx"
CAR_ITEMS = [
    ('MITSUBICHI-XPENDER GT HEV เครื่อง 1.6 cc.', 914000.0),
    ('SUZUKI ERTIGA HYBRID GL', 783000.0),
    ('CHERY 2WD V23 PLUS', 719900.0),
    ('TOYOTA-REVO SMART CAB Z EDITION 2.4 ENTRY AT', 682000.0),
    ('TOYOTA-HILUX CHAMP B-2.4 DIESAL AT', 582000.0),
    ('TOYOTA-REVO ช่วงยาว ไม่มีกระบะ รุ่นB-2.4 ENTRY C&C AT', 597000.0),
]


def seed_car_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    # category_id=2 (สินทรัพย์ถาวร / Fix Asset), sub_category_id=8 (รถยนต์
    # / CAR) — matches the fixed ids every other equipment sub-category
    # migration in this app pins its RunPython against.
    existing_names = set(
        ItemMaster.objects.filter(category_id=2, sub_category_id=8).values_list('item_name', flat=True)
    )
    to_create = [
        ItemMaster(category_id=2, sub_category_id=8, item_name=name, purchase_price=price)
        for name, price in CAR_ITEMS
        if name not in existing_names
    ]
    if to_create:
        ItemMaster.objects.bulk_create(to_create)


def remove_car_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    names = [name for name, _ in CAR_ITEMS]
    ItemMaster.objects.filter(category_id=2, sub_category_id=8, item_name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0017_seed_medical_equipment_items'),
    ]

    operations = [
        migrations.RunPython(seed_car_items, remove_car_items),
    ]
