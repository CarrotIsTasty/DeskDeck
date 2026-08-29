@echo off
REM Launches the Mini Control Center with no console window, then closes
REM this cmd window immediately. The app keeps running on its own.

cd /d "%~dp0"
start "" venv\Scripts\pythonw.exe main.py
exit
