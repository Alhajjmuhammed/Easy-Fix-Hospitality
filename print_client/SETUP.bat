@echo off
REM =============================================
REM Restaurant Print Client - First Time Setup
REM =============================================

title Print Client Setup

echo.
echo ========================================================
echo    RESTAURANT PRINT CLIENT - FIRST TIME SETUP
echo ========================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed!
    echo.
    echo Please install Python first:
    echo   1. Go to https://www.python.org/downloads/
    echo   2. Download and install Python
    echo   3. IMPORTANT: Check "Add Python to PATH" during install
    echo   4. Run this setup again
    echo.
    pause
    exit /b 1
)

echo [OK] Python is installed
echo.

REM Install dependencies
echo Installing required packages...
pip install -r requirements.txt
echo.
echo [OK] Packages installed
echo.

REM Check if config.json exists
if exist "config.json" (
    echo [OK] config.json already exists
    echo.
    echo Setup complete! You can now run start_print_client.bat
    echo.
    pause
    exit /b 0
)

REM Create config.json
echo.
echo ========================================================
echo    ENTER YOUR API TOKEN
echo ========================================================
echo.
echo To get your token:
echo   1. Go to https://hospitality.easyfixsoft.com
echo   2. Login with your username and password
echo   3. Click "Printer Settings" in the menu
echo   4. Copy the API Token shown on that page
echo.
echo ========================================================
echo.

set /p TOKEN="Paste your API Token here and press Enter: "

REM Create config.json with the token
(
echo {
echo     "server_url": "https://hospitality.easyfixsoft.com",
echo     "api_token": "%TOKEN%",
echo     "poll_interval": 5,
echo     "auto_detect_printer": true
echo }
) > config.json

echo.
echo [OK] config.json created with your token
echo.
echo ========================================================
echo    SETUP COMPLETE!
echo ========================================================
echo.
echo Now you can:
echo   1. Connect your printer via USB
echo   2. Double-click "start_print_client.bat" to start printing
echo.
pause
