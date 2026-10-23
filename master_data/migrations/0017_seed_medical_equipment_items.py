from django.db import migrations


# (item_name, purchase_price) from "Data เครื่องมือแพทย์ For Budget 2027 By พี่หนึ่ง.xlsx"
# (73 source rows, de-duplicated by item_name within the file itself first — see
# "รถเข็นเวชภัณฑ์", which appeared twice at different prices; only the first kept).
MEDICAL_EQUIPMENT_ITEMS = [
    ('Ultasound(Esaote_เช่าซื้อ)', 2400000.0),
    ('Infusion pump(HK-100)', 15400.0),
    ('Infusion pump (Medcaptain)', 14500.0),
    ('Syringe pump', 19943.93),
    ('Monitor', 160000.0),
    ('Refractometer', 12000.0),
    ('Slit lamp(TOPCON)', 800000.0),
    ('Hand held slit lamp(KEELER)', 250000.0),
    ('Hand held slit lamp(China)', 29000.0),
    ('Wifi thermometer', 4500.0),
    ('ไฟผ่าตัด(ติดเพดาน)', 230000.0),
    ('ไฟผ่าตัด(Mobile)', 152300.0),
    ('Stethoscope', 5000.0),
    ('Tonovet', 178200.0),
    ('กล้องจุลทรรศน์ 3 กระบอกตา', 88000.0),
    ('กล้องจุลทรรศน์ 2 ตา', 50000.0),
    ('Hand Lens', 12500.0),
    ('เครื่อง Laser', 550000.0),
    ('เครื่อง Laser(companion laser)', 890000.0),
    ('DR Xray', 1400000.01),
    ('CT Scan', 2500000.0),
    ('Dental xray', 40000.0),
    ('เครื่องดูดความชื้น', 31780.0),
    ('Warm Air(WARMOLOGY_WMS-1501)', 45000.0),
    ('Warm Air(China)', 15800.0),
    ('Warm Pad', 20000.0),
    ('เครื่องกดนับแยกชนิดเม็ดเลือดขาว', 14500.0),
    ('เครื่องขูดหินปูน', 75000.0),
    ('เครื่องจี้ไฟฟ้า(surtron 160)', 58000.0),
    ('เครื่องจี้ไฟฟ้า(surtron 200)', 96999.78),
    ('Ligasure(LS10)', 900000.0),
    ('Ligasure(FT10)', 1700000.0),
    ('PMS', 780000.0),
    ('Ventilator(Wato Ex-20)', 436500.0),
    ('Ventilator(Veta 5)', 378300.0),
    ('ลู่วิ่งบก', 65800.0),
    ('ลู่วิ่งน้ำ', 252000.0),
    ('เครื่องชั่งน้ำหนัก(TCS-D300_300kg_600*900mm)', 10600.0),
    ('เครื่องชั่งน้ำหนัก(Electronic_Honto_HAW_15kg_230*290 mm)', 6000.0),
    ('เครื่องชั่งน้ำหนัก(Tiger_TB-01H_20kg)', 5000.0),
    ('เครื่องซีล', 30500.0),
    ('Suction(ครื่องดูดเสมหะแบบพกพา Yuwell รุ่น 7E-H1)', 3400.0),
    ('Suction(เครื่องดูดเสมหะไฟฟ้า Suction รุ่น 7A-23B)', 6800.0),
    ('Dicom EKG', 228000.0),
    ('EKG(Fukuda_FCP-8100)', 65000.0),
    ('Digital Otoscope(Firefly)', 40000.0),
    ('Digital Otoscope(Jeed vet)', 5800.0),
    ('Autoclave 24 ลิตร', 74530.0),
    ('HCT Centrifuge', 49755.0),
    ('Pulse Oximeter', 18900.0),
    ('Doppler', 68600.0),
    ('เครื่องวัดความดันรุ่น VVD-310', 27000.0),
    ('Hand held monitor(Epet_T4)', 15000.0),
    ('Microship reader', 20200.0),
    ('ไฟส่องตา(Welch allyn)', 25500.0),
    ('ตู้ฟักไข่และให้ความอบอุ่นสำหรับลูกสัตว์', 34000.0),
    ('เสื้อตะกั่วกันรังสี', 13000.0),
    ('ถุงมือกันรังสี', 8100.0),
    ('ราวแขวนเสื้อ Xray', 21000.0),
    ('โต๊ะวางเครื่องมือผ่าตัด', 11500.01),
    ('โต๊ะผ่าตัด V-Top สแตนเลส ปรับขึ้นลงไฟฟ้า ขนาด130*60ซม', 52155.0),
    ('ตู้ฉุกเฉิน', 11000.0),
    ('ตู้ออกซิเจน พร้อมฐาน 70*120*80 cm', 32000.0),
    ('ตู้ออกซิเจน พร้อมฐาน 60*70*60 cm', 20000.0),
    ('รถเข็นเวชภัณฑ์', 9000.0),
    ('รถเข็นฉีดยา', 7500.0),
    ('รถเข็นสัตว์แบบสองช่อง', 15000.0),
    ('รถเข็นสัตว์แบบเตี้ย', 20000.0),
    ('รถเข็นสัตว์', 24000.0),
    ('ชุด Set ผ่าตัด S', 40000.0),
    ('ชุด Set ผ่าตัด M', 58500.0),
    ('ชุด Set ผ่าตัด L', 62500.0),
]


def seed_medical_equipment_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    # category_id=2 (สินทรัพย์ถาวร / Fix Asset), sub_category_id=4 (เครื่องมือแพทย์
    # / Medical Equipment) — matches the fixed ids every other equipment
    # sub-category migration in this app pins its RunPython against.
    existing_names = set(
        ItemMaster.objects.filter(category_id=2, sub_category_id=4).values_list('item_name', flat=True)
    )
    to_create = [
        ItemMaster(category_id=2, sub_category_id=4, item_name=name, purchase_price=price)
        for name, price in MEDICAL_EQUIPMENT_ITEMS
        if name not in existing_names
    ]
    if to_create:
        ItemMaster.objects.bulk_create(to_create)


def remove_medical_equipment_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    names = [name for name, _ in MEDICAL_EQUIPMENT_ITEMS]
    ItemMaster.objects.filter(category_id=2, sub_category_id=4, item_name__in=names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0016_seed_software_subcategory'),
    ]

    operations = [
        migrations.RunPython(seed_medical_equipment_items, remove_medical_equipment_items),
    ]
