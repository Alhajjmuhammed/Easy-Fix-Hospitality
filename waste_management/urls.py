from django.urls import path
from . import views

app_name = 'waste_management'

urlpatterns = [
    path('', views.waste_dashboard, name='dashboard'),
    path('export-csv/', views.export_waste_csv, name='export_csv'),
    path('export-pdf/', views.export_waste_pdf, name='export_pdf'),
    path('record-waste/', views.record_food_waste, name='record_waste'),
    path('cashier-record/', views.cashier_record_waste, name='cashier_record'),
    path('cashier-waste/', views.cashier_waste_interface, name='cashier_waste_interface'),
    path('cashier-waste-form/', views.cashier_waste_form, name='cashier_waste_form'),
    path('auto-detect/', views.auto_detect_waste, name='auto_detect'),
    path('reports/', views.waste_reports, name='reports'),
    path('export-report/', views.export_waste_report, name='export_report'),
    path('cost-settings/', views.cost_settings, name='cost_settings'),
    path('update-cost-settings/', views.update_cost_settings, name='update_cost_settings'),
    path('api/recent-records/', views.recent_waste_records, name='recent_records'),
    path('edit/<int:log_id>/', views.edit_waste_log, name='edit_log'),
    path('delete/<int:log_id>/', views.delete_waste_log, name='delete_log'),
]