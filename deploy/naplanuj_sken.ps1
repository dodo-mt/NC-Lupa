# Naplánuje automatický sken Lupy v Plánovači úloh pre aktuálneho používateľa (bez admin práv).
# Spúšťa sa cez naplanuj_sken.bat. Spúšťač: pri prihlásení (+2 min) a potom každú hodinu 12 hodín.
# Zrušenie:  naplanuj_sken.bat zrus
param(
    [string]$Exe = (Join-Path $PSScriptRoot 'lupa-sken.exe'),
    [string]$TaskName = 'Lupa sken',
    [switch]$Zrus
)
$ErrorActionPreference = 'Stop'

if ($Zrus) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "Uloha '$TaskName' zrusena."
    exit 0
}

if (-not (Test-Path $Exe)) { throw "Nenasiel sa $Exe" }

$user = "$env:USERDOMAIN\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute $Exe -Argument '--auto' -WorkingDirectory (Split-Path $Exe)

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$trigger.Delay = 'PT2M'   # počkať, kým sa pripojí sieťový disk
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 1) -RepetitionDuration (New-TimeSpan -Hours 12)).Repetition

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3)
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "OK: uloha '$TaskName' naplanovana pre $user"
Write-Host "    spusta: $Exe --auto"
Write-Host "    kedy:   pri prihlaseni (+2 min), potom kazdu hodinu pocas 12 h"
