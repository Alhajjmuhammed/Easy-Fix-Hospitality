#!/bin/bash

# 🚀 Restaurant Ordering System - Automated Deployment Script
# For Ubuntu 24.04 LTS
# Author: Deployment Assistant
# Date: October 2025

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
PROJECT_NAME="restaurant"
PROJECT_DIR="/var/www/$PROJECT_NAME"
GITHUB_REPO="https://github.com/Alhajjmuhammed/Easy-Fix-Hospitality.git"
DB_NAME="restaurant_db"
DB_USER="restaurant_user"
DB_PASSWORD="RestaurantSecure2024!"
SERVER_IP="72.62.51.225"

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

# Function to check if command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

echo -e "${GREEN}"
cat << "EOF"
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║     🍽️  RESTAURANT ORDERING SYSTEM DEPLOYMENT 🍽️       ║
║                                                          ║
║          Automated Installation Script                  ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
EOF
echo -e "${NC}"

sleep 2

# Step 1: Update system
print_status "Step 1/12: Updating Ubuntu system..."
apt update -y && apt upgrade -y
print_success "System updated successfully!"

# Step 2: Install required packages
print_status "Step 2/12: Installing required software (Python, PostgreSQL, Nginx, Redis)..."
apt install -y python3 python3-pip python3-venv python3-dev \
    postgresql postgresql-contrib libpq-dev \
    nginx \
    redis-server \
    git \
    curl \
    build-essential

print_success "All required software installed!"

# Step 3: Create project directory
print_status "Step 3/12: Creating project directory..."
mkdir -p $PROJECT_DIR
cd $PROJECT_DIR
print_success "Project directory created at $PROJECT_DIR"

# Step 4: Clone repository
print_status "Step 4/12: Downloading project from GitHub..."
if [ -d ".git" ]; then
    print_warning "Git repository already exists. Pulling latest changes..."
    git pull origin main
else
    git clone $GITHUB_REPO .
fi
print_success "Project downloaded successfully!"

# Step 5: Create virtual environment
print_status "Step 5/12: Setting up Python virtual environment..."
python3 -m venv venv
source venv/bin/activate
print_success "Virtual environment created!"

# Step 6: Install Python dependencies
print_status "Step 6/12: Installing Python packages (this may take a few minutes)..."
pip install --upgrade pip
pip install -r requirements.txt
pip install gunicorn psycopg2-binary python-decouple
print_success "Python packages installed!"

# Step 7: Set up PostgreSQL database
print_status "Step 7/12: Setting up PostgreSQL database..."
sudo -u postgres psql << EOF
-- Drop database if exists (for fresh install)
DROP DATABASE IF EXISTS $DB_NAME;
DROP USER IF EXISTS $DB_USER;

-- Create database and user
CREATE DATABASE $DB_NAME;
CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
ALTER ROLE $DB_USER SET client_encoding TO 'utf8';
ALTER ROLE $DB_USER SET default_transaction_isolation TO 'read committed';
ALTER ROLE $DB_USER SET timezone TO 'UTC+3';
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;

-- Grant additional permissions (PostgreSQL 15+)
\c $DB_NAME
GRANT ALL ON SCHEMA public TO $DB_USER;
EOF

print_success "Database created and configured!"

# Step 8: Create production settings file
print_status "Step 8/12: Creating production configuration..."

# Generate a random secret key
SECRET_KEY=$(python3 -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())")

cat > $PROJECT_DIR/.env << EOF
# Django Settings
SECRET_KEY=$SECRET_KEY
DEBUG=False
ALLOWED_HOSTS=$SERVER_IP,localhost,127.0.0.1

# Database Settings
DATABASE_ENGINE=django.db.backends.postgresql
DATABASE_NAME=$DB_NAME
DATABASE_USER=$DB_USER
DATABASE_PASSWORD=$DB_PASSWORD
DATABASE_HOST=localhost
DATABASE_PORT=5432

# Redis Settings
REDIS_HOST=localhost
REDIS_PORT=6379
EOF

print_success "Environment configuration created!"

# Step 9: Update Django settings for production
print_status "Step 9/12: Configuring Django for production..."

# Create production settings file
cat > $PROJECT_DIR/restaurant_system/production_settings.py << 'PYEOF'
from .settings import *
from decouple import config

# Security Settings
DEBUG = config('DEBUG', default=False, cast=bool)
SECRET_KEY = config('SECRET_KEY')
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='').split(',')

# Database
DATABASES = {
    'default': {
        'ENGINE': config('DATABASE_ENGINE', default='django.db.backends.postgresql'),
        'NAME': config('DATABASE_NAME'),
        'USER': config('DATABASE_USER'),
        'PASSWORD': config('DATABASE_PASSWORD'),
        'HOST': config('DATABASE_HOST', default='localhost'),
        'PORT': config('DATABASE_PORT', default='5432'),
    }
}

# Static files
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_ROOT = BASE_DIR / 'media'

# Security settings
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True

# CSRF settings
CSRF_COOKIE_SECURE = False  # Set to True when using HTTPS
SESSION_COOKIE_SECURE = False  # Set to True when using HTTPS
PYEOF

print_success "Production settings configured!"

# Step 10: Run Django migrations and collect static files
print_status "Step 10/12: Setting up database tables and collecting static files..."
cd $PROJECT_DIR
source venv/bin/activate

# Export Django settings module
export DJANGO_SETTINGS_MODULE=restaurant_system.production_settings

python manage.py makemigrations
python manage.py migrate --noinput
python manage.py collectstatic --noinput

print_success "Database tables created and static files collected!"

# Step 11: Set correct permissions
print_status "Step 11/12: Setting file permissions..."
chown -R www-data:www-data $PROJECT_DIR
chmod -R 755 $PROJECT_DIR
print_success "Permissions set!"

# Step 12: Configure Nginx
print_status "Step 12/12: Configuring Nginx web server..."
cat > /etc/nginx/sites-available/$PROJECT_NAME << NGINXEOF
server {
    listen 80;
    server_name $SERVER_IP;

    client_max_body_size 10M;

    access_log /var/log/nginx/restaurant_access.log;
    error_log /var/log/nginx/restaurant_error.log;

    location /static/ {
        alias /var/www/restaurant/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias /var/www/restaurant/media/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_redirect off;
    }

    # WebSocket support for real-time order tracking
    location /ws/ {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    }
}
NGINXEOF

# Enable site
ln -sf /etc/nginx/sites-available/$PROJECT_NAME /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test Nginx configuration
nginx -t

# Reload Nginx
systemctl restart nginx
print_success "Nginx configured and restarted!"

# Create systemd service for Gunicorn
print_status "Creating Gunicorn service..."
cat > /etc/systemd/system/$PROJECT_NAME.service << 'SERVICEEOF'
[Unit]
Description=Restaurant Ordering System (Gunicorn)
After=network.target

[Service]
Type=notify
User=www-data
Group=www-data
RuntimeDirectory=gunicorn
WorkingDirectory=/var/www/restaurant
Environment="PATH=/var/www/restaurant/venv/bin"
Environment="DJANGO_SETTINGS_MODULE=restaurant_system.production_settings"
ExecStart=/var/www/restaurant/venv/bin/gunicorn \
    --workers 3 \
    --bind 127.0.0.1:8000 \
    --access-logfile /var/log/gunicorn/access.log \
    --error-logfile /var/log/gunicorn/error.log \
    --log-level info \
    restaurant_system.wsgi:application
ExecReload=/bin/kill -s HUP $MAINPID
KillMode=mixed
TimeoutStopSec=5
PrivateTmp=true

[Install]
WantedBy=multi-user.target
SERVICEEOF

# Create Gunicorn log directory
mkdir -p /var/log/gunicorn

# Create systemd service for Daphne (WebSocket)
print_status "Creating Daphne service for WebSocket support..."
cat > /etc/systemd/system/${PROJECT_NAME}-daphne.service << 'DAPHNEEOF'
[Unit]
Description=Restaurant Ordering System (Daphne WebSocket)
After=network.target

[Service]
Type=simple
User=www-data
Group=www-data
WorkingDirectory=/var/www/restaurant
Environment="PATH=/var/www/restaurant/venv/bin"
Environment="DJANGO_SETTINGS_MODULE=restaurant_system.production_settings"
ExecStart=/var/www/restaurant/venv/bin/daphne \
    -b 127.0.0.1 \
    -p 8001 \
    restaurant_system.asgi:application
Restart=on-failure

[Install]
WantedBy=multi-user.target
DAPHNEEOF

# Reload systemd, enable and start services
systemctl daemon-reload
systemctl enable $PROJECT_NAME
systemctl enable ${PROJECT_NAME}-daphne
systemctl start $PROJECT_NAME
systemctl start ${PROJECT_NAME}-daphne

print_success "Services created and started!"

# Configure firewall
print_status "Configuring firewall..."
ufw allow 'Nginx Full'
ufw allow OpenSSH
ufw --force enable
print_success "Firewall configured!"

# Final status check
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                          ║${NC}"
echo -e "${GREEN}║           ✅  DEPLOYMENT COMPLETED! ✅                   ║${NC}"
echo -e "${GREEN}║                                                          ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════════╝${NC}"
echo ""

print_success "Your restaurant ordering system is now live!"
echo ""
echo -e "${BLUE}🌐 Access your website at:${NC}"
echo -e "${GREEN}   http://$SERVER_IP${NC}"
echo ""
echo -e "${BLUE}🔐 Next steps:${NC}"
echo "   1. Create an admin user:"
echo "      cd $PROJECT_DIR"
echo "      source venv/bin/activate"
echo "      python manage.py createsuperuser"
echo ""
echo "   2. Login at: http://$SERVER_IP/accounts/login/"
echo ""
echo -e "${BLUE}📊 Check service status:${NC}"
echo "   sudo systemctl status $PROJECT_NAME"
echo "   sudo systemctl status ${PROJECT_NAME}-daphne"
echo "   sudo systemctl status nginx"
echo "   sudo systemctl status postgresql"
echo "   sudo systemctl status redis-server"
echo ""
echo -e "${BLUE}📝 View logs:${NC}"
echo "   sudo journalctl -u $PROJECT_NAME -f"
echo "   sudo tail -f /var/log/nginx/restaurant_error.log"
echo ""
echo -e "${YELLOW}⚠️  Important:${NC}"
echo "   - Database Password: $DB_PASSWORD"
echo "   - Save this information securely!"
echo "   - Create your admin user (step 1 above)"
echo ""
print_success "Deployment script completed successfully! 🎉"
