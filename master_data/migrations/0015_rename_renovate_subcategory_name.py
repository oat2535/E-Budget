from django.db import migrations


# Renovate's sub-category (id=9, seeded by 0014_seed_renovate_subcategory.py)
# was originally named in Thai ('ปรับปรุง') — renamed to English to match the
# "Renovate" menu label it belongs to.
def rename_renovate_subcategory(apps, schema_editor):
    SubCategory = apps.get_model('master_data', 'ebudget_budget_sub_category_master')
    SubCategory.objects.filter(id=9, sub_category_code='SUBC09').update(sub_category_name='Renovate')


def unrename_renovate_subcategory(apps, schema_editor):
    SubCategory = apps.get_model('master_data', 'ebudget_budget_sub_category_master')
    SubCategory.objects.filter(id=9, sub_category_code='SUBC09').update(sub_category_name='ปรับปรุง')


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0014_seed_renovate_subcategory'),
    ]

    operations = [
        migrations.RunPython(rename_renovate_subcategory, unrename_renovate_subcategory),
    ]
