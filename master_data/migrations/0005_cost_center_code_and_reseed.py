from django.db import migrations, models


NEW_COST_CENTERS = [
    ('0000', 'Center'),
    ('0001', 'PH (Pet Hospital+Pet Taxi)'),
    ('0002', 'PW (Pet Wellness+Pet Shop+GM+Pet Pool)'),
    ('3001', 'แผนกบัญชี'),
    ('3002', 'แผนกบุคคล'),
    ('3003', 'แผนก IT'),
    ('3004', 'แผนกซ่อมบำรุง'),
    ('3005', 'แผนก Admin'),
    ('3006', 'แผนกคุณภาพ'),
    ('3007', 'แผนกจัดซื้อ'),
    ('3008', 'แผนกวางแผนและพัฒนาธุรกิจสัตว์แพทย์'),
    ('3009', 'แผนกการตลาด'),
    ('3010', 'แผนกคลังสินค้า'),
    ('3011', 'แผนกการเงิน'),
    ('3012', 'แผนก Product and Service Development'),
    ('3013', 'แผนก Legal'),
    ('3014', 'แผนก E-Commerce'),
    ('3015', 'แผนก Branded Product'),
    ('3016', 'แผนก Business Development'),
    ('3017', 'แผนกกลยุทธ์'),
    ('3018', 'แผนก Sale and Area'),
    ('3019', 'แผนกบริหารสัตวแพทย์คลีนิคพิเศษ'),
    ('3020', 'แผนก บริหาร BU'),
    ('3021', 'Internal Audit'),
    ('3022', 'แผนก Business Intelligence'),
    ('3023', 'แผนก เครื่องมือแพทย์'),
    ('3024', 'Project DCXGP'),
]

PREVIOUS_COST_CENTER_NAMES = ['PC', 'PH', 'COST CENTER']


def replace_cost_centers(apps, schema_editor):
    """Existing budget rows reference cost_center_name as a plain string
    (not a FK — see budget_app models), so clearing this master table can't
    cascade-delete or corrupt any historical budget data. The UI already
    falls back gracefully for a document whose stored value no longer
    matches any master row (see populateCostCenterSelect in budget_list.js),
    so a full replace here is safe."""
    CostCenter = apps.get_model('master_data', 'ebudget_cost_center_master')
    CostCenter.objects.all().delete()
    for code, name in NEW_COST_CENTERS:
        CostCenter.objects.create(cost_center_code=code, cost_center_name=name)


def restore_previous_cost_centers(apps, schema_editor):
    CostCenter = apps.get_model('master_data', 'ebudget_cost_center_master')
    CostCenter.objects.all().delete()
    for name in PREVIOUS_COST_CENTER_NAMES:
        CostCenter.objects.create(cost_center_name=name)


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0004_seed_cost_center_master'),
    ]

    operations = [
        migrations.AddField(
            model_name='ebudget_cost_center_master',
            name='cost_center_code',
            field=models.CharField(max_length=10, null=True, blank=True, unique=True, verbose_name='รหัส Cost Center'),
        ),
        migrations.RunPython(replace_cost_centers, restore_previous_cost_centers),
        migrations.AlterField(
            model_name='ebudget_cost_center_master',
            name='cost_center_code',
            field=models.CharField(max_length=10, unique=True, verbose_name='รหัส Cost Center'),
        ),
    ]
