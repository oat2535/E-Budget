# The old singleton pattern (0018) created SystemSettings via
# get_or_create(pk=1) — an explicit PK insert that bypasses the id column's
# sequence, so Postgres's sequence counter never advanced past its initial
# value. The new append-only writes (views.py's toggle_freeze_view /
# set_active_year_view) let the DB assign the id via that same sequence,
# which collides with the existing pk=1 row on the very first real insert.
# Resyncs the sequence to the table's actual max(id) — the standard,
# idempotent fix for a sequence that fell behind manually-inserted rows.

from django.db import migrations


def fix_sequence(apps, schema_editor):
    if schema_editor.connection.vendor != 'postgresql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("""
            SELECT setval(
                pg_get_serial_sequence('ebudget_system_settings', 'id'),
                COALESCE((SELECT MAX(id) FROM ebudget_system_settings), 1)
            )
        """)


class Migration(migrations.Migration):

    dependencies = [
        ('budget_app', '0019_alter_systemsettings_is_frozen'),
    ]

    operations = [
        migrations.RunPython(fix_sequence, migrations.RunPython.noop),
    ]
