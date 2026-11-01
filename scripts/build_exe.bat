@echo off
echo Building ChessAI Overlay LIVE executable with PyInstaller...
echo.

cd /d "%~dp0.."
if exist venv\Scripts\activate.bat (
    call venv\Scripts\activate.bat
)

pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    pip install pyinstaller
)

echo.
echo Running PyInstaller from ChessAI_Overlay_LIVE.spec (this may take a few minutes)...
pyinstaller --noconfirm ChessAI_Overlay_LIVE.spec

echo.
if exist dist\ChessAI_Overlay_LIVE\ChessAI_Overlay_LIVE.exe (
    echo SUCCESS: Executable created at dist\ChessAI_Overlay_LIVE\ChessAI_Overlay_LIVE.exe
) else (
    echo Build may have failed – check output above.
)
pause
