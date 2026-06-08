"""
Custom token authentication with expiry support.
Tokens older than TOKEN_EXPIRE_DAYS are rejected and deleted automatically.
"""
from datetime import timedelta
from django.utils import timezone
from rest_framework.authentication import TokenAuthentication
from rest_framework.exceptions import AuthenticationFailed

TOKEN_EXPIRE_DAYS = 15


class ExpiringTokenAuthentication(TokenAuthentication):
    """
    Extends DRF TokenAuthentication to enforce a 15-day expiry window.
    If the token has expired, it is deleted from the DB and a 401 is returned
    so the mobile app auto-logs out and prompts the user to re-authenticate.
    """

    def authenticate_credentials(self, key):
        model = self.get_model()
        try:
            token = model.objects.select_related('user').get(key=key)
        except model.DoesNotExist:
            raise AuthenticationFailed('Invalid token.')

        if not token.user.is_active:
            raise AuthenticationFailed('User inactive or deleted.')

        expiry_time = token.created + timedelta(days=TOKEN_EXPIRE_DAYS)
        if timezone.now() > expiry_time:
            token.delete()
            raise AuthenticationFailed(
                'Token has expired. Please log in again.'
            )

        return (token.user, token)
