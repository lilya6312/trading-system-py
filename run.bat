@echo off
title 个人交易系统工作台 - 启动器
cd /d "%~dp0"

rem ========== 定位 Python ==========
rem 优先使用豆包沙箱自带的 Python（完整路径，不依赖 PATH）
set PYEXE=
if exist "%LOCALAPPDATA%\Doubao\User Data\sandbox_runtime\bases\c98c5042338ed152c6f10ecd8591889f\python\python.exe" set "PYEXE=%LOCALAPPDATA%\Doubao\User Data\sandbox_runtime\bases\c98c5042338ed152c6f10ecd8591889f\python\python.exe"
if defined PYEXE goto py_ok
rem 回退：使用系统 PATH 中的 python
where python >nul 2>nul
if errorlevel 1 goto no_python
set PYEXE=python

:py_ok
rem ========== 依赖检查 ==========
"%PYEXE%" -c "import streamlit" >nul 2>nul
if errorlevel 1 goto install_deps
goto run_app

:install_deps
echo [首次运行] 正在安装依赖，请稍候...
"%PYEXE%" -m pip install -r requirements.txt
if errorlevel 1 goto fail
goto run_app

:run_app
if not exist "data" mkdir data
netstat -ano | findstr LISTENING | findstr ":8501 " >nul 2>nul
if not errorlevel 1 goto port_busy

echo 正在后台启动服务，请稍候...
start "" /b "%PYEXE%" -m streamlit run main.py --server.port 8501 --server.headless true

set /a tries=0
:wait
ping -n 3 127.0.0.1 >nul
netstat -ano | findstr LISTENING | findstr ":8501 " >nul 2>nul
if not errorlevel 1 goto ready
set /a tries+=1
if %tries% GEQ 60 goto slow
goto wait

:ready
echo 服务已启动: http://localhost:8501
echo 正在打开浏览器...
start "" "http://localhost:8501"
echo.
echo 提示: 服务在后台运行，关闭本窗口不影响服务。
echo       如需停止服务，请运行 stop.bat
ping -n 4 127.0.0.1 >nul
exit /b 0

:slow
echo [提示] 等待超时，服务启动较慢。
echo       请稍后手动访问 http://localhost:8501
ping -n 4 127.0.0.1 >nul
exit /b 0

:port_busy
echo [提示] 端口 8501 已被占用，服务可能已在运行。
echo       请直接访问 http://localhost:8501
ping -n 4 127.0.0.1 >nul
exit /b 0

:no_python
echo [错误] 未找到可用的 Python。
echo       请安装 Python 3.10+ 并勾选 "Add to PATH" 后重试。
pause
exit /b 1

:fail
echo [错误] 依赖安装失败，请检查网络后重试
pause
exit /b 1