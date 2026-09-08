import os
import django
import sys
import pandas as pd

sys.path.append('c:\\E-Budget')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ebudget.settings")
django.setup()

from master_data.models import ebudget_budget_item_master

df = pd.read_excel('c:\\E-Budget\\itemNONVET.xlsx')

count = 0
for index, row in df.iterrows():
    item_name = str(row.iloc[0]).strip()
    if pd.isna(row.iloc[0]) or item_name == 'nan' or not item_name:
        continue
        
    salary = row.iloc[1]
    position_allowance = row.iloc[2]
    total_salary = row.iloc[3]
    
    if pd.isna(salary) or salary == '-':
        salary = 0
    if pd.isna(position_allowance) or position_allowance == '-':
        position_allowance = 0
    if pd.isna(total_salary) or total_salary == '-':
        total_salary = 0
        
    salary = float(salary)
    position_allowance = float(position_allowance)
    total_salary = float(total_salary)
    
    obj, created = ebudget_budget_item_master.objects.update_or_create(
        item_name=item_name,
        category_id=1,
        sub_category_id=2,
        defaults={
            'salary': salary,
            'position_allowance': position_allowance,
            'total_salary': total_salary,
        }
    )
    count += 1

print(f"Successfully processed {count} records.")
