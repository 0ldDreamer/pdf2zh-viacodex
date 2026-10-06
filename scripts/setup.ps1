param([string]$PythonExe,[string]$IndexUrl="https://pypi.org/simple")
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$stateRoot=Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Force -Path (Join-Path $stateRoot 'tmp'),(Join-Path $stateRoot 'cache/pip') | Out-Null
$env:TEMP=Join-Path $stateRoot 'tmp';$env:TMP=$env:TEMP;$env:TMPDIR=$env:TEMP
$env:PIP_CACHE_DIR=Join-Path $stateRoot 'cache/pip'
$env:PYTHONUTF8='1';$env:PYTHONDONTWRITEBYTECODE='1'
. (Join-Path $PSScriptRoot 'python_probe.ps1')
$PythonExe=Find-SetupPython -PythonExe $PythonExe
Write-Host ('Using Python: '+$PythonExe)
$venvPython=Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    & $PythonExe -m venv (Join-Path $projectRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create virtual environment.' }
}
& $venvPython -m pip install --index-url $IndexUrl -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed; inspect network/proxy and retry.' }
& $venvPython -B (Join-Path $projectRoot 'project.py') bootstrap
if ($LASTEXITCODE -ne 0) { throw 'Cache isolation configuration failed.' }
& $venvPython -B (Join-Path $projectRoot 'project.py') codex-check
if ($LASTEXITCODE -ne 0) {
    $npmCommand=Get-Command npm.cmd -ErrorAction SilentlyContinue
    if (-not $npmCommand) { throw 'Please install Node.js LTS and rerun setup to install official Codex CLI.' }
    & $npmCommand.Source install --prefix (Join-Path $stateRoot 'tools') --cache (Join-Path $stateRoot 'cache/npm') '@openai/codex'
    if ($LASTEXITCODE -ne 0) { throw 'Official Codex CLI installation failed.' }
}
& $venvPython -B (Join-Path $projectRoot 'project.py') test
if ($LASTEXITCODE -ne 0) { throw 'Self tests failed.' }
Write-Host 'SETUP PASS. Next: use the ChatGPT login launcher, then the PDF translation launcher.'
