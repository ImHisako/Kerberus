$ErrorActionPreference = "Stop"
$Python = Get-Command py -ErrorAction Stop

if (-not (Test-Path ".venv")) {
    & $Python.Source -3 -m venv .venv
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e .
if (Get-Command go -ErrorAction SilentlyContinue) {
    New-Item -ItemType Directory -Force -Path "build\native" | Out-Null
    Push-Location native
    try {
        go build -trimpath -o "..\build\native\kerberus-native.exe" .
        if ($LASTEXITCODE -ne 0) { throw "Build helper Go fallita" }
    } finally {
        Pop-Location
    }
} else {
    Write-Warning "Go non trovato: messaggi vocali e trasporto nativo non saranno disponibili."
}
Write-Host "Kerberus installato. Avvia con .\start.ps1"
