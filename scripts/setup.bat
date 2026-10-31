@echo off
cd /d "%~dp0.."
echo ChessAI Board LIVE - Setup
python --version >nul 2>&1 || (echo Install Python 3.10+ and check Add to PATH & pause & exit /b 1)
python -m venv venv
if errorlevel 1 (echo Failed to create the virtual environment. & pause & exit /b 1)
venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 (echo Failed to upgrade pip. & pause & exit /b 1)
venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (echo Dependency installation failed. Check your internet connection and try again. & pause & exit /b 1)
echo.
echo Setup done. Put Stockfish in stockfish\ folder, then run scripts\launch.bat
pause
