@echo off
:: PanoFusion Metashape Edition — setup script
:: Run once before first build or when Metashape is updated.

cd /d "%~dp0\.."

echo ========================================
echo  PanoFusion Metashape — 环境配置
echo ========================================

:: ── 1. Metashape Python 依赖 ──
set META_PYTHON=Metashape\App\Metashape\python\python.exe
if exist "%META_PYTHON%" (
    echo [1/2] 安装 numpy 到 Metashape Python ...
    "%META_PYTHON%" -m pip install numpy --quiet
    if %errorlevel% neq 0 (
        echo [警告] numpy 安装失败，请手动执行:
        echo   "%META_PYTHON%" -m pip install numpy
    ) else (
        echo         numpy 安装完成
    )
) else (
    echo [1/2] 未找到 Metashape 便携版，跳过 numpy 安装
    echo         请将 Metashape 放到 Metashape\App\Metashape\metashape.exe
)

:: ── 2. Node.js 依赖 ──
echo [2/2] 安装 Node.js 依赖 ...
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
pause
