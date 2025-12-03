#!/bin/bash

#############################################################################
# PRODUCTION SECURITY FIX SCRIPT
# This script secures your VPS production environment
# Run this on your VPS server: ssh root@72.62.51.225
#############################################################################

set -e  # Exit on any error

echo "🔒 Restaurant System - Production Security Fix"
echo "=============================================="
echo ""

# Configuration
PROJECT_DIR="/var/www/restaurant"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
MANAGE_PY="$PROJECT_DIR/manage.py"

# Check if running on server
if [ ! -d "$PROJECT_DIR" ]; then
    echo "❌ Error: Project directory not found at $PROJECT_DIR"
    echo "   Are you running this on the VPS server?"
    exit 1
fi

cd $PROJECT_DIR

echo "📍 Current directory: $(pwd)"
echo ""

#############################################################################
# STEP 1: Generate secure SECRET_KEY
#############################################################################

echo "🔑 Step 1: Generating secure SECRET_KEY..."

SECRET_KEY=$($PYTHON_BIN -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")

if [ -z "$SECRET_KEY" ]; then
    echo "❌ Failed to generate SECRET_KEY"
    exit 1
fi

echo "✅ Generated secure SECRET_KEY (${#SECRET_KEY} characters)"
echo ""

#############################################################################
# STEP 2: Update or create .env file
#############################################################################

echo "📝 Step 2: Updating .env file..."

# Backup existing .env if it exists
if [ -f .env ]; then
    cp .env .env.backup.$(date +%Y%m%d_%H%M%S)
    echo "✅ Backed up existing .env file"
fi

# Create/update .env file
cat > .env << EOF
# Django Settings (PRODUCTION)
DEBUG=False
SECRET_KEY=$SECRET_KEY
ALLOWED_HOSTS=72.62.51.225,localhost,127.0.0.1

# Database Configuration (PostgreSQL)
DB_NAME=restaurant_db
DB_USER=restaurant_user
DB_PASSWORD=RestaurantPass123
DB_HOST=localhost
DB_PORT=5432

# Redis Configuration
REDIS_URL=redis://localhost:6379/0

# Security Settings (Enable AFTER SSL certificate is installed)
SECURE_SSL_REDIRECT=False
SECURE_HSTS_SECONDS=0

# Email Configuration (optional)
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EOF

echo "✅ Created secure .env file"
echo ""

#############################################################################
# STEP 3: Create production_settings.py
#############################################################################

echo "📄 Step 3: Creating production_settings.py..."

cat > $PROJECT_DIR/restaurant_system/production_settings.py << 'PYEOF'
"""
Production Settings for Restaurant System
Use this on VPS/Live server ONLY
"""

from pathlib import Path
from datetime import timedelta
import os
from decouple import Config, RepositoryEnv

# Load environment variables from .env file
BASE_DIR = Path(__file__).resolve().parent.parent
env_file = BASE_DIR / '.env'
config = Config(RepositoryEnv(env_file)) if env_file.exists() else Config()

# CRITICAL SECURITY SETTINGS
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='72.62.51.225').split(',')

# HTTPS/SSL SECURITY (Enable AFTER SSL certificate)
SECURE_SSL_REDIRECT = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
SESSION_COOKIE_SECURE = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
CSRF_COOKIE_SECURE = config('SECURE_SSL_REDIRECT', default=False, cast=bool)
SECURE_HSTS_SECONDS = config('SECURE_HSTS_SECONDS', default=0, cast=int)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = SECURE_HSTS_SECONDS > 0
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# APPLICATION DEFINITION
INSTALLED_APPS = [
    'daphne',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'rest_framework',
    'rest_framework.authtoken',
    'axes',
    'corsheaders',
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
    'corsheaders.middleware.CorsMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'restaurant_system.session_timeout_middleware.SessionTimeoutMiddleware',  # ✅ ENABLED
    'subscription_middleware.SubscriptionAccessMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'axes.middleware.AxesMiddleware',
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
ASGI_APPLICATION = 'restaurant_system.asgi.application'

# DATABASE - PostgreSQL
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME', default='restaurant_db'),
        'USER': config('DB_USER', default='restaurant_user'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST', default='localhost'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# PASSWORD VALIDATION
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# INTERNATIONALIZATION
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Nairobi'
USE_I18N = True
USE_TZ = True

# STATIC & MEDIA FILES
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = [BASE_DIR / 'static']
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

# CUSTOM USER MODEL
AUTH_USER_MODEL = 'accounts.User'
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# LOGIN URLS
LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# SECURITY HEADERS
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
SECURE_REFERRER_POLICY = 'strict-origin-when-cross-origin'
CROSS_ORIGIN_OPENER_POLICY = 'same-origin'
CROSS_ORIGIN_EMBEDDER_POLICY = 'require-corp'

# CSRF & SESSION
CSRF_COOKIE_HTTPONLY = False
CSRF_TRUSTED_ORIGINS = [
    'http://72.62.51.225',
    'http://localhost:8000',
]
SESSION_COOKIE_AGE = 900
SESSION_SAVE_EVERY_REQUEST = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = 'Lax'
SESSION_COOKIE_NAME = 'restaurant_session'

# CHANNELS (WebSocket)
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        'CONFIG': {'hosts': [('127.0.0.1', 6379)]},
    },
}

# DJANGO-AXES (Brute Force Protection)
AUTHENTICATION_BACKENDS = [
    'axes.backends.AxesStandaloneBackend',
    'django.contrib.auth.backends.ModelBackend',
]
AXES_ENABLED = True
AXES_FAILURE_LIMIT = 10
AXES_COOLOFF_TIME = timedelta(minutes=30)
AXES_LOCKOUT_PARAMETERS = [["username", "ip_address"]]
AXES_RESET_ON_SUCCESS = True
AXES_LOCKOUT_TEMPLATE = 'accounts/account_locked.html'
AXES_VERBOSE = True
AXES_ENABLE_ACCESS_FAILURE_LOG = True
AXES_IPWARE_PROXY_COUNT = 1
AXES_IPWARE_META_PRECEDENCE_ORDER = ['HTTP_X_FORWARDED_FOR', 'HTTP_X_REAL_IP', 'REMOTE_ADDR']

# CACHING
CACHES = {
    'default': {
        'BACKEND': 'django_redis.cache.RedisCache',
        'LOCATION': 'redis://127.0.0.1:6379/1',
        'OPTIONS': {'CLIENT_CLASS': 'django_redis.client.DefaultClient'},
        'TIMEOUT': 300,
    }
}

# RATE LIMITING
RATELIMIT_ENABLE = True
RATELIMIT_USE_CACHE = 'default'

# CORS
CORS_ALLOWED_ORIGINS = ['http://72.62.51.225', 'http://localhost:8000']
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_HEADERS = ['accept', 'authorization', 'content-type', 'x-csrftoken', 'x-requested-with']

# PASSWORD HASHERS
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
]

# DATA UPLOAD SECURITY
DATA_UPLOAD_MAX_MEMORY_SIZE = 10485760
FILE_UPLOAD_MAX_MEMORY_SIZE = 10485760

# LOGGING
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {'verbose': {'format': '[{levelname}] {asctime} {message}', 'style': '{'}},
    'handlers': {
        'console': {'level': 'WARNING', 'class': 'logging.StreamHandler', 'formatter': 'verbose'},
        'file': {'level': 'WARNING', 'class': 'logging.FileHandler', 'filename': BASE_DIR / 'logs' / 'security.log', 'formatter': 'verbose'},
    },
    'loggers': {
        'django.security': {'handlers': ['console', 'file'], 'level': 'WARNING', 'propagate': False},
        'axes': {'handlers': ['console', 'file'], 'level': 'WARNING', 'propagate': False},
    },
}

os.makedirs(BASE_DIR / 'logs', exist_ok=True)

# REST FRAMEWORK
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.TokenAuthentication',
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
}

# PRINT QUEUE
USE_PRINT_QUEUE = True

print(f"✅ Production settings loaded - DEBUG={DEBUG}, DB={DATABASES['default']['NAME']}")
PYEOF

echo "✅ Created production_settings.py"
echo ""

#############################################################################
# STEP 4: Install python-decouple (if not installed)
#############################################################################

echo "📦 Step 4: Installing python-decouple..."

source $PROJECT_DIR/venv/bin/activate
pip install python-decouple --quiet

echo "✅ Installed python-decouple"
echo ""

#############################################################################
# STEP 5: Test production settings
#############################################################################

echo "🧪 Step 5: Testing production settings..."

export DJANGO_SETTINGS_MODULE=restaurant_system.production_settings

# Test settings load
if $PYTHON_BIN -c "import django; django.setup(); from django.conf import settings; print(f'DEBUG={settings.DEBUG}')"; then
    echo "✅ Production settings loaded successfully"
else
    echo "❌ Error loading production settings"
    exit 1
fi

# Run deployment checks
echo ""
echo "Running security checks..."
$PYTHON_BIN $MANAGE_PY check --deploy --settings=restaurant_system.production_settings || true

echo ""

#############################################################################
# STEP 6: Update systemd services
#############################################################################

echo "🔄 Step 6: Updating systemd services..."

# Update Gunicorn service
sudo tee /etc/systemd/system/restaurant-gunicorn.service > /dev/null << 'EOF'
[Unit]
Description=Restaurant System Gunicorn
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/restaurant
Environment="PATH=/var/www/restaurant/venv/bin"
Environment="DJANGO_SETTINGS_MODULE=restaurant_system.production_settings"
ExecStart=/var/www/restaurant/venv/bin/gunicorn --workers 3 --bind unix:/var/www/restaurant/restaurant.sock restaurant_system.wsgi:application

[Install]
WantedBy=multi-user.target
EOF

# Update Daphne service (if exists)
if systemctl list-unit-files | grep -q restaurant-daphne; then
    sudo tee /etc/systemd/system/restaurant-daphne.service > /dev/null << 'EOF'
[Unit]
Description=Restaurant System Daphne (WebSocket)
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/restaurant
Environment="PATH=/var/www/restaurant/venv/bin"
Environment="DJANGO_SETTINGS_MODULE=restaurant_system.production_settings"
ExecStart=/var/www/restaurant/venv/bin/daphne -b 0.0.0.0 -p 8001 restaurant_system.asgi:application

[Install]
WantedBy=multi-user.target
EOF
fi

sudo systemctl daemon-reload

echo "✅ Updated systemd services"
echo ""

#############################################################################
# STEP 7: Restart services
#############################################################################

echo "🔄 Step 7: Restarting services..."

sudo systemctl restart restaurant-gunicorn
if systemctl list-unit-files | grep -q restaurant-daphne; then
    sudo systemctl restart restaurant-daphne
fi
sudo systemctl restart nginx

echo "✅ Services restarted"
echo ""

#############################################################################
# STEP 8: Verify services
#############################################################################

echo "✅ Step 8: Verifying services..."

sleep 3

if systemctl is-active --quiet restaurant-gunicorn; then
    echo "✅ Gunicorn is running"
else
    echo "❌ Gunicorn failed to start"
    sudo journalctl -u restaurant-gunicorn -n 20
fi

if systemctl list-unit-files | grep -q restaurant-daphne; then
    if systemctl is-active --quiet restaurant-daphne; then
        echo "✅ Daphne is running"
    else
        echo "❌ Daphne failed to start"
    fi
fi

if systemctl is-active --quiet nginx; then
    echo "✅ Nginx is running"
else
    echo "❌ Nginx failed to start"
fi

echo ""

#############################################################################
# FINAL SUMMARY
#############################################################################

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ PRODUCTION SECURITY FIX COMPLETED!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ Security improvements applied:"
echo "   • DEBUG = False (secure)"
echo "   • Secure SECRET_KEY generated"
echo "   • Session timeout enabled (15 min)"
echo "   • Production settings created"
echo "   • Services updated and restarted"
echo ""
echo "⚠️  HTTPS/SSL not yet enabled (requires SSL certificate)"
echo "   To enable SSL:"
echo "   1. Install certificate: sudo certbot --nginx -d yourdomain.com"
echo "   2. Update .env: SECURE_SSL_REDIRECT=True"
echo "   3. Restart services: sudo systemctl restart restaurant-gunicorn nginx"
echo ""
echo "🌐 Test your site:"
echo "   http://72.62.51.225"
echo ""
echo "📝 Files created/updated:"
echo "   • .env (secure environment variables)"
echo "   • restaurant_system/production_settings.py"
echo "   • /etc/systemd/system/restaurant-gunicorn.service"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
