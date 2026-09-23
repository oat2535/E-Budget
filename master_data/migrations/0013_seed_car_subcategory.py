from django.db import migrations


# Every other budget_item_master lookup (VET/NON VET/Medical/Computer/
# Furniture/Tools & Equipment) hardcodes its category_id/sub_category_id as
# a plain integer literal in budget_app/views.py — there's no FK/constant
# resolving it at runtime, since these rows are otherwise hand-entered via
# Django admin (see master_data/migrations/0009_rename_c03_category_to_budget_plan.py
# for the same pattern). CAR's view code hardcodes sub_category_id=8, so
# this migration pins the new row to that exact id rather than letting
# auto-increment pick one, and only if that id is free.
def seed_car_subcategory(apps, schema_editor):
    SubCategory = apps.get_model('master_data', 'ebudget_budget_sub_category_master')
    existing = SubCategory.objects.filter(id=8).first()
    if existing:
        if existing.sub_category_code != 'SUBC08':
            raise RuntimeError(
                "ebudget_budget_sub_category_master id=8 is already taken by "
                f"'{existing.sub_category_code}' — CAR's hardcoded sub_category_id=8 "
                "(budget_app/views.py) would collide with it. Resolve manually."
            )
        return

    SubCategory.objects.create(id=8, category_id=2, sub_category_code='SUBC08', sub_category_name='รถยนต์')

    # Keep the id sequence ahead of the explicit pk we just inserted, or the
    # next admin-created row collides with it.
    table = SubCategory._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )


def unseed_car_subcategory(apps, schema_editor):
    SubCategory = apps.get_model('master_data', 'ebudget_budget_sub_category_master')
    SubCategory.objects.filter(id=8, sub_category_code='SUBC08').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0012_alter_ebudget_general_ledger_master_depreciation_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_car_subcategory, unseed_car_subcategory),
    ]
