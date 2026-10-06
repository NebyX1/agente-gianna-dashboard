# SWC's Windows native cache needs an owner-only ACL; keep it within this repository.
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$cachePath = Join-Path $projectRoot '.swc-native-cache'
New-Item -ItemType Directory -Path $cachePath -Force | Out-Null
icacls $cachePath /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" 'SYSTEM:(OI)(CI)F' | Out-Null
$env:SWC_NATIVE_BINDING_CACHE = $cachePath
Write-Output 'SWC configurado para esta sesión de PowerShell.'
