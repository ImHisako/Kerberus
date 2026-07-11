$ErrorActionPreference = "Stop"
if (-not (Test-Path ".venv\Scripts\pythonw.exe")) {
    Write-Host "Ambiente non configurato. Eseguo setup.ps1..."
    & "$PSScriptRoot\setup.ps1"
}
& "$PSScriptRoot\.venv\Scripts\pythonw.exe" -m kerberus.main

