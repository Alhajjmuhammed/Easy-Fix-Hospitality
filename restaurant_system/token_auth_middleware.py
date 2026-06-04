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
    """Return the user for the given DRF token key, or AnonymousUser."""
    try:
        from rest_framework.authtoken.models import Token
        token = Token.objects.select_related('user').get(key=token_key)
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
