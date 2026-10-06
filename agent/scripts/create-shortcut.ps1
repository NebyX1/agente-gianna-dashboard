[CmdletBinding()]
param([switch]$Testing)
$ErrorActionPreference = 'Stop'
$AgentRoot = Split-Path -Parent $PSScriptRoot
$ShortcutName = if ($Testing) { 'Gianna - Prueba admin.lnk' } else { 'Gianna - Mesa de ayuda.lnk' }
$LauncherName = if ($Testing) { 'start-testing.ps1' } else { 'start.ps1' }
$ShortcutPath = Join-Path ([Environment]::GetFolderPath('Desktop')) $ShortcutName
$ShortcutShell = New-Object -ComObject WScript.Shell
$Shortcut = $ShortcutShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = 'powershell.exe'
$Shortcut.Arguments = '-NoProfile -ExecutionPolicy Bypass -File "' + (Join-Path $PSScriptRoot $LauncherName) + '"'
$Shortcut.WorkingDirectory = $AgentRoot
$Shortcut.Description = 'Iniciar Gianna con su navegador propio. Ctrl+C cierra ordenadamente.'
$Shortcut.Save()
Write-Host "Acceso creado: $ShortcutPath"
