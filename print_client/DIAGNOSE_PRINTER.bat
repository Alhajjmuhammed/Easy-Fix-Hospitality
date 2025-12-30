@echo off
REM =============================================
REM Printer Diagnostic Tool
REM =============================================

title Printer Diagnostic

echo.
echo ========================================================
echo    PRINTER DIAGNOSTIC TOOL
echo ========================================================
echo.
echo This tool will check all your printers and identify
echo which ones are working and which have issues.
echo.
pause

python diagnose_printer.py

echo.
echo ========================================================
echo.
pause
