"""
Django Channels WebSocket middleware for DRF Token authentication.

Mobile clients cannot send HTTP headers on the initial WebSocket handshake in
most environments, so instead they pass the DRF token as a URL query param:

    ws://host/ws/order/123/?token=<drf-token>

This middleware reads that param, looks up the matching DRF Token, and sets
scope['user'] — exactly what AuthMiddlewareStack does for session cookies.

Usage (asgi.py):
    from restaurant_system.token_auth_middleware import TokenAuthMiddleware

    application = ProtocolTypeRouter({
        "websocket": TokenAuthMiddleware(
            AuthMiddlewareStack(
                URLRouter(websocket_urlpatterns)
            )
        ),
    })
"""

from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser


@database_sync_to_async
def _get_user_from_token(token_key: str):
    from rest_framework.authtoken.models import Token
    from django.utils import timezone
    from datetime import timedelta
    TOKEN_EXPIRY_DAYS = 15
    try:
        token = Token.objects.select_related('user').get(key=token_key)
        if not token.user.is_active:
            return AnonymousUser()
        if timezone.now() > token.created + timedelta(days=TOKEN_EXPIRY_DAYS):
            return AnonymousUser()
        return token.user
    except Exception:
        return AnonymousUser()


class TokenAuthMiddleware(BaseMiddleware):
    """
    Reads ?token=<key> from the WebSocket URL and authenticates the user.
    If no token param is present, the scope is passed through unchanged
    (AuthMiddlewareStack will then handle session-based auth as a fallback).
    """

    async def __call__(self, scope, receive, send):
        # Only process WebSocket connections
        if scope.get('type') == 'websocket':
            qs = scope.get('query_string', b'').decode('utf-8')
            params = parse_qs(qs)
            token_key = (params.get('token') or [None])[0]
            if token_key:
                scope = dict(scope)  # make a mutable copy
                scope['user'] = await _get_user_from_token(token_key)
        return await super().__call__(scope, receive, send)


# ---------------------------------------------------------------------------
# Origin check (Cross-Site WebSocket Hijacking protection)
# ---------------------------------------------------------------------------
from channels.security.websocket import OriginValidator  # noqa: E402


class _HostsOriginValidator(OriginValidator):
    """
    Channels' AllowedHostsOriginValidator, except a handshake WITHOUT an Origin header
    is let through.

    Browsers always send Origin on a WebSocket handshake, so a page on another site
    (the cross-site hijacking attack, which would ride on the victim's session cookie)
    is still rejected. Native clients (the React Native app, scripts) may omit Origin;
    they authenticate with ?token=, not cookies, so the Origin check adds nothing for
    them. Stock channels 4.1 rejects a missing Origin unless ALLOWED_HOSTS has '*'.
    A literal "Origin: null" (sandboxed iframes, file:// pages) is still rejected.
    """

    def valid_origin(self, parsed_origin):
        if parsed_origin is None:
            return True
        return super().valid_origin(parsed_origin)


def AllowedHostsOriginValidator(application):
    """Only accept WebSocket handshakes whose Origin host is in settings.ALLOWED_HOSTS."""
    from django.conf import settings
    allowed_hosts = settings.ALLOWED_HOSTS
    if settings.DEBUG and not allowed_hosts:
        allowed_hosts = ['localhost', '127.0.0.1', '[::1]']
    return _HostsOriginValidator(application, allowed_hosts)
