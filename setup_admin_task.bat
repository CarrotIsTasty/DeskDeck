@echo off
echo Registering the elevated Scheduled Task for DeskDeck...
echo.
echo IMPORTANT: this needs to run AS ADMINISTRATOR. If you just double-clicked
echo this file normally, close this window, then right-click
echo setup_admin_task.bat and choose "Run as administrator" instead.
echo.
echo This is a ONE-TIME step. After it succeeds, launching DeskDeck will no
echo longer show a UAC prompt every time.
echo.
pause

cd /d "%~dp0"

if exist dist\DeskDeck\DeskDeck.exe (
    dist\DeskDeck\DeskDeck.exe --register-task
) else if exist venv\Scripts\python.exe (
    venv\Scripts\python.exe main.py --register-task
) else (
    python main.py --register-task
)

echo.
pause
