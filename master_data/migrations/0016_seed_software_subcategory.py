from django.db import migrations


# Same pattern as 0013_seed_car_subcategory.py / 0014_seed_renovate_subcategory.py
# — Software's view code hardcodes sub_category_id=10, so this migration
# pins the new row to that exact id rather than letting auto-increment pick
# one, and only if that id is free. Named in English from the start (no
# Thai translation), unlike Renovate which needed a follow-up rename.
def seed_software_subcategory(apps, schema_editor):
    SubCategory = apps.get_model('master_data', 'ebudget_budget_sub_category_master')
    existing = SubCategory.objects.filter(id=10).first()
    if existing:
        if existing.sub_category_code != 'SUBC10':
            raise RuntimeError(
                "ebudget_budget_sub_category_master id=10 is already taken by "
                f"'{existing.sub_category_code}' — Software's hardcoded sub_category_id=10 "
                "(budget_app/views.py) would collide with it. Resolve manually."
            )
        return

    SubCategory.objects.create(id=10, category_id=2, sub_category_code='SUBC10', sub_category_name='Software')

    # Keep the id sequence ahead of the explicit pk we just inserted, or the
    # next admin-created row collides with it.
    table = SubCategory._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )


def unseed_software_subcategory(apps, schema_editor):
    SubCategory = apps.get_model('master_data', 'ebudget_budget_sub_category_master')
    SubCategory.objects.filter(id=10, sub_category_code='SUBC10').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0015_rename_renovate_subcategory_name'),
    ]

    operations = [
        migrations.RunPython(seed_software_subcategory, unseed_software_subcategory),
    ]
