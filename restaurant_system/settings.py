"""
Django settings for restaurant_system project.
"""

from pathlib import Path
from datetime import timedelta
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = 'django-insecure-your-secret-key-here'

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = True

ALLOWED_HOSTS = ['*', 'testserver', '127.0.0.1', 'localhost']

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
    'django.middleware.csrf.CsrfViewMiddleware',  # Re-enabled for security
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'restaurant_system.session_timeout_middleware.SessionTimeoutMiddleware',  # ✅ Auto-logout after 15 min inactivity - RE-ENABLED
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

# Database
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
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
# This matches your system timezone for proper Happy Hour functionality
TIME_ZONE = 'Africa/Nairobi'  # East Africa Standard Time (UTC+3)

USE_I18N = True
USE_TZ = True

# Static files (CSS, JavaScript, Images)
STATIC_URL = '/static/'
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

# Channels Configuration for WebSockets
ASGI_APPLICATION = 'restaurant_system.asgi.application'

# Security Headers Configuration
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'SAMEORIGIN'  # Allow iframes from same origin

# Cross-Origin Policies
CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
CROSS_ORIGIN_EMBEDDER_POLICY = 'require-corp'

# CSRF Configuration for development
CSRF_COOKIE_HTTPONLY = False  # Allow JavaScript access for AJAX
CSRF_COOKIE_SECURE = False    # Set to True in production with HTTPS
CSRF_TRUSTED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
    'http://0.0.0.0:8000',
]

# Session Configuration
SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'

# Automatic Session Timeout (Inactivity Logout)
SESSION_COOKIE_AGE = 900  # 15 minutes (900 seconds)
SESSION_SAVE_EVERY_REQUEST = True  # Update last activity on every request
SESSION_EXPIRE_AT_BROWSER_CLOSE = False  # Don't expire when browser closes (honor timeout instead)

# Try Redis first, fall back to in-memory channels for development
try:
    import redis
    # Test Redis connection
    r = redis.Redis(host='127.0.0.1', port=6379, db=0)
    r.ping()
    # Redis is available
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels_redis.core.RedisChannelLayer',
            'CONFIG': {
                'hosts': [('127.0.0.1', 6379)],
            },
        },
    }
    print("Success: Using Redis for WebSocket channels")
except (ImportError, redis.ConnectionError, redis.ResponseError):
    # Redis not available, use in-memory channels (development only)
    CHANNEL_LAYERS = {
        'default': {
            'BACKEND': 'channels.layers.InMemoryChannelLayer',
        },
    }
    print("Warning: Using in-memory channels (development only) - Install and start Redis for production")
LOGOUT_REDIRECT_URL = '/'

# Custom Security Headers Middleware Class
class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Add security headers
        response['Cross-Origin-Opener-Policy'] = 'same-origin'
        response['Cross-Origin-Embedder-Policy'] = 'require-corp'
        response['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
        
        return response

# Add custom middleware to the middleware stack
MIDDLEWARE.insert(1, 'restaurant_system.settings.SecurityHeadersMiddleware')

# ============================================================================
# SECURITY CONFIGURATION
# ============================================================================

# Django-Axes Configuration (Failed Login Tracking)
# Protects against brute force attacks
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',  # AxesStandaloneBackend should be first
    'django.contrib.auth.backends.ModelBackend',
]

# Axes Settings - Production-Ready Configuration for Enterprise Use
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 10  # Allow 10 failed attempts before lockout (reasonable for busy restaurants)
AXES_COOLOFF_TIME = timedelta(minutes=30)  # 30-minute cooldown (not too long, not too short)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]  # Lock by username + IP combination
AXES_RESET_ON_SUCCESS = True  # Reset failed attempts counter on successful login
AXES_LOCKOUT_TEMPLATE = 'accounts/account_locked.html'  # Custom lockout template
AXES_LOCKOUT_URL = None  # Use template instead of redirect
AXES_VERBOSE = True  # Log all attempts for security audit
AXES_ENABLE_ACCESS_FAILURE_LOG = True  # Store in database for analysis
AXES_IPWARE_PROXY_COUNT = 1  # Handle proxy/load balancer correctly
AXES_IPWARE_META_PRECEDENCE_ORDER = [  # Get real IP behind proxy/load balancer
    'HTTP_X_FORWARDED_FOR',
    'HTTP_X_REAL_IP',
    'REMOTE_ADDR',
]

# Rate Limiting Configuration (django-ratelimit)
# Default rate limits for the entire application
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = 'default'  # Use default cache backend
RATELIMIT_VIEW = 'restaurant_system.views.rate_limited'  # Custom rate limit exceeded view

# Cache Configuration for Rate Limiting
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'unique-snowflake',
        'TIMEOUT': 300,
        'OPTIONS': {
            'MAX_ENTRIES': 1000
        }
    }
}

# Try to use Redis for caching if available
try:
    import redis
    r = redis.Redis(host='127.0.0.1', port=6379, db=1)
    r.ping()
    CACHES = {
        'default': {
            'BACKEND': 'django_redis.cache.RedisCache',
            'LOCATION': 'redis://127.0.0.1:6379/1',
            'OPTIONS': {
                'CLIENT_CLASS': 'django_redis.client.DefaultClient',
            }
        }
    }
    print("Success: Using Redis for caching and rate limiting")
except:
    print("Warning: Using in-memory cache - Redis recommended for production")

# CORS Configuration
CORS_ALLOWED_ORIGINS = [
    'http://localhost:8000',
    'http://127.0.0.1:8000',
]
CORS_ALLOW_CREDENTIALS = True
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

# Content Security Policy (CSP)
# Add these headers via SecurityHeadersMiddleware
CSP_DEFAULT_SRC = ["'self'"]
CSP_SCRIPT_SRC = ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com"]
CSP_STYLE_SRC = ["'self'", "'unsafe-inline'", "https://cdn.jsdelivr.net", "https://cdnjs.cloudflare.com", "https://fonts.googleapis.com"]
CSP_FONT_SRC = ["'self'", "https://fonts.gstatic.com", "https://cdnjs.cloudflare.com"]
CSP_IMG_SRC = ["'self'", "data:", "https:"]
CSP_CONNECT_SRC = ["'self'", "ws:", "wss:"]

# Password Strength Configuration
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',  # Most secure
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
    'django.contrib.auth.hashers.BCryptSHA256PasswordHasher',
]

# Session Security Configuration
# IMPORTANT: Automatic logout after 15 minutes of inactivity
# How it works:
# - User logs in → Session starts (15 min timer)
# - User clicks/navigates → Timer resets to 15 min
# - User idle for 15 min → Automatically logged out
# - On next action → Redirected to login page
SESSION_COOKIE_AGE = 900  # Already set above (15 minutes)
SESSION_SAVE_EVERY_REQUEST = True  # Already set above (resets timer on activity)
SESSION_COOKIE_NAME = 'restaurant_session'

# Additional Security Headers
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
SECURE_HSTS_SECONDS = 0  # Set to 31536000 (1 year) in production with HTTPS
SECURE_HSTS_INCLUDE_SUBDOMAINS = False  # Set to True in production
SECURE_HSTS_PRELOAD = False  # Set to True in production

# Data Upload Security
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10 MB max upload size
FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760  # 10 MB max file upload size
DATA_UPLOAD_MAX_NUMBER_FIELDS = 1000  # Prevent memory exhaustion

# Logging Configuration for Security Events
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module} {message}',
            'style': '{',
        },
        'simple': {
            'format': '{levelname} {message}',
            'style': '{',
        },
    },
    'filters': {
        'require_debug_false': {
            '()': 'django.utils.log.RequireDebugFalse',
        },
        'require_debug_true': {
            '()': 'django.utils.log.RequireDebugTrue',
        },
    },
    'handlers': {
        'console': {
            'level': 'INFO',
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
        'file': {
            'level': 'WARNING',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'security.log',
            'formatter': 'verbose',
        },
        'axes_file': {
            'level': 'WARNING',
            'class': 'logging.FileHandler',
            'filename': BASE_DIR / 'logs' / 'axes.log',
            'formatter': 'verbose',
        },
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': 'INFO',
        },
        'django.security': {
            'handlers': ['console', 'file'],
            'level': 'WARNING',
            'propagate': False,
        },
        'axes': {
            'handlers': ['console', 'axes_file'],
            'level': 'WARNING',
            'propagate': False,
        },
    },
}

# Create logs directory if it doesn't exist
import os
os.makedirs(BASE_DIR / 'logs', exist_ok=True)

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
USE_PRINT_QUEUE = False  # DISABLED for local development - direct printing

print("Success: Security configuration loaded")
