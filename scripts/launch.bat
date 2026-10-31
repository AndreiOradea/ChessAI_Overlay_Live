@echo off
cd /d "%~dp0.."
if not exist venv\Scripts\python.exe (echo Run scripts\setup.bat first & pause & exit /b 1)
venv\Scripts\python.exe -c "import PySide6" >nul 2>&1
if errorlevel 1 (echo PySide6 is missing. Run scripts\setup.bat to install the dependencies. & pause & exit /b 1)
venv\Scripts\python.exe main.py
if errorlevel 1 pause
