from django.contrib import admin
from .models import (
    ebudget_general_ledger_master,
    ebudget_budget_category_master,
    ebudget_budget_sub_category_master,
    ebudget_budget_item_master,
    ebudget_cost_center_master
)

@admin.register(ebudget_general_ledger_master)
class EbudgetGeneralLedgerMasterAdmin(admin.ModelAdmin):
    # Swap proportion/depreciation for % display methods (same list
    # position as the raw fields) — the stored value is a whole percent
    # number (15.00 = 15%), so this is purely a "%" suffix, not a x100 scale
    # conversion.
    list_display = [
        {'proportion': 'proportion_percent', 'depreciation': 'depreciation_percent'}.get(field.name, field.name)
        for field in ebudget_general_ledger_master._meta.fields
    ]

    @admin.display(description='สัดส่วน (%)', ordering='proportion')
    def proportion_percent(self, obj):
        return f"{obj.proportion}%"

    @admin.display(description='ค่าเสื่อม (%)', ordering='depreciation')
    def depreciation_percent(self, obj):
        return f"{obj.depreciation}%"

@admin.register(ebudget_budget_category_master)
class EbudgetBudgetCategoryMasterAdmin(admin.ModelAdmin):
    list_display = [field.name for field in ebudget_budget_category_master._meta.fields]

@admin.register(ebudget_budget_sub_category_master)
class EbudgetBudgetSubCategoryMasterAdmin(admin.ModelAdmin):
    list_display = [field.name for field in ebudget_budget_sub_category_master._meta.fields]

@admin.register(ebudget_budget_item_master)
class EbudgetBudgetItemMasterAdmin(admin.ModelAdmin):
    list_display = [field.name for field in ebudget_budget_item_master._meta.fields]

@admin.register(ebudget_cost_center_master)
class EbudgetCostCenterMasterAdmin(admin.ModelAdmin):
    list_display = [field.name for field in ebudget_cost_center_master._meta.fields]
