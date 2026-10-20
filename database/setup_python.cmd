@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" setup_python.py
) else if exist ".runtime\Scripts\python.exe" (
    ".runtime\Scripts\python.exe" setup_python.py
) else (
    py -3 setup_python.py
)
if errorlevel 1 (
    echo 専用Pythonのセットアップに失敗しました。上のエラーを確認してください。
    pause
    exit /b 1
)
pause
