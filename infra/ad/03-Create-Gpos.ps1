<#
.SYNOPSIS
    Шаг 3. Создаёт групповые политики для рабочих станций, привязывает их к OU Workstations
    и публикует скрипты раздачи программ в NETLOGON.

.DESCRIPTION
    * "Workstations - Baseline": блокировка экрана при простое, отключение «рекомендуемых» приложений Windows.
    * "Workstations - Software deploy": пустая политика-оболочка. Скрипт установки программ вы подключаете
      вручную в консоли GPMC (3 клика, шаги — в infra/ad/README.md): подключение стартап-скриптов через
      файлы SYSVOL не автоматизируется намеренно, это хрупко и не проверено.
    * Копирует infra/deploy/* в \\<домен>\NETLOGON\deploy, чтобы компьютеры могли прочитать скрипт и список программ.
    Идемпотентный; поддерживает -WhatIf. Значения политик — разумные умолчания, согласуйте их до боевого запуска.

.PARAMETER InactivitySeconds
    Через сколько секунд простоя блокировать экран (по умолчанию 900 = 15 минут).

.EXAMPLE
    .\03-Create-Gpos.ps1 -WhatIf
#>
#Requires -Modules ActiveDirectory, GroupPolicy
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$StructurePath = (Join-Path $PSScriptRoot 'structure.json'),
    [string]$DeployPath = (Join-Path $PSScriptRoot '..\deploy'),
    [int]$InactivitySeconds = 900
)

$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory, GroupPolicy

$cfg = Get-Content -LiteralPath $StructurePath -Raw -Encoding UTF8 | ConvertFrom-Json
$domain = Get-ADDomain
$workstationsOu = "OU=$($cfg.ous.workstations),$($domain.DistinguishedName)"
if (-not (Get-ADOrganizationalUnit -Filter "distinguishedName -eq '$workstationsOu'" -ErrorAction SilentlyContinue)) {
    throw "Нет OU $workstationsOu. Сначала запустите 02-Configure-AD.ps1"
}

function Ensure-Gpo([string]$Name, [string]$Comment) {
    $gpo = Get-GPO -Name $Name -ErrorAction SilentlyContinue
    if ($gpo) { Write-Host "  = GPO уже есть: $Name" }
    elseif ($PSCmdlet.ShouldProcess($Name, 'Создать GPO')) {
        $gpo = New-GPO -Name $Name -Comment $Comment
        Write-Host "  + GPO создана: $Name" -ForegroundColor Green
    }
    $linkedNames = @((Get-GPInheritance -Target $workstationsOu).GpoLinks | ForEach-Object { $_.DisplayName })
    if ($gpo -and ($Name -notin $linkedNames)) {
        if ($PSCmdlet.ShouldProcess($Name, "Привязать к $workstationsOu")) {
            New-GPLink -Name $Name -Target $workstationsOu -LinkEnabled Yes | Out-Null
            Write-Host "  + привязана к $workstationsOu" -ForegroundColor Green
        }
    }
    return $gpo
}

Write-Host '== Групповые политики ==' -ForegroundColor Cyan
$baseline = Ensure-Gpo 'Workstations - Baseline' 'Базовые настройки рабочих станций (создано infra/ad/03-Create-Gpos.ps1)'
[void](Ensure-Gpo 'Workstations - Software deploy' 'Оболочка для скрипта раздачи программ (скрипт подключается в GPMC)')

if ($baseline -and $PSCmdlet.ShouldProcess($baseline.DisplayName, 'Записать параметры реестра')) {
    # Блокировка экрана при простое (политика «Интерактивный вход: предел простоя компьютера»)
    Set-GPRegistryValue -Name $baseline.DisplayName -Key 'HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' `
        -ValueName 'InactivityTimeoutSecs' -Type DWord -Value $InactivitySeconds | Out-Null
    # Не ставить «рекомендуемые» приложения и рекламу из магазина
    Set-GPRegistryValue -Name $baseline.DisplayName -Key 'HKLM\SOFTWARE\Policies\Microsoft\Windows\CloudContent' `
        -ValueName 'DisableWindowsConsumerFeatures' -Type DWord -Value 1 | Out-Null
    Write-Host "  + в Baseline записаны параметры (блокировка через $InactivitySeconds с, без consumer features)" -ForegroundColor Green
}

# --- Публикация скриптов раздачи в NETLOGON ---
Write-Host '== Скрипты раздачи программ ==' -ForegroundColor Cyan
$netlogon = "\\$($domain.DNSRoot)\NETLOGON\deploy"
$deploy = (Resolve-Path -LiteralPath $DeployPath).Path
if ($PSCmdlet.ShouldProcess($netlogon, "Скопировать $deploy")) {
    New-Item -ItemType Directory -Path $netlogon -Force | Out-Null
    Copy-Item -Path (Join-Path $deploy '*') -Destination $netlogon -Recurse -Force
    Write-Host "  + скопировано в $netlogon" -ForegroundColor Green
}

Write-Host @"

Дальше вручную (один раз), в консоли «Управление групповой политикой»:
  GPO 'Workstations - Software deploy' → Изменить → Конфигурация компьютера → Политики →
  Конфигурация Windows → Сценарии → Автозагрузка → вкладка «Сценарии PowerShell» → Добавить:
  $netlogon\Install-Software.ps1
Затем перенесите тестовый ПК в OU Workstations и перезагрузите его — программы из software.json поставятся при загрузке.
"@
