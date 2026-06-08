"""
Token authentication with path-aware expiry.

- Requests to /api/v1/ (mobile app): tokens expire after TOKEN_EXPIRE_DAYS days.
  Expired tokens are deleted so the app gets a clean 401 and prompts re-login.
- All other paths (print client at /orders/api/, web session, etc.):
  standard TokenAuthentication — tokens never expire automatically.
  This prevents the print client's long-lived service token from being deleted.
"""
from datetime import timedelta
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

TOKEN_EXPIRE_DAYS = 15
MOBILE_API_PREFIX = '/api/v1/'


class ExpiringTokenAuthentication(TokenAuthentication):
    """
    Drop-in replacement for TokenAuthentication.
    Applies a 15-day expiry ONLY for mobile API requests (/api/v1/*).
    All other requests (print client, web) use standard non-expiring tokens.
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, token = result

        # Only enforce expiry for mobile API paths
        if not request.path.startswith(MOBILE_API_PREFIX):
            return (user, token)

        # Mobile path — check expiry
        if not user.is_active:
            raise AuthenticationFailed('User inactive or deleted.')

        expiry_time = token.created + timedelta(days=TOKEN_EXPIRE_DAYS)
        if timezone.now() > expiry_time:
            token.delete()
            raise AuthenticationFailed('Token has expired. Please log in again.')

        return (user, token)
