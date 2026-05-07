@echo off
echo Stopping PaperTracker Social services...
taskkill /FI "WINDOWTITLE eq PaperTracker*" /T /F 2>nul
echo All services stopped.
timeout /t 2 /nobreak >nul
