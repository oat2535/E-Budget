import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ebudget.settings')
django.setup()

from master_data.models import ebudget_budget_item_master

data = """Ultasound	 1,550,000 
Syringe pump	 19,000 
Infusion pump (ให้เลือดได้)	 14,500 
Monitor	 141,000 
Capnostat	 85,000 
Monitor + Capnostat	 180,000 
Refractometer	 11,000 
Slit lamp	 760,000 
Data logger	 10,000 
Data logger	 24,967 
Infusion pump	 13,000 
ไฟผ่าตัด(Mobile)	 140,000 
Monitor	 152,000 
Probe ultrasound	 278,000 
แว่นขยายใส่ผ่าตัด	 52,500 
ไฟติดศีรษะสำหรับผ่าตัด	 45,000 
Stethoscope	 5,000 
Stethoscope	 3,000 
Syringe pump	 19,000 
Telepack	 650,000 
Telecam	 170,000 
Tonovet	 170,000 
กล้องจุลทรรศน์ 3 กระบอกตา	 72,000 
กล้องจุลทรรศน์ 2 ตา	 42,000 
Hand Lens	 12,000 
เครื่อง Laser	 550,000 
DR Xray	 1,400,000 
CT Scan	 1,600,000 
Warm Air	 50,000 
Warm Pad	 15,500 
เครื่องกดนับแยกชนิดเม็ดเลือดขาว	 14,000 
เครื่องขูดหินปูน	 75,000 
เครื่องจี้ไฟฟ้า	 39,000 
เครื่องจี้ไฟฟ้า	 60,000 
Ventilator	 370,000 
เครื่องชั่งน้ำหนัก(Electronic_Honto_02E_300kg_1*1 M)	 16,000 
เครื่องชั่งน้ำหนัก(Electronic_Honto_HAW_15kg_230*290 mm)	 6,000 
เครื่องชั่งน้ำหนัก(Electronic_Honto_02-7E_300kg_60*80 cm)	 16,000 
เครื่องซีล	 13,000 
Ventilator	 350,000 
Suction(ครื่องดูดเสมหะแบบพกพา Yuwell รุ่น 7E-A)	 3,000 
Suction(เครื่องดูดเสมหะไฟฟ้า Suction รุ่น 7A-23B)	 8,000 
Suction(เครื่องดูดเสมหะไฟฟ้า(เครื่องดูดเสมหะไฟฟ้า Suction รุ่น 7A-23B)	 8,000 
Suction(เครื่องดูดเสมหะไฟฟ้า Suction_รุ่น YX930D_SWAF)	 26,000 
EKG	 220,000 
Ultrasound Echocardiography ยี่ห้อ Hitachi Aloka รุ่น Arietta70	 1,550,000 
Ultrasound itachi Aloka รุ่น Arietta65 พร้อมชุด WSR	 2,500,000 
Probe ultrasound	 278,000 
Otoscope	 38,000 
Ligasure	 650,000 
Warm air	 50,000 
Autoclave 24 ลิตร	 65,000 
Autoclave 60 ลิตร	 250,000 
HCT Centrifuge	 37,450 
Pulse Oximeter	 18,000 
ลู่วิ่งน้ำ	 280,000 
Microship reader	 19,000 
เสื้อตะกั่วกันรังสี	 10,000 
แว่นตากันรังสี	 7,000 
โคมไฟผ่าตัดโคมคู่ชนิดแขวนเพดาน	 250,000 
โต๊ะวางเครื่องมือผ่าตัด	 11,500 
โต๊ะผ่าตัดสแตนเลสแบบหน้าเรียบระบบพาวเวอร์ลิฟท์	 65,000 
กล้องจุลทรรศน์ 3 กระบอกตา	 72,000 
กล้องจุลทรรศน์ 2 ตา	 42,000 
Doppler	 62,000 
ตู้ฉุกเฉิน	 11,000 
ตู้ฟักไข่และให้ความอบอุ่นสำหรับลูกสัตว์	 32,000 
ตู้ออกซิเจน พร้อมฐาน 70*120*80 cm	 32,000 
ตู้ออกซิเจน พร้อมฐาน 60*70*60 cm	 20,000 
ถุงมือกันรังสี	 10,000 
ถุงมือกันรังสี	 10,600 
รถเข็นเวชภัณฑ์	 9,000 
รถเข็นฉีดยา	 7,500 
รถเข็นเวชภัณฑ์	 19,000 
รถเข็นสัตว์แบบสองช่อง	 15,000 
รถเข็นสัตว์แบบเตี้ย	 20,000 
รถเข็นสัตว์	 24,000 
ราวแขวนเสื้อ Xray	 12,000 
ไฟส่องตา	 6,500 
ชุด Set ผ่าตัด SML	 40,000 
ชุด Set ผ่าตัด M	 58,500 
ชุด Set ผ่าตัด L	 62,500"""

lines = data.strip().split('\n')
count = 0
for line in lines:
    parts = line.split('\t')
    if len(parts) == 2:
        name = parts[0].strip().replace('"', '')
        price = float(parts[1].replace(',', '').strip())
        
        ebudget_budget_item_master.objects.create(
            category_id=2,
            sub_category_id=4,
            item_name=name,
            purchase_price=price
        )
        count += 1

print(f"Successfully inserted {count} items.")
