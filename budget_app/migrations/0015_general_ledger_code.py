from django.db import migrations, models


MODEL_NAMES = [
    'ebudget_vet_manpower',
    'ebudget_non_vet_manpower',
    'ebudget_position_adjustment',
    'ebudget_medical_equipment',
    'ebudget_computer_equipment',
    'ebudget_furniture',
    'ebudget_tools_equipment',
]


def copy_gl_code_from_fk(apps, schema_editor):
    """Stamp gl_code from the still-present general_ledger FK onto the new
    general_ledger_code column before the FK column is dropped, so existing
    rows don't silently lose their general ledger reference."""
    GLMaster = apps.get_model('master_data', 'ebudget_general_ledger_master')
    gl_codes_by_id = dict(GLMaster.objects.values_list('id', 'gl_code'))

    for model_name in MODEL_NAMES:
        Model = apps.get_model('budget_app', model_name)
        rows = Model.objects.exclude(general_ledger_id__isnull=True)
        for row in rows:
            gl_code = gl_codes_by_id.get(row.general_ledger_id)
            if gl_code:
                row.general_ledger_code = gl_code
                row.save(update_fields=['general_ledger_code'])


class Migration(migrations.Migration):

    dependencies = [
        ('budget_app', '0014_ebudget_computer_equipment_cost_center_name_and_more'),
        ('master_data', '0002_ebudget_budget_item_master_total_salary'),
    ]

    operations = [
        # 1. Add the new plain-string column alongside the still-existing FK.
        migrations.AddField(
            model_name='ebudget_vet_manpower',
            name='general_ledger_code',
            field=models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัส General Ledger"),
        ),
        migrations.AddField(
            model_name='ebudget_non_vet_manpower',
            name='general_ledger_code',
            field=models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัส General Ledger"),
        ),
        migrations.AddField(
            model_name='ebudget_position_adjustment',
            name='general_ledger_code',
            field=models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัส General Ledger"),
        ),
        migrations.AddField(
            model_name='ebudget_medical_equipment',
            name='general_ledger_code',
            field=models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัส General Ledger"),
        ),
        migrations.AddField(
            model_name='ebudget_computer_equipment',
            name='general_ledger_code',
            field=models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัส General Ledger"),
        ),
        migrations.AddField(
            model_name='ebudget_furniture',
            name='general_ledger_code',
            field=models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัส General Ledger"),
        ),
        migrations.AddField(
            model_name='ebudget_tools_equipment',
            name='general_ledger_code',
            field=models.CharField(max_length=50, null=True, blank=True, verbose_name="รหัส General Ledger"),
        ),

        # 2. Backfill general_ledger_code from the FK's gl_code for any existing rows.
        migrations.RunPython(copy_gl_code_from_fk, migrations.RunPython.noop),

        # 3. Drop the old FK column now that its value has been preserved as a string.
        migrations.RemoveField(model_name='ebudget_vet_manpower', name='general_ledger'),
        migrations.RemoveField(model_name='ebudget_non_vet_manpower', name='general_ledger'),
        migrations.RemoveField(model_name='ebudget_position_adjustment', name='general_ledger'),
        migrations.RemoveField(model_name='ebudget_medical_equipment', name='general_ledger'),
        migrations.RemoveField(model_name='ebudget_computer_equipment', name='general_ledger'),
        migrations.RemoveField(model_name='ebudget_furniture', name='general_ledger'),
        migrations.RemoveField(model_name='ebudget_tools_equipment', name='general_ledger'),
    ]
