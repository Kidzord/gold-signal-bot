<#
.SYNOPSIS
    Регистрирует бота сигналов по золоту в Планировщике задач Windows (запуск при входе).
#>
$ErrorActionPreference = "Stop"
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$taskName = "GoldSignalBot"

$candidates = @(
    (Join-Path $dir "..\..\..\..\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"),
    "C:\Users\admin\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe",
    (Get-Command pythonw -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -ErrorAction SilentlyContinue)
)

$pythonw = $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $pythonw) {
    Write-Host "Не найден pythonw.exe. Укажите путь к Python вручную." -ForegroundColor Red
    exit 1
}
$pythonw = (Resolve-Path -LiteralPath $pythonw).Path

$config = Join-Path $dir "config.json"
if (-not (Test-Path $config)) {
    Write-Host "Нет config.json — запустите бота один раз вручную." -ForegroundColor Red
    exit 1
}
$cfg = Get-Content $config -Raw | ConvertFrom-Json
if (-not $cfg.telegram_token -and -not $env:TELEGRAM_BOT_TOKEN) {
    Write-Host "В config.json не заполнен telegram_token. Бот не сможет подключиться." -ForegroundColor Yellow
    $answer = Read-Host "Продолжить? (y/n)"
    if ($answer -ne "y") { exit 1 }
}

if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$dir\bot.py`"" -WorkingDirectory $dir
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Days 365)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "Telegram-бот сигналов по золоту (H1)" | Out-Null

Write-Host "Задача '$taskName' создана." -ForegroundColor Green
Write-Host "Python: $pythonw"
Write-Host "Запустить сейчас: Start-ScheduledTask -TaskName $taskName"
Write-Host "Смотреть логи:   Get-Content '$dir\bot.log' -Tail 30 -Wait"
