import os
import django
import sys

# Setup django environment
sys.path.append('c:\\E-Budget')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ebudget.settings")
django.setup()

from django.db import connection

try:
    with connection.cursor() as cursor:
        print("Altering create_date...")
        cursor.execute("ALTER TABLE ebudget_vet_manpower ALTER COLUMN create_date TYPE timestamp(0) without time zone;")
        print("Altering modify_date...")
        cursor.execute("ALTER TABLE ebudget_vet_manpower ALTER COLUMN modify_date TYPE timestamp(0) without time zone;")
    print("Successfully altered columns to timestamp(0) without time zone!")
except Exception as e:
    print(f"Error: {e}")
