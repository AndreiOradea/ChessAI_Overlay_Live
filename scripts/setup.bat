@echo off
echo ============================================
echo  ChessAI Overlay LIVE - Setup
echo ============================================
echo.

REM Always run from the project root (parent of scripts\)
cd /d "%~dp0.."

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH.
    echo Download Python 3.10+ from https://www.python.org/downloads/
    echo During install, check "Add python.exe to PATH".
    pause
    exit /b 1
)

echo Project folder: %CD%
echo.

if not exist "requirements.txt" (
    echo ERROR: requirements.txt not found in:
    echo   %CD%
    echo Make sure you extracted the full zip and are running scripts\setup.bat
    pause
    exit /b 1
)

echo Creating virtual environment...
python -m venv venv
if errorlevel 1 (
    echo ERROR: Failed to create virtual environment.
    pause
    exit /b 1
)

call venv\Scripts\activate.bat

echo Installing dependencies...
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo ERROR: pip install failed. See messages above.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  Setup complete!
echo.
echo  Next steps:
echo  1. Download Stockfish from https://stockfishchess.org/download/
echo     and place stockfish.exe somewhere (e.g. C:\stockfish\)
echo  2. Run:  scripts\launch.bat
echo ============================================
pause
