#!/bin/bash
# Deploy updated print client to production
# VPS: 72.62.51.225
# Project: /var/www/restaurant

echo "================================================"
echo "   DEPLOYING UPDATED PRINT CLIENT"
echo "================================================"
echo ""

# Navigate to project directory
cd /var/www/restaurant || exit 1

# Pull latest changes
echo "Pulling latest changes from GitHub..."
git pull origin main

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
source venv/bin/activate

# Run migrations (in case any model changes)
echo ""
echo "Running migrations..."
python manage.py migrate --settings=restaurant_system.production_settings

# Collect static files (to make ZIP available for download)
echo ""
echo "Collecting static files..."
python manage.py collectstatic --noinput --settings=restaurant_system.production_settings

# Restart services
echo ""
echo "Restarting services..."
sudo systemctl restart restaurant-gunicorn restaurant-daphne nginx

echo ""
echo "Checking service status..."
sudo systemctl status restaurant-gunicorn restaurant-daphne nginx --no-pager

echo ""
echo "================================================"
echo "   DEPLOYMENT COMPLETE!"
echo "================================================"
echo ""
echo "✓ Updated print client ZIP is now available at:"
echo "  https://hospitality.easyfixsoft.com/admin-panel/printer-settings/"
echo ""
echo "Changes deployed:"
echo "  • Print client with automatic printer validation"
echo "  • Smart fallback to working printers"  
echo "  • Error 1905 detection and handling"
echo "  • Diagnostic tool (DIAGNOSE_PRINTER.bat)"
echo "  • Quick fix tool (FIX_PRINTER_ERROR.bat)"
echo "  • Complete troubleshooting guide (TROUBLESHOOTING.md)"
echo ""
echo "Restaurant owners can now download the updated version!"
echo "================================================"
