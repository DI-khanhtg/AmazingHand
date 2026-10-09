param(
    [ValidateSet('angles', 'tracking')]
    [string]$Mode = 'angles'
)

$ErrorActionPreference = 'Stop'
$demoPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
$demoDora = Join-Path $PSScriptRoot '.venv\Scripts\dora.exe'
if (!(Test-Path -LiteralPath $demoPython) -or !(Test-Path -LiteralPath $demoDora)) {
    throw 'Dependencies are missing. Run: powershell -ExecutionPolicy Bypass -File .\setup-demo.ps1'
}

$previousPath = $env:PATH
$previousVirtualEnv = $env:VIRTUAL_ENV
try {
    $env:VIRTUAL_ENV = Join-Path $PSScriptRoot '.venv'
    $env:PATH = (Join-Path $PSScriptRoot '.venv\Scripts') + ';' + $env:PATH
    Push-Location (Join-Path $PSScriptRoot 'Demo')
    try {
        $dataflow = if ($Mode -eq 'tracking') { 'dataflow_tracking_simu.yml' } else { 'dataflow_angle_simu.yml' }
        Write-Host "Starting $Mode simulation. Press Ctrl+C in this terminal to stop."
        & $demoDora run $dataflow
        if ($LASTEXITCODE -ne 0) { throw "Demo exited with code $LASTEXITCODE" }
    }
    finally { Pop-Location }
}
finally {
    $env:PATH = $previousPath
    $env:VIRTUAL_ENV = $previousVirtualEnv
}
