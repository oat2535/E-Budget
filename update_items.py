import os
import django
import sys

# Setup django environment
sys.path.append('c:\\E-Budget')
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ebudget.settings")
django.setup()

from master_data.models import ebudget_budget_item_master

data = [
    ("สัตวแพทย์ทั่วไป", 30000.00, 15000.00),
    ("สัตวแพทย์เฉพาะทาง - คลินิกผิวหนัง", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - คลินิกกายภาพ", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - คลินิกช่องปากและฟัน", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - คลินิกแมว", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - คลินิกสัตว์เลี้ยงพิเศษ", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - คลินิกโรคตา", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - คลินิกหัวใจ", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - อัลตราซาวด์", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - ศัลยกรรมและวิสัญญี", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - ศูนย์ระบบประสาทและกระดูกสันหลัง", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - ศูนย์รักษาโรคอายุรกรรม", 45000.00, 22500.00),
    ("สัตวแพทย์เฉพาะทาง - คลินิกเนื้องอกและมะเร็ง", 45000.00, 22500.00),
]

try:
    print("Deleting old data...")
    ebudget_budget_item_master.objects.all().delete()
    print("Old data deleted.")
    
    print("Inserting new data...")
    for item_name, salary, shift_allowance in data:
        ebudget_budget_item_master.objects.create(
            category_id=1,
            sub_category_id=1,
            item_name=item_name,
            salary=salary,
            estimated_shift_allowance=shift_allowance
        )
    print("New data inserted successfully!")
except Exception as e:
    print(f"Error: {e}")
