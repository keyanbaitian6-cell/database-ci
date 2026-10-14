@echo off
setlocal
cd /d "%~dp0"
if exist "..\database\.runtime\Scripts\python.exe" (
    "..\database\.runtime\Scripts\python.exe" app.py %*
) else if exist "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" (
    "%LocalAppData%\Python\pythoncore-3.14-64\python.exe" app.py %*
) else (
    py -3 app.py %*
)
if errorlevel 1 pause
