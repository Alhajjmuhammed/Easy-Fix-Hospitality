"""
Production settings for Restaurant Ordering System
This file will be used when deploying to production server
"""

from pathlib import Path
from datetime import timedelta
import os
from decouple import config, Csv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY: Secret key MUST be set via environment variable
# Generate with: python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
SECRET_KEY = config('SECRET_KEY')  # No default - MUST be configured

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=False, cast=bool)

# Allowed hosts - include all domains that can access this site
ALLOWED_HOSTS = [
    'hospitality.easyfixsoft.com',
    'www.hospitality.easyfixsoft.com',
    '72.62.51.225',
    'localhost',
    '127.0.0.1',
]

# Application definition
INSTALLED_APPS = [
    'daphne',  # Add this for Channels ASGI support
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',  # Add Channels
    'rest_framework',  # Django REST Framework for print API
    'rest_framework.authtoken',  # Token authentication for print clients
    'axes',  # Django-axes for failed login tracking
    'corsheaders',  # CORS headers
    'accounts',
    'restaurant',
    'orders',
    'admin_panel',
    'system_admin',
    'cashier',
    'waste_management',
    'reports',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # CORS - must be before CommonMiddleware
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',  # Enabled for production
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'restaurant_system.session_timeout_middleware.SessionTimeoutMiddleware',  # Auto-logout after 15 min inactivity
    'subscription_middleware.SubscriptionAccessMiddleware',  # SaaS subscription control
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'axes.middleware.AxesMiddleware',  # Django-axes for failed login tracking
]

ROOT_URLCONF = 'restaurant_system.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'restaurant_system.wsgi.application'

# Database - Use environment variables for production
# SSL mode enforced for secure database connections
DB_SSL_MODE = config('DB_SSL_MODE', default='require')  # Options: disable, allow, prefer, require, verify-ca, verify-full

# Warn if SSL is disabled in production
if DB_SSL_MODE == 'disable' and not DEBUG:
    import sys
    sys.stderr.write("⚠️  WARNING: DB_SSL_MODE is disabled. Enable SSL for production database security.\n")

DATABASES = {
    'default': {
        'ENGINE': config('DATABASE_ENGINE', default='django.db.backends.postgresql'),
        'NAME': config('DB_NAME'),  # No default - MUST be configured
        'USER': config('DB_USER'),  # No default - MUST be configured
        'PASSWORD': config('DB_PASSWORD'),  # No default - MUST be configured
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
        'CONN_MAX_AGE': 60,  # Keep database connections alive for 60 seconds
        'CONN_HEALTH_CHECKS': True,  # Verify connections before use (Django 4.1+)
        'OPTIONS': {
            'connect_timeout': 10,
            'sslmode': DB_SSL_MODE,  # Enforce SSL connection
        },
        'ATOMIC_REQUESTS': True,  # Wrap each request in transaction
    }
}

# Password validation
AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

# Internationalization
LANGUAGE_CODE = 'en-us'

# Set to East Africa Standard Time (UTC+3) for consistent local/production behavior
TIME_ZONE = 'Africa/Nairobi'  # East Africa Standard Time (UTC+3)

USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [
    BASE_DIR / 'static',
]

# Media files
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# Default primary key field type
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Custom user model
AUTH_USER_MODEL = 'accounts.User'

# Login URLs
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# Channels Configuration for WebSockets
ASGI_APPLICATION = 'restaurant_system.asgi.application'

# Redis configuration for production with authentication
REDIS_HOST = config('REDIS_HOST', default='127.0.0.1')
REDIS_PORT = config('REDIS_PORT', default=6379, cast=int)
REDIS_PASSWORD_CHANNELS = config('REDIS_PASSWORD', default='')

CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [{
                'address': (REDIS_HOST, REDIS_PORT),
                'password': REDIS_PASSWORD_CHANNELS if REDIS_PASSWORD_CHANNELS else None,
            }],
            'capacity': 1500,
            'expiry': 10,
        },
    },
}

# Security Settings for Production
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'SAMEORIGIN'  # Allow iframes from same origin

# Cross-Origin Policies - Relaxed to allow CDN resources
CROSS_ORIGIN_OPENER_POLICY = 'same-origin-allow-popups'
CROSS_ORIGIN_EMBEDDER_POLICY = 'unsafe-none'  # Allow external CDN resources

# SSL/HTTPS Detection - Read from environment
# Default to True in production - should always use HTTPS
USE_HTTPS = config('USE_HTTPS', default=True, cast=bool)

# CSRF Settings
CSRF_COOKIE_HTTPONLY = False  # Allow JavaScript to read CSRF token
CSRF_COOKIE_SECURE = USE_HTTPS  # Automatically set based on HTTPS
CSRF_COOKIE_SAMESITE = 'Lax'  # Allow cookies in same-site context
CSRF_COOKIE_NAME = 'csrftoken'  # Default name
CSRF_USE_SESSIONS = False  # Store CSRF token in cookie, not session
# CSRF Trusted Origins - HTTPS only for production security
CSRF_TRUSTED_ORIGINS = [
    'https://easyfixsoft.com',
    'https://www.easyfixsoft.com',
    'https://hospitality.easyfixsoft.com',
    'https://www.hospitality.easyfixsoft.com',
    'https://72.62.51.225',
    # Development origins - remove in strict production
    # 'http://localhost:8000',
    # 'http://127.0.0.1:8000',
]

# Session Configuration
SESSION_COOKIE_SECURE = USE_HTTPS  # Automatically set based on HTTPS
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# HTTPS Settings - SSL is configured with nginx reverse proxy
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Logging Configuration
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '{levelname} {asctime} {module} {message}',
            'style': '{',
        },
    },
    'handlers': {
        'file': {
            'level': 'INFO',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'django.log',
            'formatter': 'verbose',
        },
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': True,
        },
        'django.security': {
            'handlers': ['file', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'axes': {
            'handlers': ['file', 'console'],
            'level': 'WARNING',
            'propagate': False,
        },
        'restaurant': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Create logs directory if it doesn't exist
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

# Custom Security Headers Middleware Class with CSP Enforcement
class SecurityHeadersMiddleware:
    """
    Production security headers middleware.
    Enforces CSP, security headers, and other protections.
    """
    
    # Content Security Policy directives
    # Note: 'unsafe-inline' needed for inline scripts/styles until nonce implementation
    CSP_DIRECTIVES = {
        'default-src': ["'self'"],
        'script-src': ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com"],
        'style-src': ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://fonts.googleapis.com"],
        'font-src': ["'self'", "https://fonts.gstatic.com", "https://cdnjs.cloudflare.com"],
        'img-src': ["'self'", "data:", "https:", "blob:"],
        'connect-src': ["'self'", "wss:", "https:"],
        'frame-ancestors': ["'self'"],
        'base-uri': ["'self'"],
        'form-action': ["'self'"],
        'object-src': ["'none'"],
        'upgrade-insecure-requests': [],
    }
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Skip CSP for admin pages (they need inline styles/scripts)
        if request.path.startswith('/secure-management-portal/'):
            return response
        
        # Build CSP header
        csp_parts = []
        for directive, sources in self.CSP_DIRECTIVES.items():
            if sources:
                csp_parts.append(f"{directive} {' '.join(sources)}")
            else:
                csp_parts.append(directive)
        
        csp_header = '; '.join(csp_parts)
        
        # Add security headers
        response['Content-Security-Policy'] = csp_header
        response['X-Content-Type-Options'] = 'nosniff'
        response['X-Frame-Options'] = 'SAMEORIGIN'
        response['X-XSS-Protection'] = '1; mode=block'
        response['Cross-Origin-Opener-Policy'] = 'same-origin-allow-popups'
        response['Cross-Origin-Embedder-Policy'] = 'unsafe-none'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=(), payment=()'
        response['X-DNS-Prefetch-Control'] = 'off'
        # Prevent search engines from indexing sensitive admin/system pages
        response['X-Robots-Tag'] = 'noindex, nofollow'
        
        # Remove server identification headers
        if 'Server' in response:
            del response['Server']
        
        return response

# Add custom middleware to the middleware stack
MIDDLEWARE.insert(1, 'restaurant_system.production_settings.SecurityHeadersMiddleware')

# ============================================================================
# PRODUCTION SECURITY CONFIGURATION
# ============================================================================

# Django-Axes Configuration (Failed Login Tracking)
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Axes Settings - Production-Ready Configuration for Enterprise Use
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 10  # Allow 10 failed attempts before lockout (reasonable for busy restaurants)
AXES_COOLOFF_TIME = timedelta(minutes=30)  # 30-minute cooldown (not too long, not too short)
AXES_LOCKOUT_PARAMETERS = ["username"]  # Lock by username only (simpler and more reliable)
AXES_RESET_ON_SUCCESS = True  # Reset counter on successful login
AXES_LOCKOUT_TEMPLATE = 'accounts/account_locked.html'  # Custom lockout page
AXES_LOCKOUT_URL = None  # Use template instead of redirect
AXES_VERBOSE = True  # Log all attempts for security audit
AXES_ENABLE_ACCESS_FAILURE_LOG = True  # Store in database for analysis

# IP detection for nginx reverse proxy
AXES_PROXY_COUNT = 1  # We have 1 proxy (nginx)
AXES_META_PRECEDENCE_ORDER = [
    'HTTP_X_FORWARDED_FOR',
    'HTTP_X_REAL_IP', 
    'REMOTE_ADDR',
]

AXES_IP_BLACKLIST = []  # Can add known malicious IPs
AXES_IP_WHITELIST = []  # Can add trusted IPs (e.g., admin office, staff networks)

# Rate Limiting Configuration
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = 'default'
# Use X-Real-IP header which nginx sets, fallback to X-Forwarded-For
RATELIMIT_IP_META_KEY = 'HTTP_X_REAL_IP'

# Redis Cache for Production (Required)
# IMPORTANT: REDIS_PASSWORD should be set in environment for security
REDIS_PASSWORD = config('REDIS_PASSWORD', default='')

# Only warn about Redis password when running server (not during imports/tests)
# Check for runserver, gunicorn, daphne, or uvicorn in sys.argv
import sys
_is_server_running = any(cmd in sys.argv[0] for cmd in ['manage.py', 'gunicorn', 'daphne', 'uvicorn']) and \
                     any(arg in sys.argv for arg in ['runserver', 'run', 'gunicorn', 'daphne', 'uvicorn'])

if not REDIS_PASSWORD and not DEBUG and _is_server_running:
    sys.stderr.write("WARNING: REDIS_PASSWORD not set. Strongly recommended for production security.\n")

# Build Redis URL with password if set
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/1" if REDIS_PASSWORD else f"redis://{REDIS_HOST}:{REDIS_PORT}/1"

CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': REDIS_URL,
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
            'RETRY_ON_TIMEOUT': True,
            'MAX_CONNECTIONS': 50,
            'CONNECTION_POOL_KWARGS': {'max_connections': 50},
            'IGNORE_EXCEPTIONS': True,  # Graceful degradation if Redis down
        },
        'KEY_PREFIX': 'restaurant',
        'TIMEOUT': 300,
    }
}

# Use Redis for session storage in production
SESSION_ENGINE = 'django.contrib.sessions.backends.cache'
SESSION_CACHE_ALIAS = 'default'

# CORS Configuration for Production
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='https://easyfixsoft.com,https://www.easyfixsoft.com,https://hospitality.easyfixsoft.com,https://www.hospitality.easyfixsoft.com',
    cast=Csv()
)
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_METHODS = [
    'GET',
    'POST',
    'PUT',
    'PATCH',
    'DELETE',
    'OPTIONS',
]
CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

# Content Security Policy - Stricter for production
CSP_DEFAULT_SRC = ["'self'"]
CSP_SCRIPT_SRC = ["'self'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com"]
CSP_STYLE_SRC = ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://fonts.googleapis.com"]
CSP_FONT_SRC = ["'self'", "https://fonts.gstatic.com"]
CSP_IMG_SRC = ["'self'", "data:", "https:"]
CSP_CONNECT_SRC = ["'self'", "wss:", "https:"]

# Password Hashers - Use Argon2 for production
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
]

# Session Security - Stricter for production
SESSION_COOKIE_AGE = 900  # 15 minutes (900 seconds) - Auto logout after inactivity
SESSION_SAVE_EVERY_REQUEST = True  # Update expiry time on every request
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # Honor timeout instead of browser close
SESSION_COOKIE_NAME = 'restaurant_prod_session'

# Enhanced Security Headers for Production
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_HSTS_SECONDS = 31536000  # 1 year
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
# SSL redirect as defense-in-depth (nginx also handles this)
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=True, cast=bool)

# Data Upload Limits
DATA_UPLOAD_MAX_MEMORY_SIZE = 5242880  # 5 MB (stricter than dev)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5242880
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000

# ============================================================================
# REST Framework Configuration (for Print Client API)
# ============================================================================
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 100,
    'DEFAULT_RENDERER_CLASSES': [
        'rest_framework.renderers.JSONRenderer',
    ],
    # Rate limiting to protect against abuse
    'DEFAULT_THROTTLE_CLASSES': [
        'rest_framework.throttling.AnonRateThrottle',
        'rest_framework.throttling.UserRateThrottle',
    ],
    'DEFAULT_THROTTLE_RATES': {
        'anon': '100/minute',   # Anonymous users: 100 requests/minute
        'user': '1000/minute',  # Authenticated users: 1000 requests/minute (PrintClient uses ~12/min)
    },
}

# ============================================================================
# Print Queue Configuration
# ============================================================================
# Set to True for hosted/remote printing (uses print queue + print client)
# Set to False for local direct printing (uses win32print directly)
USE_PRINT_QUEUE = True  # ENABLED for production - uses print queue

import logging
_logger = logging.getLogger(__name__)
_logger.info("Production settings loaded successfully")
# Enhanced Logging for Production
