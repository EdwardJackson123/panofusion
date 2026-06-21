@echo off
cd /d "%~dp0..\backend"
echo Starting PanoFusion COLMAP Edition Backend...
python -u main.py
pause
