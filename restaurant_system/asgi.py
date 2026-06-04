import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

# Set the Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'restaurant_system.settings')

# Initialize Django
django.setup()

# Get the Django ASGI application
django_asgi_app = get_asgi_application()

# Import routing after Django is set up
import orders.routing
from restaurant_system.token_auth_middleware import TokenAuthMiddleware

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    # TokenAuthMiddleware first: reads ?token=<drf-token> from the WS URL
    # so mobile clients can authenticate without session cookies.
    # AuthMiddlewareStack handles session-based auth (web browsers) as fallback.
    "websocket": TokenAuthMiddleware(
        AuthMiddlewareStack(
            URLRouter(
                orders.routing.websocket_urlpatterns
            )
        )
    ),
})
