"""
Token authentication with expiry.

- Every path: tokens expire TOKEN_EXPIRE_DAYS days after they were created.
  Expired tokens get a clean 401 every time, so the app prompts re-login (login
  replaces the user's tokens). They are not deleted here: production runs with
  ATOMIC_REQUESTS, and DRF rolls the request's transaction back on a 401, so a
  delete here would be undone anyway.
- One exception: the print-jobs API used by the restaurant's local Print Client
  (/orders/api/print-jobs/, see print_client/print_client.py). The Print Client is a
  headless agent configured once with the owner's token from Printer Settings; it
  cannot log in again by itself, so expiring that token would silently stop all
  printing every 15 days. Those requests keep the standard non-expiring check.
- Tokens are also deleted whenever the user's password changes (accounts/signals.py).
"""
from datetime import timedelta
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

TOKEN_EXPIRE_DAYS = 15
MOBILE_API_PREFIX = '/api/v1/'
# Paths whose callers are long-running agents with a fixed token (no expiry there).
NON_EXPIRING_PREFIXES = ('/orders/api/print-jobs/',)


class ExpiringTokenAuthentication(TokenAuthentication):
    """
    Drop-in replacement for TokenAuthentication.
    Applies a 15-day expiry on every path except the Print Client's print-jobs API.
    """

    def authenticate(self, request):
        result = super().authenticate(request)
        if result is None:
            return None

        user, token = result

        if not user.is_active:
            raise AuthenticationFailed('User inactive or deleted.')

        if request.path.startswith(NON_EXPIRING_PREFIXES):
            return (user, token)

        expiry_time = token.created + timedelta(days=TOKEN_EXPIRE_DAYS)
        if timezone.now() > expiry_time:
            raise AuthenticationFailed('Token has expired. Please log in again.')

        return (user, token)
