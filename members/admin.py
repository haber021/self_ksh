from django.contrib import admin
from django.contrib.auth.models import User
from .models import MemberType, Member, BalanceTransaction
from django import forms
from django.utils.html import format_html


class MemberPinForm(forms.ModelForm):
    pin = forms.CharField(required=False, max_length=4, min_length=4, help_text='Enter 4-digit PIN to set or leave blank to keep.', widget=forms.PasswordInput(render_value=False))

    class Meta:
        model = Member
        fields = '__all__'

    def clean_pin(self):
        pin = self.cleaned_data.get('pin')
        if pin:
            if not pin.isdigit() or len(pin) != 4:
                raise forms.ValidationError('PIN must be exactly 4 digits')
        return pin

    def clean_user(self):
        user = self.cleaned_data.get('user')
        if user:
            # Check if this username is already used by another member
            username = user.username
            existing_members = Member.objects.filter(user__username=username)
            # Exclude current instance if editing
            if self.instance and self.instance.pk:
                existing_members = existing_members.exclude(pk=self.instance.pk)
            
            if existing_members.exists():
                raise forms.ValidationError(
                    f'Username "{username}" is already assigned to another member: {existing_members.first().full_name}'
                )
        return user

    def save(self, commit=True):
        pin = self.cleaned_data.get('pin')
        instance = super().save(commit=False)
        if pin:
            instance.set_pin(pin)
        if commit:
            instance.save()
        return instance


@admin.register(MemberType)
class MemberTypeAdmin(admin.ModelAdmin):
    list_display = ['name', 'patronage_rate', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['name']


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    form = MemberPinForm
    list_display = ['full_name', 'username', 'rfid_card_number', 'role', 'balance', 'utang_balance', 'total_patronage', 'is_active', 'pin_set']
    list_filter = ['role', 'is_active', 'member_type']
    search_fields = ['first_name', 'last_name', 'rfid_card_number', 'email', 'user__username']
    readonly_fields = ['total_patronage', 'created_at', 'updated_at']

    def username(self, obj):
        if obj.user:
            username_value = obj.user.username
            # Check if this username is duplicated (used by multiple members)
            duplicate_count = Member.objects.filter(user__username=username_value).exclude(pk=obj.pk).count()
            
            if duplicate_count > 0:
                # Show in red if duplicate
                return format_html(
                    '<span style="color: red; font-weight: bold;">{}</span>',
                    username_value
                )
            return username_value
        return '-'
    username.short_description = 'Username'
    username.admin_order_field = 'user__username'

    def pin_set(self, obj):
        return bool(obj.pin_hash)
    pin_set.boolean = True
    pin_set.short_description = 'PIN set?'


@admin.register(BalanceTransaction)
class BalanceTransactionAdmin(admin.ModelAdmin):
    list_display = ['member', 'transaction_type', 'amount', 'balance_after', 'created_at']
    list_filter = ['transaction_type', 'created_at']
    search_fields = ['member__first_name', 'member__last_name']
    readonly_fields = ['created_at']
