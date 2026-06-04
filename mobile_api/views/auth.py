import logging
import re

from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from ..permissions import IsSubscriptionActive
from rest_framework.authtoken.models import Token
from rest_framework.response import Response
from rest_framework import status
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from ..serializers import UserSerializer

logger = logging.getLogger(__name__)


@api_view(['POST'])
@permission_classes([AllowAny])
def login(request):
    """Authenticate and return a DRF token + user profile."""
    username = request.data.get('username', '').strip()
    password = request.data.get('password', '')

    if not username or not password:
        return Response(
            {'error': 'Username and password are required.'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        user = authenticate(request, username=username, password=password)
    except Exception:
        # django-axes raises PermissionDenied when account is locked out
        logger.warning('Mobile login locked out for username: %s', username)
        return Response(
            {'error': 'Too many failed login attempts. Account temporarily locked.'},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not user:
        logger.warning('Failed mobile login for username: %s', username)
        return Response(
            {'error': 'Invalid username or password.'},
            status=status.HTTP_401_UNAUTHORIZED,
        )

    if not user.is_active:
        return Response(
            {'error': 'This account is inactive.'},
            status=status.HTTP_403_FORBIDDEN,
        )

    # Check subscription for staff users
    if not user.is_customer():
        owner = user.get_owner()
        if owner:
            try:
                sub = owner.subscription
                if sub.subscription_status in ('expired', 'blocked'):
                    return Response(
                        {'error': 'Restaurant subscription has expired. Contact your administrator.'},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            except Exception:
                pass

    token, _ = Token.objects.get_or_create(user=user)
    logger.info('Mobile login success: %s', username)

    return Response({
        'token': token.key,
        'user': UserSerializer(user, context={'request': request}).data,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def logout(request):
    """Invalidate the current token."""
    try:
        request.user.auth_token.delete()
    except Exception:
        pass
    return Response({'message': 'Logged out successfully.'})


@api_view(['GET'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def me(request):
    """Return the current user's profile."""
    return Response(UserSerializer(request.user, context={'request': request}).data)


@api_view(['POST'])
@permission_classes([IsAuthenticated, IsSubscriptionActive])
def save_push_token(request):
    """Save the Expo push token for the current user (for push notifications)."""
    token = request.data.get('token', '').strip()
    if not token:
        return Response({'error': 'Token is required.'}, status=status.HTTP_400_BAD_REQUEST)
    request.user.expo_push_token = token
    request.user.save(update_fields=['expo_push_token'])
    return Response({'message': 'Push token saved.'})


_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_]{3,150}$')


@api_view(['POST'])
@permission_classes([AllowAny])
def register(request):
    """
    Customer self-registration (mirrors web's customer_register_view).
    Required fields: username, email, first_name, last_name, password, confirm_password.
    Optional: phone_number.
    Always creates a customer-role account (no role escalation possible).
    """
    from django.contrib.auth import get_user_model
    from accounts.models import Role

    User = get_user_model()
    data = request.data

    username = (data.get('username') or '').strip()
    email = (data.get('email') or '').strip().lower()
    first_name = (data.get('first_name') or '').strip()
    last_name = (data.get('last_name') or '').strip()
    phone_number = (data.get('phone_number') or '').strip()
    password = data.get('password', '')
    confirm_password = data.get('confirm_password', '')

    # --- Field validation ---
    if not username:
        return Response({'error': 'Username is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not _USERNAME_RE.match(username):
        return Response(
            {'error': 'Username may only contain letters, numbers, and underscores (3–150 chars).'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if User.objects.filter(username__iexact=username).exists():
        return Response({'error': 'This username is already taken.'}, status=status.HTTP_400_BAD_REQUEST)

    if not email:
        return Response({'error': 'Email is required.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        validate_email(email)
    except ValidationError:
        return Response({'error': 'Enter a valid email address.'}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(email__iexact=email).exists():
        return Response({'error': 'This email is already registered.'}, status=status.HTTP_400_BAD_REQUEST)

    if not first_name:
        return Response({'error': 'First name is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if not last_name:
        return Response({'error': 'Last name is required.'}, status=status.HTTP_400_BAD_REQUEST)

    if not password:
        return Response({'error': 'Password is required.'}, status=status.HTTP_400_BAD_REQUEST)
    if password != confirm_password:
        return Response({'error': 'Passwords do not match.'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        validate_password(password)
    except ValidationError as exc:
        return Response({'error': ' '.join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

    # --- Create user ---
    customer_role, _ = Role.objects.get_or_create(
        name='customer',
        defaults={'description': 'Customer'},
    )
    user = User(
        username=username,
        email=email,
        first_name=first_name,
        last_name=last_name,
        phone_number=phone_number,
        role=customer_role,
        owner=None,  # Universal customer — not tied to a specific restaurant
    )
    user.set_password(password)
    user.save()

    token, _ = Token.objects.get_or_create(user=user)
    logger.info('Mobile customer registered: %s', username)

    return Response(
        {
            'token': token.key,
            'user': UserSerializer(user, context={'request': request}).data,
            'message': 'Account created successfully. Welcome!',
        },
        status=status.HTTP_201_CREATED,
    )
