@echo off
echo ========================================
echo Starting PaperTracker Social Services...
echo ========================================
echo.

echo [0/3] Starting PostgreSQL Database (Docker)...
docker-compose up -d postgres >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Failed to start Docker database. Please ensure Docker Desktop is running.
    pause
    exit /b 1
)

echo [0/3] Waiting for database to be ready...
timeout /t 5 /nobreak >nul

echo [1/3] Starting Backend API...
start "PaperTracker Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\activate.bat && python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

timeout /t 3 /nobreak >nul

echo [2/3] Starting Frontend...
start "PaperTracker Frontend" cmd /k "cd /d %~dp0web && npm run dev"

echo.
echo ========================================
echo All services started!
echo ========================================
echo.
echo Backend API:  http://localhost:8000
echo Frontend:     http://localhost:5173
echo API Docs:     http://localhost:8000/docs
echo.
echo Press any key to stop all services...
pause >nul

echo.
echo Stopping services...
taskkill /FI "WINDOWTITLE eq PaperTracker*" /T /F 2>nul
echo Services stopped.
