from django.urls import path
from . import views

app_name = 'mobile_api'

urlpatterns = [
    path('login/', views.mobile_login, name='mobile_login'),
    path('account/', views.account_info, name='account_info'),
    path('account/summary/', views.account_summary, name='account_summary'),
    path('transactions/', views.transaction_history, name='transaction_history'),
    path('balance-transactions/', views.balance_transactions, name='balance_transactions'),
]

