@echo off
cd /d "%~dp0.."
if exist venv\Scripts\activate.bat call venv\Scripts\activate.bat
python tests\test_move_list_sync.py
python tests\test_game_tracker.py
python tests\test_move_diff.py
pause
