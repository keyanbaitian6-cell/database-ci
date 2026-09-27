@echo off
setlocal
cd /d "%~dp0"
if exist ".runtime\Scripts\python.exe" (
    ".runtime\Scripts\python.exe" app.py
) else (
    py -3 app.py
)
if errorlevel 1 pause
