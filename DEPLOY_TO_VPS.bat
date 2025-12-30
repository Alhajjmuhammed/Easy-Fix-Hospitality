@echo off
REM =============================================
REM Deploy to Production VPS (72.62.51.225)
REM =============================================

title Deploy to Production

echo.
echo ========================================================
echo    DEPLOYING TO PRODUCTION VPS
echo ========================================================
echo.
echo Server: 72.62.51.225
echo Project: /var/www/restaurant
echo.

REM Push to GitHub first
echo Step 1: Pushing changes to GitHub...
git push origin main
if errorlevel 1 (
    echo [ERROR] Failed to push to GitHub
    pause
    exit /b 1
)
echo [OK] Pushed to GitHub
echo.

REM SSH and deploy
echo Step 2: Connecting to VPS and deploying...
echo.
ssh root@72.62.51.225 "cd /var/www/restaurant && git pull origin main && source venv/bin/activate && python manage.py migrate --settings=restaurant_system.production_settings && python manage.py collectstatic --noinput --settings=restaurant_system.production_settings && sudo systemctl restart restaurant-gunicorn restaurant-daphne nginx"

if errorlevel 1 (
    echo.
    echo [ERROR] Deployment failed
    echo.
    echo Try running manually:
    echo   ssh root@72.62.51.225
    echo   cd /var/www/restaurant
    echo   git pull origin main
    echo   source venv/bin/activate
    echo   python manage.py collectstatic --noinput --settings=restaurant_system.production_settings
    echo   sudo systemctl restart restaurant-gunicorn restaurant-daphne nginx
    pause
    exit /b 1
)

echo.
echo ========================================================
echo    DEPLOYMENT SUCCESSFUL!
echo ========================================================
echo.
echo Updated print client is now available at:
echo https://hospitality.easyfixsoft.com/admin-panel/printer-settings/
echo.
echo Changes deployed:
echo   * Print client with automatic printer validation
echo   * Smart fallback to working printers
echo   * Error 1905 detection and handling
echo   * Diagnostic and troubleshooting tools
echo.
pause
