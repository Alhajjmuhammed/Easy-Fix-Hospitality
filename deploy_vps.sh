#!/bin/bash
# ============================================================
# VPS Deploy Script — run this on the VPS after any git push
# Usage: ssh root@72.62.51.225 "bash /var/www/restaurant/deploy_vps.sh"
# ============================================================
set -e

cd /var/www/restaurant

echo "==> Pulling latest code from origin/test..."
git pull origin test

echo "==> Installing Python dependencies..."
pip install -r requirements-production.txt -q

echo "==> Running migrations..."
python manage.py migrate --settings=restaurant_system.production_settings --no-input

echo "==> Collecting static files..."
python manage.py collectstatic --settings=restaurant_system.production_settings --noinput

echo "==> Restarting services..."
systemctl restart restaurant-gunicorn restaurant-daphne nginx

echo ""
echo "✔ Deploy complete."
echo "  Check status: systemctl status gunicorn"
echo "  Check logs:   tail -50 logs/django.log"
