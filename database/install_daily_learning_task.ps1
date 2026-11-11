param(
    [string]$PythonPath = (Join-Path $PSScriptRoot '.venv\Scripts\python.exe'),
    [string]$NodePath = '',
    [switch]$Preview
)
$ErrorActionPreference = 'Stop'
$taskPython = (Resolve-Path -LiteralPath $PythonPath).Path
$taskScript = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'daily_learning_runtime.py')).Path
$taskData = Join-Path $PSScriptRoot 'data'
if (!$NodePath) { $NodePath = (Get-Command node -ErrorAction Stop).Source }
$taskNode = (Resolve-Path -LiteralPath $NodePath).Path
$taskArgs = '-B -X utf8 "' + $taskScript + '" --data-dir "' + $taskData + '" --node "' + $taskNode + '"'
$taskName = 'database 全店舗の日次学習'
if ($Preview) {
    [pscustomobject]@{名前=$taskName; 実行=$taskPython; 引数=$taskArgs; 時刻='毎日07:30・ログオン時。取り逃しは再開時に実行'; 締切='08:00 JST。締切後の事前予測は作成しない'}
    exit 0
}
$taskAction = New-ScheduledTaskAction -Execute $taskPython -Argument $taskArgs -WorkingDirectory $PSScriptRoot
$taskTrigger = @((New-ScheduledTaskTrigger -Daily -At '07:30'), (New-ScheduledTaskTrigger -AtLogOn))
$taskSettings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 45) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$taskPrincipal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType Interactive -RunLevel Limited
$task = New-ScheduledTask -Action $taskAction -Trigger $taskTrigger -Settings $taskSettings -Principal $taskPrincipal -Description '保存済みデータだけを使用。原本DBと既存研究は読み取り専用。'
Register-ScheduledTask -TaskName $taskName -InputObject $task -Force | Select-Object TaskName,State
