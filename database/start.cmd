@echo off
cd /d "%~dp0"
".runtime\Scripts\python.exe" app.py
if errorlevel 1 pause
