@echo off
echo Registering the elevated Scheduled Task for DeskDeck...
echo.
echo IMPORTANT: this needs to run AS ADMINISTRATOR. If you just double-clicked
echo this file normally, close this window, then right-click
echo setup_admin_task.bat and choose "Run as administrator" instead.
echo.
echo This is a ONE-TIME step. After it succeeds, launching Mini Control
echo Center (via start.bat, or python main.py) will no longer show a UAC
echo prompt every time.
echo.
pause

cd /d "%~dp0"

if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe main.py --register-task
) else (
    python main.py --register-task
)

echo.
pause
