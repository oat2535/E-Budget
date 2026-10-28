from django.db import migrations


FIX_ASSET_CATEGORY_ID = 2
FIX_ASSET_SUBCATEGORY_IDS = [4, 5, 6, 7, 8, 9, 10]


def add_other_to_fix_assets(apps, schema_editor):
    SubCategory = apps.get_model('master_data', 'ebudget_budget_sub_category_master')
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')

    # Query all subcategories under category_id=2 (Fix Asset / ครุภัณฑ์ / สินทรัพย์ถาวร)
    subcat_ids = set(
        SubCategory.objects.filter(category_id=FIX_ASSET_CATEGORY_ID).values_list('id', flat=True)
    )
    # Ensure all standard Fix Asset subcategories (4: Med, 5: Comp, 6: Furn, 7: Tools, 8: CAR, 9: Renovate, 10: Software) are present
    subcat_ids.update(FIX_ASSET_SUBCATEGORY_IDS)

    # Check for existing 'OTHER' item in category 2 per subcategory
    existing_other_subcats = set(
        ItemMaster.objects.filter(
            category_id=FIX_ASSET_CATEGORY_ID,
            item_name__iexact='OTHER'
        ).values_list('sub_category_id', flat=True)
    )

    to_create = []
    for subcat_id in sorted(subcat_ids):
        if subcat_id not in existing_other_subcats:
            to_create.append(
                ItemMaster(
                    category_id=FIX_ASSET_CATEGORY_ID,
                    sub_category_id=subcat_id,
                    item_name='OTHER',
                    purchase_price=0.0,
                    salary=0.0,
                    position_allowance=0.0,
                    estimated_shift_allowance=0.0,
                    total_salary=0.0,
                    general_ledger_code=None,
                )
            )

    if to_create:
        ItemMaster.objects.bulk_create(to_create)

    # Keep serial sequence in sync in PostgreSQL
    table = ItemMaster._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )


def remove_other_from_fix_assets(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    ItemMaster.objects.filter(category_id=FIX_ASSET_CATEGORY_ID, item_name='OTHER').delete()

    table = ItemMaster._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0022_replace_non_vet_items'),
    ]

    operations = [
        migrations.RunPython(add_other_to_fix_assets, remove_other_from_fix_assets),
    ]
