import sys
import hashlib
from django.db import connections

def test():
    try:
        with connections['default'].cursor() as cursor:
            print("Connected to default DB")
            cursor.execute("SET search_path TO public")
            
            username = 'nattchai_u'
            password = '1234'
            
            cursor.execute("SELECT employee_id, password FROM employee WHERE employee_id = %s", [username])
            row = cursor.fetchone()
            print(f"Row: {row}")
            if row:
                emp_id, db_password = row
                encoded_password = hashlib.md5(password.encode('utf-8')).hexdigest()
                print(f"Encoded: {encoded_password}")
                print(f"DB Pass: {db_password}")
                print(f"Match: {encoded_password == db_password}")
            else:
                print("No user found")
    except Exception as e:
        print(f"Error: {e}")

test()
