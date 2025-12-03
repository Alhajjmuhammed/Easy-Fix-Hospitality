@echo off
REM Restaurant Print Client - Quick Start Script
REM =============================================

title Restaurant Print Client

echo.
echo ╔═══════════════════════════════════════════════════════════╗
echo ║   Restaurant Print Client - Starting...                  ║
echo ╚═══════════════════════════════════════════════════════════╝
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Please install Python from https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

REM Check if config.json exists
if not exist "config.json" (
    echo ERROR: config.json not found
    echo Please copy config.json.example to config.json and edit it
    echo.
    pause
    exit /b 1
)

REM Check if dependencies are installed
python -c "import requests" >nul 2>&1
if errorlevel 1 (
    echo Installing dependencies...
    pip install requests pywin32
    echo.
)

REM Run print client
echo Starting print client...
echo Press Ctrl+C to stop
echo.
python print_client.py

pause
