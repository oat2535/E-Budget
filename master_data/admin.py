from django.contrib import admin
from .models import (
    ebudget_general_ledger_master,
    ebudget_budget_category_master,
    ebudget_budget_sub_category_master,
    ebudget_budget_item_master
)

@admin.register(ebudget_general_ledger_master)
class EbudgetGeneralLedgerMasterAdmin(admin.ModelAdmin):
    list_display = [field.name for field in ebudget_general_ledger_master._meta.fields]

@admin.register(ebudget_budget_category_master)
class EbudgetBudgetCategoryMasterAdmin(admin.ModelAdmin):
    list_display = [field.name for field in ebudget_budget_category_master._meta.fields]

@admin.register(ebudget_budget_sub_category_master)
class EbudgetBudgetSubCategoryMasterAdmin(admin.ModelAdmin):
    list_display = [field.name for field in ebudget_budget_sub_category_master._meta.fields]

@admin.register(ebudget_budget_item_master)
class EbudgetBudgetItemMasterAdmin(admin.ModelAdmin):
    list_display = [field.name for field in ebudget_budget_item_master._meta.fields]
