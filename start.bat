@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

:: 1. Check if standalone DeskDeck.exe exists in current directory
if exist "%~dp0DeskDeck.exe" (
    start "" "%~dp0DeskDeck.exe"
    exit /b
)

:: 2. Check if standalone DeskDeck.exe exists in dist\DeskDeck\
if exist "%~dp0dist\DeskDeck\DeskDeck.exe" (
    start "" "%~dp0dist\DeskDeck\DeskDeck.exe"
    exit /b
)

:: 3. Python Source Mode: Auto-setup Virtual Environment if missing
if not exist "%~dp0venv\Scripts\python.exe" (
    echo [DeskDeck] First time setup: creating virtual environment...
    python -m venv "%~dp0venv"
    if errorlevel 1 (
        echo [ERROR] Python is not installed or not added to PATH.
        echo Please install Python 3.9+ from https://www.python.org/
        pause
        exit /b 1
    )
    echo [DeskDeck] Installing required dependencies...
    "%~dp0venv\Scripts\pip.exe" install -r "%~dp0requirements.txt"
)

:: 4. Launch main.py quietly
if exist "%~dp0venv\Scripts\pythonw.exe" (
    start "" "%~dp0venv\Scripts\pythonw.exe" "%~dp0main.py"
) else (
    start "" "%~dp0venv\Scripts\python.exe" "%~dp0main.py"
)
exit /b 0
