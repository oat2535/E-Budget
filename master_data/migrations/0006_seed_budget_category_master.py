from django.db import migrations


GL_CATEGORIES = [
    ('GL01', 'รายได้ '),
    ('GL02', 'ต้นทุนขาย'),
    ('GL03', 'ค่าใช้จ่ายในการขาย'),
    ('GL04', 'ค่าเสื่อมราคา'),
    ('GL05', 'เงินเดือนและสวัสดิการพนักงาน'),
    ('GL06', 'ค่าอบรมสัมมนา'),
    ('GL07', 'ค่าธรรมเนียมวิชาชีพ'),
    ('GL08', 'ค่าธรรมเนียม'),
    ('GL09', 'ค่าวัสดุสิ้นเปลือง'),
    ('GL10', 'ค่าโฆษณา'),
    ('GL11', 'ค่าซ่อมแซมและบำรุงรักษา'),
    ('GL12', 'ค่าสาธารณูปโภค'),
    ('GL13', 'ค่าเช่าและค่าบริการ'),
    ('GL14', 'ค่าใช้จ่ายในการเดินทาง'),
    ('GL15', 'ค่าใช้จ่ายอื่น'),
    ('GL16', 'ภาษีต่างๆ'),
    ('GL17', 'ค่าใช้จ่ายตัดบัญชี'),
    ('GL18', 'ค่าใช้จ่ายระหว่างกัน'),
    ('GL19', 'รายได้'),
    ('GL20', 'ดอกเบี้ย'),
]


def seed_categories(apps, schema_editor):
    Category = apps.get_model('master_data', 'ebudget_budget_category_master')
    for code, name in GL_CATEGORIES:
        Category.objects.update_or_create(category_code=code, defaults={'category_name': name})


def remove_categories(apps, schema_editor):
    Category = apps.get_model('master_data', 'ebudget_budget_category_master')
    Category.objects.filter(category_code__in=[code for code, _ in GL_CATEGORIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0005_cost_center_code_and_reseed'),
    ]

    operations = [
        migrations.RunPython(seed_categories, remove_categories),
    ]
