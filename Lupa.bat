@echo off
rem Spustí Lupu bez okna konzoly (pythonw z .venv vedľa tohto súboru).
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Chyba: nenasiel sa .venv\Scripts\pythonw.exe
    echo Vytvor prostredie:  python -m venv .venv  a  .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "%~dp0app.py"
