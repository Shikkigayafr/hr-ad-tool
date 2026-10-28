<#
.SYNOPSIS
    Прописывает MTProto-прокси в Telegram Desktop. Запускать как скрипт ВХОДА ПОЛЬЗОВАТЕЛЯ (GPO),
    т.к. прокси хранится в профиле пользователя, а не машины.

.DESCRIPTION
    Однократно на пользователя: запускает Telegram со ссылкой tg://proxy?... — Telegram добавляет
    и включает прокси. Повторно не трогает (флаг в HKCU). Если Telegram ещё не установлен (ставится
    стартовым скриптом компьютера) — тихо выходит и попробует при следующем входе.
#>
$ErrorActionPreference = 'SilentlyContinue'

$flagKey = 'HKCU:\Software\ITDeploy'
if ((Get-ItemProperty -Path $flagKey -Name TelegramProxy -ErrorAction SilentlyContinue).TelegramProxy -eq 1) {
    return   # уже настроено у этого пользователя
}

$exe = @(
    "$env:ProgramFiles\Telegram Desktop\Telegram.exe",
    "${env:ProgramFiles(x86)}\Telegram Desktop\Telegram.exe",
    "$env:LOCALAPPDATA\Programs\Telegram Desktop\Telegram.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $exe) { return }   # Telegram ещё не установлен — настроим при следующем входе

$proxy = 'tg://proxy?server=nova.raccoonito.org&port=443&secret=ee128ff92541ef46962380176e292d31536e6f76612e726163636f6f6e69746f2e6f7267'
Start-Process -FilePath $exe -ArgumentList $proxy

New-Item -Path $flagKey -Force | Out-Null
Set-ItemProperty -Path $flagKey -Name TelegramProxy -Value 1
