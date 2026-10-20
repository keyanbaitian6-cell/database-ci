@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app.py
) else if exist ".venv" (
    echo 専用Pythonを起動できません。database\setup_python.cmd を実行してください。
    pause
    exit /b 1
) else if exist ".runtime\Scripts\python.exe" (
    ".runtime\Scripts\python.exe" app.py
) else (
    echo 最初に database\setup_python.cmd を実行してください。
    pause
    exit /b 1
)
if errorlevel 1 pause
