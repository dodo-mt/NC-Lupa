@echo off
rem Naplánuje automatický sken Lupy (Plánovač úloh, aktuálny používateľ, bez admin práv).
rem   naplanuj_sken.bat        = naplánovať
rem   naplanuj_sken.bat zrus   = zrušiť
if /i "%~1"=="zrus" (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0naplanuj_sken.ps1" -Zrus
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0naplanuj_sken.ps1"
)
pause
