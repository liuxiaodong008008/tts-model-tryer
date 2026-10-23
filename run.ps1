$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
$env:PYTHONUTF8 = '1'
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw 'Create .venv and install requirements.txt first. See README.md.'
}
& $python (Join-Path $PSScriptRoot 'app.py')
exit $LASTEXITCODE
