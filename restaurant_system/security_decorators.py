"""
Security Decorators for Restaurant Ordering System
Provides rate limiting and security utilities for views
"""

from django_ratelimit.decorators import ratelimit
from functools import wraps
from django.shortcuts import render
from django.http import HttpResponse


def rate_limit_login(func):
    """
    Rate limiter for login attempts
    - Blocks excessive login attempts
    - Works in harmony with django-axes (which handles failed attempts)
    - Rate limiting is per IP address
    """
    @wraps(func)
    @ratelimit(key='ip', rate='20/m', block=True, method='POST')  # 20 attempts per minute - BLOCKS if exceeded
    @ratelimit(key='ip', rate='60/h', block=True, method='POST')  # 60 attempts per hour - BLOCKS if exceeded
    def wrapper(request, *args, **kwargs):
        # Check if rate limited
        was_limited = getattr(request, 'limited', False)
        if was_limited:
            # Show custom rate limit page instead of 403
            return render(request, 'accounts/rate_limited.html', {
                'message': 'Too many login attempts. Please wait a moment before trying again.',
                'retry_after': 60,
            }, status=429)
        return func(request, *args, **kwargs)
    return wrapper


def rate_limit_payment(func):
    """
    Rate limiter for payment processing
    - 3 attempts per minute per user
    - 20 attempts per hour per user
    """
    @wraps(func)
    @ratelimit(key='user', rate='3/m', block=True, method='POST')
    @ratelimit(key='user', rate='20/h', block=True, method='POST')
    def wrapper(request, *args, **kwargs):
        return func(request, *args, **kwargs)
    return wrapper


def rate_limit_order(func):
    """
    Rate limiter for order placement
    - 10 orders per minute per user
    - 50 orders per hour per user
    """
    @wraps(func)
    @ratelimit(key='user', rate='10/m', block=True, method='POST')
    @ratelimit(key='user', rate='50/h', block=True, method='POST')
    def wrapper(request, *args, **kwargs):
        return func(request, *args, **kwargs)
    return wrapper


def rate_limit_api(func):
    """
    Rate limiter for API endpoints
    - 30 requests per minute per IP
    - 500 requests per hour per IP
    """
    @wraps(func)
    @ratelimit(key='ip', rate='30/m', block=True)
    @ratelimit(key='ip', rate='500/h', block=True)
    def wrapper(request, *args, **kwargs):
        return func(request, *args, **kwargs)
    return wrapper


def rate_limit_registration(func):
    """
    Rate limiter for user registration
    - 3 registrations per hour per IP
    - 10 registrations per day per IP
    """
    @wraps(func)
    @ratelimit(key='ip', rate='3/h', block=True, method='POST')
    @ratelimit(key='ip', rate='10/d', block=True, method='POST')
    def wrapper(request, *args, **kwargs):
        return func(request, *args, **kwargs)
    return wrapper


def rate_limit_password_reset(func):
    """
    Rate limiter for password reset requests
    - 3 attempts per hour per IP
    - 5 attempts per day per IP
    """
    @wraps(func)
    @ratelimit(key='ip', rate='3/h', block=True, method='POST')
    @ratelimit(key='ip', rate='5/d', block=True, method='POST')
    def wrapper(request, *args, **kwargs):
        return func(request, *args, **kwargs)
    return wrapper


def rate_limit_data_export(func):
    """
    Rate limiter for data exports (reports, analytics)
    - 5 exports per minute per user
    - 30 exports per hour per user
    """
    @wraps(func)
    @ratelimit(key='user', rate='5/m', block=True)
    @ratelimit(key='user', rate='30/h', block=True)
    def wrapper(request, *args, **kwargs):
        return func(request, *args, **kwargs)
    return wrapper


def rate_limit_general(func):
    """
    General rate limiter for standard views
    - 60 requests per minute per IP
    - 1000 requests per hour per IP
    """
    @wraps(func)
    @ratelimit(key='ip', rate='60/m', block=True)
    @ratelimit(key='ip', rate='1000/h', block=True)
    def wrapper(request, *args, **kwargs):
        return func(request, *args, **kwargs)
    return wrapper


# Custom rate limit exceeded view
def rate_limited_view(request, exception=None):
    """
    Custom view when rate limit is exceeded
    """
    return render(request, 'accounts/rate_limited.html', {
        'retry_after': getattr(exception, 'retry_after', 60),
    }, status=429)
