from django.urls import path
from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('register/', views.register_view, name='register'),
    path('register-owner/', views.register_owner_view, name='register_owner'),
    path('customer-register/<str:qr_code>/', views.customer_register_view, name='customer_register'),
    path('profile/', views.profile_view, name='profile'),
    path('update-tax-rate/', views.update_tax_rate, name='update_tax_rate'),
    path('access-blocked/', views.access_blocked_view, name='access_blocked'),
    path('rider/', views.rider_home, name='rider_home'),
]
