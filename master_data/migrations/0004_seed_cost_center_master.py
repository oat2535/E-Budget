from django.db import migrations


COST_CENTER_NAMES = ['PC', 'PH', 'COST CENTER']


def seed_cost_centers(apps, schema_editor):
    CostCenter = apps.get_model('master_data', 'ebudget_cost_center_master')
    for name in COST_CENTER_NAMES:
        CostCenter.objects.get_or_create(cost_center_name=name)


def remove_cost_centers(apps, schema_editor):
    CostCenter = apps.get_model('master_data', 'ebudget_cost_center_master')
    CostCenter.objects.filter(cost_center_name__in=COST_CENTER_NAMES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0003_ebudget_cost_center_master'),
    ]

    operations = [
        migrations.RunPython(seed_cost_centers, remove_cost_centers),
    ]
