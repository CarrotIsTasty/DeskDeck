@echo off
REM Builds DeskDeck.exe with PyInstaller. Run this on Windows, in a normal
REM (non-admin) Command Prompt, from this folder.
cd /d "%~dp0"

if exist venv\Scripts\python.exe (
    set PY=venv\Scripts\python.exe
) else (
    set PY=python
)

%PY% -m pip install --upgrade pyinstaller

REM --contents-directory "." keeps the flat pre-6.0 layout (everything
REM directly in dist\DeskDeck\, no _internal subfolder) - the app expects
REM its "libs" folder to sit right next to DeskDeck.exe.
%PY% -m PyInstaller --noconfirm --onedir --windowed --name DeskDeck ^
    --contents-directory "." ^
    --add-data "libs;libs" ^
    --collect-all pythonnet ^
    --collect-all clr ^
    --collect-all clr_loader ^
    --collect-submodules comtypes.gen ^
    main.py

echo.
echo Done. Your app is in dist\DeskDeck\DeskDeck.exe
echo Copy the *whole* dist\DeskDeck folder when sharing it - the .exe alone
echo will not work, it needs the files sitting next to it.
pause
