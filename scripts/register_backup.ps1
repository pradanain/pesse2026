$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$backupScript = Join-Path $PSScriptRoot 'backup_local.py'
$taskLabel = 'PESSE2026-LocalBackup'
$arguments = '"' + $backupScript + '"'
$action = New-ScheduledTaskAction -Execute $pythonPath -Argument $arguments -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -Daily -At '07:00'
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal -UserId $identity -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -Hidden -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
$existing = Get-ScheduledTask -TaskName $taskLabel -ErrorAction SilentlyContinue
if ($existing) {
    throw 'Task sudah ada. Tinjau task tersebut sebelum mengganti jadwal.'
}
Register-ScheduledTask -TaskName $taskLabel -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'Backup SQLite PES SE2026 dan uji restore pada database sementara.' | Out-Null
Write-Output 'Backup harian terdaftar pukul 07:00, saat akun Windows sedang masuk; jadwal terlewat dijalankan saat tersedia.'
