from django.urls import path
from . import views

app_name = 'cashier'

urlpatterns = [
    path('', views.cashier_dashboard, name='dashboard'),
    path('process-payment/<int:order_id>/', views.process_payment, name='process_payment'),
    path('void-payment/<int:payment_id>/', views.void_payment, name='void_payment'),
    path('cancel-order/<int:order_id>/', views.cancel_order, name='cancel_order'),
    path('payment-history/<int:order_id>/', views.payment_history, name='payment_history'),
    path('receipt/<int:payment_id>/', views.generate_receipt, name='generate_receipt'),
    path('reprint/<int:payment_id>/', views.reprint_receipt, name='reprint_receipt'),
    path('receipts/', views.receipt_management, name='receipt_management'),
    path('print-bill/<int:order_id>/', views.print_bill, name='print_bill'),
]