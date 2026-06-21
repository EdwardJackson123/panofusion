@echo off
title PanoFusion
echo ========================================
echo   PanoFusion — 全景融合重建工作站
echo ========================================
echo.

REM Start Python backend in background
echo [1/2] Starting backend...
start "PanoFusion-Backend" /MIN cmd /c ""%~dp0Metashape\App\Metashape\python\python.exe" -u "%~dp0backend\main.py""

REM Wait for backend
echo Waiting for backend to be ready...
:wait_backend
timeout /t 2 /nobreak >nul
set BACKEND_READY=
for %%P in (8765 8766 8767 8768) do (
    curl -s http://localhost:%%P/api/health >nul 2>&1
    if not errorlevel 1 set BACKEND_READY=%%P
)
if "%BACKEND_READY%"=="" goto wait_backend
echo Backend ready on port %BACKEND_READY%.

echo [2/2] Launching PanoFusion...
echo.

REM Try Edge in app mode first, then Chrome, then default browser
start msedge --app=http://localhost:5173 --window-size=1280,860 2>nul
if %errorlevel% neq 0 (
    start chrome --app=http://localhost:5173 --window-size=1280,860 2>nul
)
if %errorlevel% neq 0 (
    start http://localhost:5173
)

echo PanoFusion is running.
echo Close this window to stop the backend.
pause

REM Cleanup
taskkill /FI "WINDOWTITLE eq PanoFusion-Backend*" /F 2>nul
