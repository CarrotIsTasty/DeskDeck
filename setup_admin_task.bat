@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: Check for Administrator permissions
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [DeskDeck] Requesting administrative privileges...
    powershell -Command "Start-Process cmd.exe -ArgumentList '/c \"\"%~f0\"\"' -Verb RunAs"
    exit /b
)

echo =======================================================
echo   DeskDeck - One-Time Silent Elevation Task Setup
echo =======================================================
echo.

if exist "%~dp0DeskDeck.exe" (
    "%~dp0DeskDeck.exe" --register-task
) else if exist "%~dp0dist\DeskDeck\DeskDeck.exe" (
    "%~dp0dist\DeskDeck\DeskDeck.exe" --register-task
) else if exist "%~dp0venv\Scripts\python.exe" (
    "%~dp0venv\Scripts\python.exe" "%~dp0main.py" --register-task
) else (
    python "%~dp0main.py" --register-task
)

echo.
echo [Done] Scheduled Task setup finished.
echo Press any key to close this window...
pause >nul
