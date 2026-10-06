[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$AgentRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $AgentRoot
& '.venv\Scripts\python.exe' -m gianna run
exit $LASTEXITCODE
