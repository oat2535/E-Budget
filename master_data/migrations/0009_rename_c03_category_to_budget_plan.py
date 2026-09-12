from django.db import migrations


OLD_NAME = 'Category 3'
NEW_NAME = 'Budget Plan'


def rename_forward(apps, schema_editor):
    Category = apps.get_model('master_data', 'ebudget_budget_category_master')
    Category.objects.filter(category_code='C03').update(category_name=NEW_NAME)


def rename_backward(apps, schema_editor):
    Category = apps.get_model('master_data', 'ebudget_budget_category_master')
    Category.objects.filter(category_code='C03').update(category_name=OLD_NAME)


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0008_seed_general_ledger_master'),
    ]

    operations = [
        migrations.RunPython(rename_forward, rename_backward),
    ]
