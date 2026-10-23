from django.db import migrations


# (item_name, salary, position_allowance, total_salary) from
# "Data เงินเดือน+ค่าแรง  VET+ NON VET For Budget 2027  By พี่เล็ก.xlsx" (right-hand
# table = NON VET). The left-hand VET table's 13 rows all already matched existing
# master rows by item_name, so this migration only seeds NON VET.
NON_VET_ITEMS = [
    ('ผู้จัดการฝ่าย Pet Care', 33000.0, 6000.0, 39000.0),
    ('รองผู้จัดการ แผนก Pet Shop & Pet Taxi', 29000.0, 3000.0, 32000.0),
    ('รองผู้จัดการ ผู้ป่วยใน', 24000.0, 4000.0, 28000.0),
    ('เจ้าหน้าที่ Front Office Support', 15000.0, 11000.0, 26000.0),
    ('เจ้าหน้าที่ แม่บ้าน Support', 12000.0, 11000.0, 23000.0),
    ('เจ้าหน้าที่ Nurse Supoort', 15000.0, 11000.0, 26000.0),
    ('รองผู้จัดการ แผนก Front Office', 29000.0, 4000.0, 33000.0),
    ('รองผู้จัดการ แผนก Pet Shop Support', 29000.0, 4000.0, 33000.0),
    ('รองผู้จัดการ แผนก Grooming Support', 29000.0, 4000.0, 33000.0),
]


def seed_non_vet_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    # category_id=1 (บุคลากร/Manpower), sub_category_id=2 (NON VET) — matches
    # the ids budget_app/views.py already queries for the NON VET master dropdown.
    existing_names = set(
        ItemMaster.objects.filter(category_id=1, sub_category_id=2).values_list('item_name', flat=True)
    )
    to_create = [
        ItemMaster(
            category_id=1,
            sub_category_id=2,
            item_name=name,
            salary=salary,
            position_allowance=position_allowance,
            total_salary=total_salary,
        )
        for name, salary, position_allowance, total_salary in NON_VET_ITEMS
        if name not in existing_names
    ]
    if to_create:
        ItemMaster.objects.bulk_create(to_create)


def remove_non_vet_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    names = [name for name, _, _, _ in NON_VET_ITEMS]
    ItemMaster.objects.filter(category_id=1, sub_category_id=2, item_name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0018_seed_car_items'),
    ]

    operations = [
        migrations.RunPython(seed_non_vet_items, remove_non_vet_items),
    ]
