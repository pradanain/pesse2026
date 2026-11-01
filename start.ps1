$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:AUTH_REQUIRED = '1'
$portalPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $portalPython)) {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Pembuatan virtual environment gagal.' }
    & $portalPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Pemasangan dependency gagal.' }
}
& $portalPython setup_local.py
if ($LASTEXITCODE -ne 0) { throw 'Inisialisasi/impor gagal. Dataset aktif tidak diubah.' }
& $portalPython run_local.py
