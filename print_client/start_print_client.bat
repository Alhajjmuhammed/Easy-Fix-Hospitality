@echo off
REM =============================================
REM Restaurant Print Client - Start Script
REM =============================================

title Restaurant Print Client

echo.
echo ========================================================
echo    RESTAURANT PRINT CLIENT
echo ========================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed!
    echo Please run SETUP.bat first
    echo.
    pause
    exit /b 1
)

REM Check if config.json exists
if not exist "config.json" (
    echo [ERROR] config.json not found!
    echo Please run SETUP.bat first
    echo.
    pause
    exit /b 1
)

REM Check if dependencies are installed, install if not
python -c "import requests" >nul 2>&1
if errorlevel 1 (
    echo Installing required packages...
    pip install -r requirements.txt
    echo.
)

REM Run print client
echo Starting Print Client...
echo.
echo Leave this window OPEN to keep printing orders!
echo Press Ctrl+C to stop
echo.
python print_client.py

pause
