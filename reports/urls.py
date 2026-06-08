from django.urls import path
from . import views

app_name = 'reports'

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('dashboard/', views.dashboard),  # alias so /reports/dashboard/ also works
    path('export/', views.export_csv, name='export_csv'),
    path('export-pdf/', views.export_pdf, name='export_pdf'),
    path('money-flow/', views.money_flow, name='money_flow'),
]