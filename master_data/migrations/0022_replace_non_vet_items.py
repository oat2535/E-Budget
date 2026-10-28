from django.db import migrations


# Master list of NON VET positions from the updated salary & allowance schedule
# (item_name, salary, position_allowance, total_salary)
NON_VET_ITEMS = [
    ('เจ้าหน้าที่ LAB', 15000.0, 3000.0, 18000.0),
    ('เจ้าหน้าที่ IPD', 15000.0, 3000.0, 18000.0),
    ('เจ้าหน้าที่ OPD', 15000.0, 3000.0, 18000.0),
    ('เจ้าหน้าที่ สนับสนุนและวินิจฉัย', 15000.0, 3000.0, 18000.0),
    ('เจ้าหน้าที่ Front Office', 16000.0, 3000.0, 19000.0),
    ('เจ้าหน้าที่ PA', 17000.0, 3000.0, 20000.0),
    ('เจ้าหน้าที่ เครื่องมือแพทย์', 15000.0, 3000.0, 18000.0),
    ('เจ้าหน้าที่ แม่บ้าน', 12000.0, 1000.0, 13000.0),
    ('เจ้าหน้าที่ รับรถ', 12000.0, 1000.0, 13000.0),
    ('เจ้าหน้าที่ Pet Taxi', 13080.0, 1000.0, 14080.0),
    ('เจ้าหน้าที่ Grooming', 15000.0, 1000.0, 16000.0),
    ('เจ้าหน้าที่ Pet Shop', 15000.0, 3000.0, 18000.0),
    ('ผู้จัดการเขต', 38000.0, 9000.0, 47000.0),
    ('ผู้จัดการฝ่าย Pet Care', 33000.0, 6000.0, 39000.0),
    ('ผู้จัดการสาขา', 33000.0, 6000.0, 39000.0),
    ('หัวหน้าหน่วย แม่บ้าน', 24000.0, 3000.0, 27000.0),
    ('รองผู้จัดการ แผนก Pet Shop & Pet Taxi', 29000.0, 3000.0, 32000.0),
    ('หัวหน้าหน่วย สนับสนุนและวินิจฉัย', 24000.0, 3000.0, 27000.0),
    ('หัวหน้าหน่วย Reception', 24000.0, 3000.0, 27000.0),
    ('หัวหน้าหน่วย Pharmacy', 24000.0, 3000.0, 27000.0),
    ('หัวหน้าหน่วย Pet Shop & Pet Taxi', 24000.0, 3000.0, 27000.0),
    ('หัวหน้าหน่วย PA', 24000.0, 3000.0, 27000.0),
    ('หัวหน้าหน่วย Front Office', 24000.0, 4000.0, 28000.0),
    ('หัวหน้าหน่วย IPD', 24000.0, 3000.0, 27000.0),
    ('รองผู้จัดการ ผู้ป่วยใน', 24000.0, 4000.0, 28000.0),
    ('หัวหน้าหน่วย Pet Shop', 24000.0, 3000.0, 27000.0),
    ('หัวหน้าหน่วย Grooming', 24000.0, 3000.0, 27000.0),
    ('หัวหน้าหน่วย OPD', 24000.0, 3000.0, 27000.0),
    ('หัวหน้าหน่วย Front Office', 24000.0, 3000.0, 27000.0),
    ('เจ้าหน้าที่ Front Office Support', 15000.0, 11000.0, 26000.0),
    ('เจ้าหน้าที่ แม่บ้าน Support', 12000.0, 11000.0, 23000.0),
    ('เจ้าหน้าที่ Nurse Supoort', 15000.0, 11000.0, 26000.0),
    ('รองผู้จัดการ แผนก Front Office', 29000.0, 4000.0, 33000.0),
    ('รองผู้จัดการ แผนก Pet Shop Support', 29000.0, 4000.0, 33000.0),
    ('รองผู้จัดการ แผนก Grooming Support', 29000.0, 4000.0, 33000.0),
    ('หัวหน้าแผนก/หัวหน้าหน่วย', 0.0, 0.0, 0.0),
    ('รองผู้จัดการ', 0.0, 0.0, 0.0),
    ('ผู้จัดการ', 0.0, 0.0, 0.0),
    ('เจ้าหน้าที่', 0.0, 0.0, 0.0),
    ('รองผู้อำนวยการ', 0.0, 0.0, 0.0),
]


def replace_non_vet_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    # Delete existing NON VET items (sub_category_id = 2)
    ItemMaster.objects.filter(sub_category_id=2).delete()

    # Bulk create the new NON VET items
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
    ]
    ItemMaster.objects.bulk_create(to_create)


def revert_non_vet_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    ItemMaster.objects.filter(sub_category_id=2).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0021_seed_gl_actual_template_rows'),
    ]

    operations = [
        migrations.RunPython(replace_non_vet_items, revert_non_vet_items),
    ]
