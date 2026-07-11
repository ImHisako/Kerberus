$ErrorActionPreference = "Stop"
$Python = Get-Command py -ErrorAction Stop

if (-not (Test-Path ".venv")) {
    & $Python.Source -3 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e .
Write-Host "Kerberus installato. Avvia con .\start.ps1"

