@echo off
:: PanoFusion COLMAP Edition — setup script
:: Run once before first build.

cd /d "%~dp0\.."

echo ========================================
echo  PanoFusion COLMAP — 环境配置
echo ========================================

:: ── 1. Python virtual environment ──
echo [1/3] 创建 Python 虚拟环境 ...
if not exist ".venv\Scripts\python.exe" (
    python -m venv .venv
    if %errorlevel% neq 0 (
        echo [错误] 创建 venv 失败，请确认 Python 3.10+ 已安装且在 PATH 中
        pause
        exit /b 1
    )
    echo         venv 创建完成
) else (
    echo         venv 已存在，跳过
)

:: ── 2. Install Python dependencies ──
echo [2/3] 安装 Python 依赖 ...
.venv\Scripts\python.exe -m pip install numpy pillow --quiet
if %errorlevel% neq 0 (
    echo [错误] pip 安装失败
    pause
    exit /b 1
)
echo         numpy, pillow 安装完成

:: ── 3. Node.js dependencies ──
echo [3/3] 安装 Node.js 依赖 ...
if exist "package.json" (
    call npm install --silent 2>nul
    cd frontend
    call npm install --silent 2>nul
    cd ..
    echo         Node 依赖安装完成
)

echo.
echo ========================================
echo  配置完成！运行 npm run build 打包
echo ========================================
echo  注意：colmap.exe 请放到 colmap\bin\colmap.exe
echo ========================================
pause
