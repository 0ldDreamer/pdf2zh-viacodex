param([ValidateSet('gui','login','logout','doctor','translate','models','test')][string]$Command='gui',[Parameter(ValueFromRemainingArguments=$true)][string[]]$Arguments)
$ErrorActionPreference='Stop'
$projectRoot=Split-Path -Parent $PSScriptRoot
$stateRoot=Join-Path $projectRoot '.runtime'
New-Item -ItemType Directory -Force -Path (Join-Path $stateRoot 'tmp') | Out-Null
$env:TEMP=Join-Path $stateRoot 'tmp';$env:TMP=$env:TEMP;$env:TMPDIR=$env:TEMP
$env:PYTHONUTF8='1';$env:PYTHONDONTWRITEBYTECODE='1'
$python=Join-Path $projectRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run setup.cmd first.' }
& $python -B (Join-Path $projectRoot 'project.py') $Command @Arguments
exit $LASTEXITCODE
