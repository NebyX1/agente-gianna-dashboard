[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$AgentRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $AgentRoot
foreach ($command in @('uv', 'node', 'npm')) {
    if (!(Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Falta $command. Revisá docs/instalacion-rapida.md y abrí una terminal nueva después de instalarlo."
    }
}
$nodeVersion = [version]((node --version).TrimStart('v'))
if ($nodeVersion.Major -ne 22 -or $nodeVersion -lt [version]'22.13.0') {
    throw 'Gianna necesita Node 22.13 o posterior dentro de la rama 22; recomendado: 22.23.3.'
}
uv sync --locked --python 3.12
if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar el lock de Python' }
& '.venv\Scripts\python.exe' -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar Chromium' }
& '.venv\Scripts\python.exe' -m gianna models download
if ($LASTEXITCODE -ne 0) { throw 'No se pudieron verificar los modelos' }
. (Join-Path (Split-Path -Parent $AgentRoot) 'scripts\windows-toolchain.ps1')
npm --prefix ui ci
if ($LASTEXITCODE -ne 0) { throw 'No se pudo instalar la consola' }
npm --prefix ui run build
if ($LASTEXITCODE -ne 0) { throw 'No se pudo construir la consola' }
if (!(Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
Write-Host 'Gianna instalada. Configurá OLLAMA_API_KEY en .env y ejecutá scripts\start.ps1 con tickets activo.'
