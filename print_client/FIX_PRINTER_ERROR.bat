@echo off
REM =============================================
REM Quick Fix for Printer Error 1905
REM =============================================

title Printer Quick Fix

echo.
echo ========================================================
echo    PRINTER ERROR 1905 - QUICK FIX
echo ========================================================
echo.
echo This will restart the Windows Print Spooler service
echo which often fixes "printer deleted" errors.
echo.
echo Press any key to restart print spooler...
pause > nul

echo.
echo Stopping print spooler...
net stop spooler

echo.
echo Clearing print queue...
del /Q /F /S "%systemroot%\System32\spool\PRINTERS\*" 2>nul

echo.
echo Starting print spooler...
net start spooler

echo.
echo ========================================================
echo.
echo Print spooler has been restarted!
echo.
echo NEXT STEPS:
echo 1. Close and restart the print client
echo 2. Try printing again
echo.
echo If still not working, run DIAGNOSE_PRINTER.bat
echo.
pause
