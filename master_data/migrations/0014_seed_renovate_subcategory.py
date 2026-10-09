from django.db import migrations


# Same pattern as 0013_seed_car_subcategory.py — Renovate's view code
# hardcodes sub_category_id=9, so this migration pins the new row to that
# exact id rather than letting auto-increment pick one, and only if that id
# is free.
def seed_renovate_subcategory(apps, schema_editor):
    SubCategory = apps.get_model('master_data', 'ebudget_budget_sub_category_master')
    existing = SubCategory.objects.filter(id=9).first()
    if existing:
        if existing.sub_category_code != 'SUBC09':
            raise RuntimeError(
                "ebudget_budget_sub_category_master id=9 is already taken by "
                f"'{existing.sub_category_code}' — Renovate's hardcoded sub_category_id=9 "
                "(budget_app/views.py) would collide with it. Resolve manually."
            )
        return

    SubCategory.objects.create(id=9, category_id=2, sub_category_code='SUBC09', sub_category_name='ปรับปรุง')

    # Keep the id sequence ahead of the explicit pk we just inserted, or the
    # next admin-created row collides with it.
    table = SubCategory._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )


def unseed_renovate_subcategory(apps, schema_editor):
    SubCategory = apps.get_model('master_data', 'ebudget_budget_sub_category_master')
    SubCategory.objects.filter(id=9, sub_category_code='SUBC09').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0013_seed_car_subcategory'),
    ]

    operations = [
        migrations.RunPython(seed_renovate_subcategory, unseed_renovate_subcategory),
    ]
