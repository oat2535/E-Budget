from django.db import models

class ebudget_general_ledger_master(models.Model):
    gl_code = models.CharField(max_length=50, unique=True, verbose_name="รหัส general ledger")
    gl_name = models.CharField(max_length=255, verbose_name="ชื่อ general_ledger")

    def __str__(self):
        return f"{self.gl_code} - {self.gl_name}"

class ebudget_budget_category_master(models.Model):
    category_code = models.CharField(max_length=50, unique=True, verbose_name="รหัส category")
    category_name = models.CharField(max_length=255, verbose_name="ชื่อ category")

    def __str__(self):
        return f"{self.category_code} - {self.category_name}"

class ebudget_budget_sub_category_master(models.Model):
    category = models.ForeignKey(ebudget_budget_category_master, on_delete=models.CASCADE, verbose_name="Category")
    sub_category_code = models.CharField(max_length=50, unique=True, verbose_name="รหัส sub_category")
    sub_category_name = models.CharField(max_length=255, verbose_name="ชื่อ sub_category")

    def __str__(self):
        return f"{self.sub_category_code} - {self.sub_category_name}"

class ebudget_budget_item_master(models.Model):
    general_ledger = models.ForeignKey(ebudget_general_ledger_master, on_delete=models.CASCADE, verbose_name="General Ledger", null=True, blank=True)
    category = models.ForeignKey(ebudget_budget_category_master, on_delete=models.CASCADE, verbose_name="Category", null=True, blank=True)
    sub_category = models.ForeignKey(ebudget_budget_sub_category_master, on_delete=models.CASCADE, verbose_name="Sub Category", null=True, blank=True)
    item_name = models.CharField(max_length=255, verbose_name="ชื่อตำแหน่ง/รายการ")
    salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="เงินเดือน")
    estimated_shift_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ค่าเวรโดยประมาณ")
    position_allowance = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ค่าวัดระดับ/ตำแหน่ง")
    total_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="รวม")
    purchase_price = models.DecimalField(max_digits=12, decimal_places=2, default=0, verbose_name="ราคาซื้อ")

    def __str__(self):
        return self.item_name
