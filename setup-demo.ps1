$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (!(Get-Command uv -ErrorAction SilentlyContinue)) {
        throw 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/'
    }
    if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
        & uv venv --python 3.12 --seed .venv
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    }
    & uv pip install --python .venv\Scripts\python.exe -r requirements-demo.lock
    if ($LASTEXITCODE -ne 0) { throw 'Could not install dependencies.' }
    & uv pip check --python .venv\Scripts\python.exe
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
    Write-Host 'Ready. Run: powershell -ExecutionPolicy Bypass -File .\run-demo.ps1'
}
finally { Pop-Location }
