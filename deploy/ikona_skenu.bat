@echo off
rem Ikona Lupa skenu pri hodinách (spúšťa sa pri prihlásení, sken každú hodinu).
rem   ikona_skenu.bat        = nainštalovať / aktualizovať a spustiť
rem   ikona_skenu.bat zrus   = odstrániť
if /i "%~1"=="zrus" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ikona_skenu.ps1" -Zrus
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0ikona_skenu.ps1"
)
pause
