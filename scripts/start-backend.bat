@echo off
REM PanoFusion Backend Launcher
REM Uses Metashape's bundled Python to run the FastAPI backend

setlocal

REM Try to find Metashape's Python
set "METASHAPE_PYTHON=%~dp0..\Metashape\App\Metashape\python\python.exe"

if not exist "%METASHAPE_PYTHON%" (
    echo Looking for Metashape Python...
    REM Check common install locations
    if exist "C:\Program Files\Agisoft\Metashape Pro\python\python.exe" (
        set "METASHAPE_PYTHON=C:\Program Files\Agisoft\Metashape Pro\python\python.exe"
    ) else if exist "C:\Program Files\Agisoft\Metashape\python\python.exe" (
        set "METASHAPE_PYTHON=C:\Program Files\Agisoft\Metashape\python\python.exe"
    ) else (
        echo ERROR: Cannot find Metashape Python installation.
        echo Please set PANOFUSION_METASHAPE_PYTHON environment variable.
        pause
        exit /b 1
    )
)

echo Using Metashape Python: %METASHAPE_PYTHON%

REM Install required packages if needed
echo Checking dependencies...
"%METASHAPE_PYTHON%" -m pip install fastapi uvicorn pydantic websockets Pillow piexif --quiet

REM Start the backend
cd /d "%~dp0..\backend"
echo Starting PanoFusion Backend on port 8765...
"%METASHAPE_PYTHON%" -u main.py

pause
