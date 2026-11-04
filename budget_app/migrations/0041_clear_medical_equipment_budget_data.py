from django.db import migrations


def clear_medical_equipment_budgets(apps, schema_editor):
    MedEquip = apps.get_model('budget_app', 'ebudget_medical_equipment')
    MonthlyDetail = apps.get_model('budget_app', 'BudgetMonthlyDetail')

    # Delete monthly details for medical equipment
    MonthlyDetail.objects.filter(med_equip__isnull=False).delete()

    # Delete all medical equipment budget documents
    MedEquip.objects.all().delete()

    # Keep serial sequence in sync in PostgreSQL
    table = MedEquip._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), COALESCE((SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "), 1), false)",
            [table],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('budget_app', '0040_ebudget_gl_actual_template_department_id'),
    ]

    operations = [
        migrations.RunPython(clear_medical_equipment_budgets, migrations.RunPython.noop),
    ]

