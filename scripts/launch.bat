@echo off
REM Always run from the project root
cd /d "%~dp0.."

if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
) else (
    echo Virtual environment not found.
    echo Please run scripts\setup.bat first.
    pause
    exit /b 1
)

python main.py
if errorlevel 1 pause
