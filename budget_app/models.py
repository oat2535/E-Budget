from django.db import models

class Timestamp0Field(models.DateTimeField):
    def db_type(self, connection):
        return 'timestamp(0)'

class ebudget_vet_manpower(models.Model):
    position_name = models.CharField(max_length=255, verbose_name="ตำแหน่ง")
    salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="เงินเดือน")
    base_branch_id = models.CharField(max_length=20, verbose_name="รหัสสาขาหลัก", null=True, blank=True)
    base_sub_branch_id = models.CharField(max_length=20, verbose_name="รหัสสาขาย่อย", null=True, blank=True)
    document_no = models.CharField(max_length=50, verbose_name="เลขที่เอกสาร", null=True, blank=True)
    item_master = models.ForeignKey('master_data.ebudget_budget_item_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง Item Master")
    general_ledger = models.ForeignKey('master_data.ebudget_general_ledger_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง General Ledger")
    
    create_date = Timestamp0Field(verbose_name="วันที่สร้าง", null=True, blank=True)
    create_eid = models.CharField(max_length=50, verbose_name="ผู้สร้าง (Employee ID)")
    modify_date = Timestamp0Field(verbose_name="วันที่แก้ไขล่าสุด", null=True, blank=True)
    modify_eid = models.CharField(max_length=50, verbose_name="ผู้แก้ไข (Employee ID)", null=True, blank=True)

    def save(self, *args, **kwargs):
        from datetime import datetime
        now = datetime.now().replace(microsecond=0)
        if not self.id and not self.create_date:
            self.create_date = now
        self.modify_date = now
        super().save(*args, **kwargs)

    @property
    def monthly_data_dict(self):
        month_map_rev = {
            1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr',
            5: 'may', 6: 'jun', 7: 'jul', 8: 'aug',
            9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
        }
        res = {}
        for detail in self.monthly_details.all():
            m_str = month_map_rev.get(detail.month)
            if m_str:
                res[m_str] = {
                    'headcount': float(detail.headcount),
                    'cost': float(detail.cost)
                }
        return res

    class Meta:
        db_table = 'ebudget_vet_manpower'
        verbose_name = "VET Manpower Budget"
        verbose_name_plural = "VET Manpower Budgets"

    def __str__(self):
        return f"{self.position_name} - {self.salary}"

class ebudget_non_vet_manpower(models.Model):
    position_name = models.CharField(max_length=255, verbose_name="ตำแหน่ง")
    salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="เงินเดือน")
    position_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ค่าวัดระดับ/ตำแหน่ง")
    base_branch_id = models.CharField(max_length=20, verbose_name="รหัสสาขาหลัก", null=True, blank=True)
    base_sub_branch_id = models.CharField(max_length=20, verbose_name="รหัสสาขาย่อย", null=True, blank=True)
    document_no = models.CharField(max_length=50, verbose_name="เลขที่เอกสาร", null=True, blank=True)
    item_master = models.ForeignKey('master_data.ebudget_budget_item_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง Item Master")
    general_ledger = models.ForeignKey('master_data.ebudget_general_ledger_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง General Ledger")
    
    create_date = Timestamp0Field(verbose_name="วันที่สร้าง", null=True, blank=True)
    create_eid = models.CharField(max_length=50, verbose_name="ผู้สร้าง (Employee ID)")
    modify_date = Timestamp0Field(verbose_name="วันที่แก้ไขล่าสุด", null=True, blank=True)
    modify_eid = models.CharField(max_length=50, verbose_name="ผู้แก้ไข (Employee ID)", null=True, blank=True)

    def save(self, *args, **kwargs):
        from datetime import datetime
        now = datetime.now().replace(microsecond=0)
        if not self.id and not self.create_date:
            self.create_date = now
        self.modify_date = now
        super().save(*args, **kwargs)

    @property
    def monthly_data_dict(self):
        month_map_rev = {
            1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr',
            5: 'may', 6: 'jun', 7: 'jul', 8: 'aug',
            9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
        }
        res = {}
        for detail in self.monthly_details.all():
            m_str = month_map_rev.get(detail.month)
            if m_str:
                res[m_str] = {
                    'headcount': float(detail.headcount),
                    'cost': float(detail.cost)
                }
        return res

    class Meta:
        db_table = 'ebudget_non_vet_manpower'
        verbose_name = "NON VET Manpower Budget"
        verbose_name_plural = "NON VET Manpower Budgets"

    def __str__(self):
        return f"{self.position_name} - {self.salary}"

class ebudget_position_adjustment(models.Model):
    old_position_name = models.CharField(max_length=255, verbose_name="ตำแหน่งเดิม")
    new_position_name = models.CharField(max_length=255, verbose_name="ตำแหน่งใหม่")
    old_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="เงินเดือนเดิม")
    old_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ค่าวัดระดับ/ตำแหน่งเดิม")
    new_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="เงินเดือนใหม่")
    new_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ค่าวัดระดับ/ตำแหน่งใหม่")
    base_branch_id = models.CharField(max_length=20, verbose_name="รหัสสาขาหลัก", null=True, blank=True)
    document_no = models.CharField(max_length=50, verbose_name="เลขที่เอกสาร", null=True, blank=True)
    item_master = models.ForeignKey('master_data.ebudget_budget_item_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง Item Master")
    general_ledger = models.ForeignKey('master_data.ebudget_general_ledger_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง General Ledger")
    
    create_date = Timestamp0Field(verbose_name="วันที่สร้าง", null=True, blank=True)
    create_eid = models.CharField(max_length=50, verbose_name="ผู้สร้าง (Employee ID)")
    modify_date = Timestamp0Field(verbose_name="วันที่แก้ไขล่าสุด", null=True, blank=True)
    modify_eid = models.CharField(max_length=50, verbose_name="ผู้แก้ไข (Employee ID)", null=True, blank=True)

    def save(self, *args, **kwargs):
        from datetime import datetime
        now = datetime.now().replace(microsecond=0)
        if not self.id and not self.create_date:
            self.create_date = now
        self.modify_date = now
        super().save(*args, **kwargs)

    @property
    def monthly_data_dict(self):
        month_map_rev = {
            1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr',
            5: 'may', 6: 'jun', 7: 'jul', 8: 'aug',
            9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
        }
        res = {}
        for detail in self.monthly_details.all():
            m_str = month_map_rev.get(detail.month)
            if m_str:
                res[m_str] = {
                    'headcount': float(detail.headcount),
                    'cost': float(detail.cost)
                }
        return res

    class Meta:
        db_table = 'ebudget_position_adjustment'
        verbose_name = "Position Adjustment"
        verbose_name_plural = "Position Adjustments"

    def __str__(self):
        return f"{self.document_no} - {self.old_position_name} -> {self.new_position_name}"

class ebudget_medical_equipment(models.Model):
    item_name = models.CharField(max_length=255, verbose_name="เครื่องมือ")
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ราคาซื้อ")
    base_branch_id = models.CharField(max_length=20, verbose_name="รหัสสาขาหลัก", null=True, blank=True)
    document_no = models.CharField(max_length=50, verbose_name="เลขที่เอกสาร", null=True, blank=True)
    item_master = models.ForeignKey('master_data.ebudget_budget_item_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง Item Master")
    general_ledger = models.ForeignKey('master_data.ebudget_general_ledger_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง General Ledger")
    
    create_date = Timestamp0Field(verbose_name="วันที่สร้าง", null=True, blank=True)
    create_eid = models.CharField(max_length=50, verbose_name="ผู้สร้าง (Employee ID)")
    modify_date = Timestamp0Field(verbose_name="วันที่แก้ไขล่าสุด", null=True, blank=True)
    modify_eid = models.CharField(max_length=50, verbose_name="ผู้แก้ไข (Employee ID)", null=True, blank=True)

    def save(self, *args, **kwargs):
        from datetime import datetime
        now = datetime.now().replace(microsecond=0)
        if not self.id and not self.create_date:
            self.create_date = now
        self.modify_date = now
        super().save(*args, **kwargs)

    @property
    def monthly_data_dict(self):
        month_map_rev = {
            1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr',
            5: 'may', 6: 'jun', 7: 'jul', 8: 'aug',
            9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
        }
        res = {}
        for detail in self.monthly_details.all():
            m_str = month_map_rev.get(detail.month)
            if m_str:
                res[m_str] = {
                    'headcount': float(detail.headcount),
                    'cost': float(detail.cost)
                }
        return res

    class Meta:
        db_table = 'ebudget_medical_equipment'
        verbose_name = "Medical Equipment Budget"
        verbose_name_plural = "Medical Equipment Budgets"

    def __str__(self):
        return f"{self.item_name} - {self.purchase_price}"

class ebudget_computer_equipment(models.Model):
    item_name = models.CharField(max_length=255, verbose_name="เครื่องมือ")
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ราคาซื้อ")
    base_branch_id = models.CharField(max_length=20, verbose_name="รหัสสาขาหลัก", null=True, blank=True)
    document_no = models.CharField(max_length=50, verbose_name="เลขที่เอกสาร", null=True, blank=True)
    item_master = models.ForeignKey('master_data.ebudget_budget_item_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง Item Master")
    general_ledger = models.ForeignKey('master_data.ebudget_general_ledger_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง General Ledger")
    
    create_date = Timestamp0Field(verbose_name="วันที่สร้าง", null=True, blank=True)
    create_eid = models.CharField(max_length=50, verbose_name="ผู้สร้าง (Employee ID)")
    modify_date = Timestamp0Field(verbose_name="วันที่แก้ไขล่าสุด", null=True, blank=True)
    modify_eid = models.CharField(max_length=50, verbose_name="ผู้แก้ไข (Employee ID)", null=True, blank=True)

    def save(self, *args, **kwargs):
        from datetime import datetime
        now = datetime.now().replace(microsecond=0)
        if not self.id and not self.create_date:
            self.create_date = now
        self.modify_date = now
        super().save(*args, **kwargs)

    @property
    def monthly_data_dict(self):
        month_map_rev = {
            1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr',
            5: 'may', 6: 'jun', 7: 'jul', 8: 'aug',
            9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
        }
        res = {}
        for detail in self.monthly_details.all():
            m_str = month_map_rev.get(detail.month)
            if m_str:
                res[m_str] = {
                    'headcount': float(detail.headcount),
                    'cost': float(detail.cost)
                }
        return res

    class Meta:
        db_table = 'ebudget_computer_equipment'
        verbose_name = "Computer Equipment Budget"
        verbose_name_plural = "Computer Equipment Budgets"

    def __str__(self):
        return f"{self.item_name} - {self.purchase_price}"

class ebudget_furniture(models.Model):
    item_name = models.CharField(max_length=255, verbose_name="เครื่องมือ")
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ราคาซื้อ")
    base_branch_id = models.CharField(max_length=20, verbose_name="รหัสสาขาหลัก", null=True, blank=True)
    document_no = models.CharField(max_length=50, verbose_name="เลขที่เอกสาร", null=True, blank=True)
    item_master = models.ForeignKey('master_data.ebudget_budget_item_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง Item Master")
    general_ledger = models.ForeignKey('master_data.ebudget_general_ledger_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง General Ledger")

    create_date = Timestamp0Field(verbose_name="วันที่สร้าง", null=True, blank=True)
    create_eid = models.CharField(max_length=50, verbose_name="ผู้สร้าง (Employee ID)")
    modify_date = Timestamp0Field(verbose_name="วันที่แก้ไขล่าสุด", null=True, blank=True)
    modify_eid = models.CharField(max_length=50, verbose_name="ผู้แก้ไข (Employee ID)", null=True, blank=True)

    def save(self, *args, **kwargs):
        from datetime import datetime
        now = datetime.now().replace(microsecond=0)
        if not self.id and not self.create_date:
            self.create_date = now
        self.modify_date = now
        super().save(*args, **kwargs)

    @property
    def monthly_data_dict(self):
        month_map_rev = {
            1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr',
            5: 'may', 6: 'jun', 7: 'jul', 8: 'aug',
            9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
        }
        res = {}
        for detail in self.monthly_details.all():
            m_str = month_map_rev.get(detail.month)
            if m_str:
                res[m_str] = {
                    'headcount': float(detail.headcount),
                    'cost': float(detail.cost)
                }
        return res

    class Meta:
        db_table = 'ebudget_furniture'
        verbose_name = "Furniture Budget"
        verbose_name_plural = "Furniture Budgets"

    def __str__(self):
        return f"{self.item_name} - {self.purchase_price}"

class ebudget_tools_equipment(models.Model):
    item_name = models.CharField(max_length=255, verbose_name="เครื่องมือ")
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ราคาซื้อ")
    base_branch_id = models.CharField(max_length=20, verbose_name="รหัสสาขาหลัก", null=True, blank=True)
    document_no = models.CharField(max_length=50, verbose_name="เลขที่เอกสาร", null=True, blank=True)
    item_master = models.ForeignKey('master_data.ebudget_budget_item_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง Item Master")
    general_ledger = models.ForeignKey('master_data.ebudget_general_ledger_master', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="อ้างอิง General Ledger")

    create_date = Timestamp0Field(verbose_name="วันที่สร้าง", null=True, blank=True)
    create_eid = models.CharField(max_length=50, verbose_name="ผู้สร้าง (Employee ID)")
    modify_date = Timestamp0Field(verbose_name="วันที่แก้ไขล่าสุด", null=True, blank=True)
    modify_eid = models.CharField(max_length=50, verbose_name="ผู้แก้ไข (Employee ID)", null=True, blank=True)

    def save(self, *args, **kwargs):
        from datetime import datetime
        now = datetime.now().replace(microsecond=0)
        if not self.id and not self.create_date:
            self.create_date = now
        self.modify_date = now
        super().save(*args, **kwargs)

    @property
    def monthly_data_dict(self):
        month_map_rev = {
            1: 'jan', 2: 'feb', 3: 'mar', 4: 'apr',
            5: 'may', 6: 'jun', 7: 'jul', 8: 'aug',
            9: 'sep', 10: 'oct', 11: 'nov', 12: 'dec'
        }
        res = {}
        for detail in self.monthly_details.all():
            m_str = month_map_rev.get(detail.month)
            if m_str:
                res[m_str] = {
                    'headcount': float(detail.headcount),
                    'cost': float(detail.cost)
                }
        return res

    class Meta:
        db_table = 'ebudget_tools_equipment'
        verbose_name = "Tools & Equipment Budget"
        verbose_name_plural = "Tools & Equipment Budgets"

    def __str__(self):
        return f"{self.item_name} - {self.purchase_price}"

class BudgetMonthlyDetail(models.Model):
    MONTH_CHOICES = [(i, str(i)) for i in range(1, 13)]
    
    month = models.PositiveSmallIntegerField(choices=MONTH_CHOICES, verbose_name="เดือน (1-12)")
    headcount = models.DecimalField(max_digits=10, decimal_places=2, default=0, verbose_name="จำนวน (คน/ชิ้น)")
    cost = models.DecimalField(max_digits=14, decimal_places=2, default=0, verbose_name="งบประมาณ (Cost)")
    
    vet_budget = models.ForeignKey(ebudget_vet_manpower, on_delete=models.CASCADE, null=True, blank=True, related_name='monthly_details')
    non_vet_budget = models.ForeignKey(ebudget_non_vet_manpower, on_delete=models.CASCADE, null=True, blank=True, related_name='monthly_details')
    position_adj = models.ForeignKey(ebudget_position_adjustment, on_delete=models.CASCADE, null=True, blank=True, related_name='monthly_details')
    med_equip = models.ForeignKey(ebudget_medical_equipment, on_delete=models.CASCADE, null=True, blank=True, related_name='monthly_details')
    comp_equip = models.ForeignKey(ebudget_computer_equipment, on_delete=models.CASCADE, null=True, blank=True, related_name='monthly_details')
    furniture_equip = models.ForeignKey(ebudget_furniture, on_delete=models.CASCADE, null=True, blank=True, related_name='monthly_details')
    tools_equip = models.ForeignKey(ebudget_tools_equipment, on_delete=models.CASCADE, null=True, blank=True, related_name='monthly_details')

    class Meta:
        db_table = 'ebudget_monthly_detail'
        verbose_name = "Budget Monthly Detail"
        verbose_name_plural = "Budget Monthly Details"

    def __str__(self):
        return f"Month {self.month} - Headcount: {self.headcount}, Cost: {self.cost}"
