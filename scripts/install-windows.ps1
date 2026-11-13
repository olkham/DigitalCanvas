# Starts Digital Canvas at logon on Windows (e.g. a NUC driving a monitor).
#
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\install-windows.ps1 -Remove
param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$dir = Split-Path -Parent $PSScriptRoot
$task = 'Digital Canvas'

if ($Remove) {
    Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
    "Removed the '$task' logon task. Media and config.json are untouched."
    return
}

$exe = Join-Path $dir 'dist\digitalcanvas-windows-amd64.exe'
if (-not (Test-Path $exe)) {
    if (-not (Get-Command go -ErrorAction SilentlyContinue)) { throw "Build first (scripts\build.ps1) or install Go 1.26+." }
    Push-Location $dir; try { & "$dir\scripts\build.ps1" } finally { Pop-Location }
}
$log = Join-Path $dir 'cache\digitalcanvas.log'
New-Item -ItemType Directory -Force (Join-Path $dir 'cache') | Out-Null
$taskArgs = "-NoProfile -WindowStyle Hidden -Command `"& '$exe' -config '$dir\config.json' -log '$log'`""
$action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $taskArgs -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName $task
"Registered and started '$task'. Log: $log"
