from django.contrib import admin
from .models import Transaction, TransactionItem, PatronageDistribution


class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    extra = 0
    readonly_fields = ['total_price']


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ['transaction_number', 'member', 'total_amount', 'payment_method', 'status', 'created_at']
    list_filter = ['payment_method', 'status', 'created_at']
    search_fields = ['transaction_number', 'member__first_name', 'member__last_name']
    readonly_fields = ['transaction_number', 'created_at', 'updated_at']
    inlines = [TransactionItemInline]


@admin.register(TransactionItem)
class TransactionItemAdmin(admin.ModelAdmin):
    list_display = ['transaction', 'product_name', 'quantity', 'unit_price', 'total_price', 'created_at']
    list_filter = ['created_at']
    search_fields = ['product_name', 'transaction__transaction_number']
    readonly_fields = ['total_price', 'created_at']


@admin.register(PatronageDistribution)
class PatronageDistributionAdmin(admin.ModelAdmin):
    list_display = ['member', 'period_start', 'period_end', 'patronage_amount', 'distribution_date']
    list_filter = ['distribution_date']
    search_fields = ['member__first_name', 'member__last_name']
    readonly_fields = ['distribution_date']
