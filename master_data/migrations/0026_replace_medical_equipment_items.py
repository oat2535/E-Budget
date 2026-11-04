from django.db import migrations


# Master list of Medical Equipment (เครื่องมือแพทย์) items from:
# "Data เครื่องมือแพทย์ For Budget 2027 By พี่หนึ่ง Update.xlsx"
# De-duplicated within the file itself (same as 0017: 'รถเข็นเวชภัณฑ์' appears twice
# at 9,000 and 19,000; the first occurrence is kept).
# Corporate accounting policy for Medical Equipment (sub_category_id=4):
# - '61300010' (ค่าเสื่อมราคา - เครื่องมือแพทย์) for purchase_price >= 5000
# - '60300002' (ค่าอุปกรณ์สำนักงาน-ของใช้สิ้นเปลือง) for purchase_price < 5000
MEDICAL_EQUIPMENT_ITEMS = [
    ('Ultasound(Esaote_เช่าซื้อ)', 2400000.0, '61300010'),
    ('Infusion pump(HK-100)', 15400.0, '61300010'),
    ('Infusion pump (Medcaptain)', 14500.0, '61300010'),
    ('Syringe pump', 19943.93, '61300010'),
    ('Monitor', 160000.0, '61300010'),
    ('Refractometer', 12000.0, '61300010'),
    ('Slit lamp(TOPCON)', 800000.0, '61300010'),
    ('Hand held slit lamp(KEELER)', 250000.0, '61300010'),
    ('Hand held slit lamp(China)', 33215.0, '61300010'),
    ('Wifi thermometer', 4500.0, '60300002'),
    ('ไฟผ่าตัด(ติดเพดาน)', 230000.0, '61300010'),
    ('ไฟผ่าตัด(Mobile)', 152300.0, '61300010'),
    ('Stethoscope', 5000.0, '61300010'),
    ('Tonovet', 178200.0, '61300010'),
    ('กล้องจุลทรรศน์ 3 กระบอกตา', 88000.0, '61300010'),
    ('กล้องจุลทรรศน์ 2 ตา', 50000.0, '61300010'),
    ('Hand Lens', 12500.0, '61300010'),
    ('เครื่อง Laser', 550000.0, '61300010'),
    ('เครื่อง Laser(companion laser)', 890000.0, '61300010'),
    ('DR Xray', 1400000.01, '61300010'),
    ('CT Scan', 2500000.0, '61300010'),
    ('Dental xray', 40000.0, '61300010'),
    ('เครื่องดูดความชื้น', 31780.0, '61300010'),
    ('Warm Air(WARMOLOGY_WMS-1501)', 45000.0, '61300010'),
    ('Warm Air(China)', 16000.0, '61300010'),
    ('Warm Pad', 20000.0, '61300010'),
    ('เครื่องกดนับแยกชนิดเม็ดเลือดขาว', 14500.0, '61300010'),
    ('เครื่องขูดหินปูน', 75000.0, '61300010'),
    ('เครื่องจี้ไฟฟ้า(surtron 160)', 58000.0, '61300010'),
    ('เครื่องจี้ไฟฟ้า(surtron 200)', 96999.78, '61300010'),
    ('Ligasure(LS10)', 900000.0, '61300010'),
    ('Ligasure(FT10)', 1700000.0, '61300010'),
    ('ECT', 516000.0, '61300010'),
    ('PMS', 780000.0, '61300010'),
    ('TMS', 2300000.0, '61300010'),
    ('เครื่องฟอกไต', 1250000.0, '61300010'),
    ('VEP BAEP', 2000000.0, '61300010'),
    ('Ventilator(Wato Ex-20)', 436500.0, '61300010'),
    ('Ventilator(Veta 5)', 378300.0, '61300010'),
    ('ลู่วิ่งบก', 65800.0, '61300010'),
    ('ลู่วิ่งน้ำ', 252000.0, '61300010'),
    ('เครื่องชั่งน้ำหนัก(TCS-D300_300kg_600*900mm)', 10600.0, '61300010'),
    ('เครื่องชั่งน้ำหนัก(Electronic_Honto_HAW_15kg_230*290 mm)', 6000.0, '61300010'),
    ('เครื่องชั่งน้ำหนัก(Tiger_TB-01H_20kg)', 5000.0, '61300010'),
    ('เครื่องซีล', 30500.0, '61300010'),
    ('Suction(ครื่องดูดเสมหะแบบพกพา Yuwell รุ่น 7E-H1)', 3400.0, '60300002'),
    ('Suction(เครื่องดูดเสมหะไฟฟ้า Suction รุ่น 7A-23B)', 6800.0, '61300010'),
    ('Dicom EKG', 228000.0, '61300010'),
    ('EKG(Fukuda_FCP-8100)', 65000.0, '61300010'),
    ('Digital Otoscope(Firefly)', 40000.0, '61300010'),
    ('Digital Otoscope(Jeed vet)', 6240.0, '61300010'),
    ('Wood lamp', 3500.0, '60300002'),
    ('Phovia', 41000.0, '61300010'),
    ('Autoclave 24 ลิตร', 74530.0, '61300010'),
    ('HCT Centrifuge', 49755.0, '61300010'),
    ('Pulse Oximeter', 18900.0, '61300010'),
    ('Doppler', 68600.0, '61300010'),
    ('เครื่องวัดความดันรุ่น VVD-310', 27000.0, '61300010'),
    ('เครื่องวัดความดันรุ่น VMED', 70000.0, '61300010'),
    ('Hand held monitor(Epet_T4)', 15000.0, '61300010'),
    ('Microship reader', 20200.0, '61300010'),
    ('ไฟส่องตา(Welch allyn)', 25500.0, '61300010'),
    ('ตู้ฟักไข่และให้ความอบอุ่นสำหรับลูกสัตว์', 34000.0, '61300010'),
    ('เสื้อตะกั่วกันรังสี', 13000.0, '61300010'),
    ('ถุงมือกันรังสี', 8100.0, '61300010'),
    ('ราวแขวนเสื้อ Xray', 21000.0, '61300010'),
    ('โต๊ะวางเครื่องมือผ่าตัด', 11500.01, '61300010'),
    ('โต๊ะผ่าตัด V-Top สแตนเลส ปรับขึ้นลงไฟฟ้า ขนาด130*60ซม', 52155.0, '61300010'),
    ('ตู้ฉุกเฉิน', 11000.0, '61300010'),
    ('ตู้ออกซิเจน พร้อมฐาน 70*120*80 cm', 32000.0, '61300010'),
    ('ตู้ออกซิเจน พร้อมฐาน 60*70*60 cm', 20000.0, '61300010'),
    ('ตู้ Intensive care(THX-ICU-02)', 315950.0, '61300010'),
    ('ตู้ Intensive care(THX-ICU-03)', 215000.0, '61300010'),
    ('ตู้ Intensive care(THX-ICU-05)', 205000.0, '61300010'),
    ('ตู้ Intensive care(THX-ICU-06)', 225000.0, '61300010'),
    ('รถเข็นเวชภัณฑ์', 9000.0, '61300010'),
    ('รถเข็นฉีดยา', 7500.0, '61300010'),
    ('รถเข็นสัตว์แบบสองช่อง', 15000.0, '61300010'),
    ('รถเข็นสัตว์แบบเตี้ย', 20000.0, '61300010'),
    ('รถเข็นสัตว์', 24000.0, '61300010'),
    ('ชุด Set ผ่าตัด S', 40000.0, '61300010'),
    ('ชุด Set ผ่าตัด M', 58500.0, '61300010'),
    ('ชุด Set ผ่าตัด L', 62500.0, '61300010'),
]

CATEGORY_ID = 2       # Fix Asset / ครุภัณฑ์
SUB_CATEGORY_ID = 4   # Medical Equipment / เครื่องมือแพทย์


def replace_medical_equipment_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    table = ItemMaster._meta.db_table

    # 1. Sync sequence before any operation so nextval never collides
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )

    # 2. Delete all existing medical equipment items EXCEPT 'OTHER'
    ItemMaster.objects.filter(
        category_id=CATEGORY_ID,
        sub_category_id=SUB_CATEGORY_ID
    ).exclude(
        item_name__iexact='OTHER'
    ).delete()

    # 3. Ensure 'OTHER' exists for sub_category_id=4
    if not ItemMaster.objects.filter(category_id=CATEGORY_ID, sub_category_id=SUB_CATEGORY_ID, item_name__iexact='OTHER').exists():
        ItemMaster.objects.create(
            category_id=CATEGORY_ID,
            sub_category_id=SUB_CATEGORY_ID,
            item_name='OTHER',
            purchase_price=0.0,
            salary=0.0,
            position_allowance=0.0,
            estimated_shift_allowance=0.0,
            total_salary=0.0,
            general_ledger_code=None,
        )

    # 4. Re-sync sequence before bulk_create
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )

    # 5. Bulk create the new medical equipment items
    to_create = [
        ItemMaster(
            category_id=CATEGORY_ID,
            sub_category_id=SUB_CATEGORY_ID,
            item_name=item_name,
            purchase_price=price,
            salary=0.0,
            position_allowance=0.0,
            estimated_shift_allowance=0.0,
            total_salary=0.0,
            general_ledger_code=gl_code,
        )
        for item_name, price, gl_code in MEDICAL_EQUIPMENT_ITEMS
    ]
    ItemMaster.objects.bulk_create(to_create)

    # 6. Keep serial sequence in sync in PostgreSQL
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )


def revert_medical_equipment_items(apps, schema_editor):
    ItemMaster = apps.get_model('master_data', 'ebudget_budget_item_master')
    item_names = [name for name, _, _ in MEDICAL_EQUIPMENT_ITEMS]
    ItemMaster.objects.filter(
        category_id=CATEGORY_ID,
        sub_category_id=SUB_CATEGORY_ID,
        item_name__in=item_names,
    ).delete()

    table = ItemMaster._meta.db_table
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), (SELECT MAX(id) FROM " + schema_editor.quote_name(table) + "))",
            [table],
        )


class Migration(migrations.Migration):

    dependencies = [
        ('master_data', '0025_replace_tools_equipment_items'),
        ('budget_app', '0041_clear_medical_equipment_budget_data'),
    ]

    operations = [
        migrations.RunPython(replace_medical_equipment_items, revert_medical_equipment_items),
    ]
