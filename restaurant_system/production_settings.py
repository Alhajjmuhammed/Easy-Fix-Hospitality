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

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = config('SECRET_KEY', default='django-insecure-change-this-in-production')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

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
DATABASES = {
    'default': {
        'ENGINE': config('DATABASE_ENGINE', default='django.db.backends.postgresql'),
        'NAME': config('DB_NAME', default='restaurant_db'),
        'USER': config('DB_USER', default='restaurant_user'),
        'PASSWORD': config('DB_PASSWORD', default='password'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
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

# Redis configuration for production
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {
            'hosts': [(
                config('REDIS_HOST', default='127.0.0.1'),
                config('REDIS_PORT', default=6379, cast=int)
            )],
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
USE_HTTPS = config('USE_HTTPS', default=False, cast=bool)

# CSRF Settings
CSRF_COOKIE_HTTPONLY = False  # Allow JavaScript to read CSRF token
CSRF_COOKIE_SECURE = USE_HTTPS  # Automatically set based on HTTPS
CSRF_COOKIE_SAMESITE = 'Lax'  # Allow cookies in same-site context
CSRF_COOKIE_NAME = 'csrftoken'  # Default name
CSRF_USE_SESSIONS = False  # Store CSRF token in cookie, not session
CSRF_TRUSTED_ORIGINS = [
    'https://easyfixsoft.com',
    'https://www.easyfixsoft.com',
    'http://easyfixsoft.com',
    'http://www.easyfixsoft.com',
    'https://hospitality.easyfixsoft.com',
    'http://hospitality.easyfixsoft.com',
    'https://www.hospitality.easyfixsoft.com',
    'http://www.hospitality.easyfixsoft.com',
    'http://72.62.51.225',
    'https://72.62.51.225',
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]

# Session Configuration
SESSION_COOKIE_SECURE = USE_HTTPS  # Automatically set based on HTTPS
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# HTTPS Settings - SSL is configured with nginx reverse proxy
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
# SECURE_SSL_REDIRECT = True  # Let nginx handle SSL redirect

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
        'restaurant': {
            'handlers': ['file', 'console'],
            'level': 'INFO',
            'propagate': False,
        },
    },
}

# Create logs directory if it doesn't exist
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

# Custom Security Headers Middleware Class
class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Add security headers - Allow CDN resources
        response['Cross-Origin-Opener-Policy'] = 'same-origin-allow-popups'
        response['Cross-Origin-Embedder-Policy'] = 'unsafe-none'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
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
RATELIMIT_IP_META_KEY = 'HTTP_X_FORWARDED_FOR'  # Get real IP from nginx proxy

# Redis Cache for Production (Required)
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {
            'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            'PASSWORD': config('REDIS_PASSWORD', default=''),
            'SOCKET_CONNECT_TIMEOUT': 5,
            'SOCKET_TIMEOUT': 5,
            'RETRY_ON_TIMEOUT': True,
            'MAX_CONNECTIONS': 50,
        },
        'KEY_PREFIX': 'restaurant',
        'TIMEOUT': 300,
    }
}

# CORS Configuration for Production
CORS_ALLOWED_ORIGINS = config(
    'CORS_ALLOWED_ORIGINS',
    default='https://easyfixsoft.com,https://www.easyfixsoft.com',
    cast=Csv()
)
CORS_ALLOW_CREDENTIALS = True

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
SECURE_SSL_REDIRECT = False  # Let nginx handle SSL redirect

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
}

# ============================================================================
# Print Queue Configuration
# ============================================================================
# Set to True for hosted/remote printing (uses print queue + print client)
# Set to False for local direct printing (uses win32print directly)
USE_PRINT_QUEUE = True  # ENABLED for production - uses print queue

print("✅ Production settings loaded successfully")
# Enhanced Logging for Production
