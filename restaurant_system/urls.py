"""restaurant_system URL Configuration"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.views.generic import RedirectView
from django.http import HttpResponse
from django.views.decorators.http import require_GET
from django.shortcuts import render
import os
from accounts.views import qr_code_access

# Import security views
try:
    from restaurant_system.security_decorators import rate_limited_view
except ImportError:
    # Fallback if django-ratelimit not installed
    def rate_limited_view(request, exception=None):
        return render(request, 'accounts/rate_limited.html', {'retry_after': 60}, status=429)

@require_GET
def service_worker(request):
    """Serve the service worker with proper headers"""
    service_worker_path = os.path.join(settings.BASE_DIR, 'service-worker.js')
    
    try:
        with open(service_worker_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        response = HttpResponse(content, content_type='application/javascript')
        response['Service-Worker-Allowed'] = '/'
        response['Cache-Control'] = 'no-cache'
        return response
    except FileNotFoundError:
        return HttpResponse('Service worker not found', status=404)

urlpatterns = [
    path('', RedirectView.as_view(url='/accounts/login/', permanent=False), name='root'),
    path('service-worker.js', service_worker, name='service_worker'),
    # Security endpoints
    path('rate-limited/', rate_limited_view, name='rate_limited'),
    # QR Code access - short URL for restaurant access
    path('r/<str:qr_code>/', qr_code_access, name='qr_code_access'),
    path('admin/', admin.site.urls),
    path('admin-panel/', include('admin_panel.urls')),
    path('system-admin/', include('system_admin.urls')),
    path('cashier/', include('cashier.urls')),
    path('waste-management/', include('waste_management.urls')),
    path('reports/', include('reports.urls')),
    path('accounts/', include('accounts.urls')),
    path('orders/', include('orders.urls')),
    path('restaurant/', include('restaurant.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
