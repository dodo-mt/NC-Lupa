# Ikona Lupa skenu pri hodinách – inštalácia pre aktuálneho používateľa (bez admin práv).
# Spúšťa sa cez ikona_skenu.bat z priečinka L:\_Lupa\.
#  - skopíruje lupa-sken.exe do %LOCALAPPDATA%\Lupa\bin (pri prihlásení ešte nemusí byť L:\ pripojený)
#  - vytvorí odkaz v priečinku Po spustení (Startup) s cestami na L:\ a databázu
#  - zruší starú úlohu „Lupa sken“ v Plánovači úloh (ak existuje) a spustí ikonu
# Zrušenie:  ikona_skenu.bat zrus
param(
    [string]$Source = (Join-Path $PSScriptRoot 'lupa-sken.exe'),
    [string]$Db = (Join-Path $PSScriptRoot 'lupa.db'),
    [string]$Root = '',
    [switch]$Zrus
)
$ErrorActionPreference = 'Stop'

$bin = Join-Path $env:LOCALAPPDATA 'Lupa\bin'
$exe = Join-Path $bin 'lupa-sken.exe'
$lnk = Join-Path ([Environment]::GetFolderPath('Startup')) 'Lupa sken.lnk'

# bežiacu ikonu ukončiť (kvôli prepísaniu exe / zrušeniu)
Get-Process -Name 'lupa-sken' -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Milliseconds 500

if ($Zrus) {
    Remove-Item $lnk -ErrorAction SilentlyContinue
    Remove-Item $exe -ErrorAction SilentlyContinue
    Write-Host 'Ikona Lupa skenu odstranena (odkaz Po spusteni aj lokalna kopia).'
    exit 0
}

if (-not (Test-Path $Source)) { throw "Nenasiel sa $Source" }
if (-not $Root) {
    # koreň z lupa.ini vedľa exe, inak koreň disku, na ktorom je _Lupa (napr. L:\)
    $ini = Join-Path $PSScriptRoot 'lupa.ini'
    $m = if (Test-Path $ini) { Select-String -Path $ini -Pattern '^\s*root\s*=\s*(.+)$' | Select-Object -First 1 }
    $Root = if ($m) { $m.Matches[0].Groups[1].Value.Trim() } else { [IO.Path]::GetPathRoot($PSScriptRoot) }
}

New-Item -ItemType Directory -Force $bin | Out-Null
Copy-Item $Source $exe -Force

$sh = New-Object -ComObject WScript.Shell
$s = $sh.CreateShortcut($lnk)
$s.TargetPath = $exe
# Pozor: "L:\" na príkazovom riadku = L: + doslovná úvodzovka (\" sa berie ako escape)!
# Preto bez koncového \ – skener si "L:" doplní na "L:\".
$s.Arguments = "--tray --root `"$($Root.TrimEnd('\'))`" --db `"$Db`""
$s.WorkingDirectory = $bin
$s.IconLocation = "$exe,0"
$s.Description = 'Lupa – sken zákaziek (ikona pri hodinách)'
$s.Save()

# stará úloha z Plánovača (predchádzajúca verzia) – už netreba
if (Get-ScheduledTask -TaskName 'Lupa sken' -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName 'Lupa sken' -Confirm:$false
    Write-Host 'Stara uloha "Lupa sken" v Planovaci uloh zrusena.'
}

Start-Process -FilePath $exe -ArgumentList $s.Arguments -WorkingDirectory $bin
Write-Host 'OK: ikona Lupa skenu nainstalovana a spustena.'
Write-Host "    koren: $Root"
Write-Host "    DB:    $Db"
Write-Host '    spusta sa pri prihlaseni (priecinok Po spusteni), sken kazdu hodinu.'
