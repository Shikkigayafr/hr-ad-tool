<#
.SYNOPSIS
    Шаг 1. Устанавливает роли AD DS + DNS и создаёт новый лес (первый контроллер домена).

.DESCRIPTION
    Запускать на ЧИСТОМ Windows Server под локальным администратором. Перед запуском:
      * задайте имя сервера (Rename-Computer) и СТАТИЧЕСКИЙ IP — у контроллера домена адрес меняться не должен;
      * для безопасной проверки сначала запустите с -WhatIf.
    После создания леса сервер перезагрузится сам. Дальше — 02-Configure-AD.ps1.

.PARAMETER DomainName
    DNS-имя домена, например evostore.local (для боевого лучше поддомен реального домена: ad.example.ru).

.PARAMETER NetbiosName
    Короткое имя (до 15 символов), например EVOSTORE. Если не задано — берётся первая часть DomainName.

.PARAMETER SafeModeAdministratorPassword
    Пароль режима восстановления служб каталогов (DSRM). Если не передан — будет запрошен. Сохраните его в менеджере паролей.

.EXAMPLE
    .\01-Install-ADDS.ps1 -DomainName evostore.local -WhatIf
    .\01-Install-ADDS.ps1 -DomainName evostore.local
#>
#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [Parameter(Mandatory)][string]$DomainName,
    [string]$NetbiosName,
    [securestring]$SafeModeAdministratorPassword
)

$ErrorActionPreference = 'Stop'

if (-not $NetbiosName) { $NetbiosName = ($DomainName -split '\.')[0].ToUpper() }
if ($NetbiosName.Length -gt 15) { throw "NetBIOS-имя не должно быть длиннее 15 символов: $NetbiosName" }

if ((Get-CimInstance Win32_OperatingSystem).ProductType -eq 1) {
    throw 'Это клиентская Windows. Контроллер домена ставится только на Windows Server.'
}

# Предупреждение про DHCP: у DC должен быть статический адрес
$dhcp = Get-NetIPInterface -AddressFamily IPv4 | Where-Object { $_.Dhcp -eq 'Enabled' -and $_.ConnectionState -eq 'Connected' }
if ($dhcp) {
    Write-Warning ("У интерфейса(ов) {0} включён DHCP. Задайте статический IP и DNS перед созданием домена." -f (($dhcp | ForEach-Object InterfaceAlias) -join ', '))
}

if (-not $SafeModeAdministratorPassword) {
    $SafeModeAdministratorPassword = Read-Host 'Пароль DSRM (режим восстановления)' -AsSecureString
}

Write-Host "Домен: $DomainName  |  NetBIOS: $NetbiosName  |  Сервер: $env:COMPUTERNAME" -ForegroundColor Cyan

if ($PSCmdlet.ShouldProcess($env:COMPUTERNAME, "Установить AD DS и DNS, создать лес $DomainName")) {
    Install-WindowsFeature -Name AD-Domain-Services, DNS -IncludeManagementTools | Out-Null

    Install-ADDSForest `
        -DomainName $DomainName `
        -DomainNetbiosName $NetbiosName `
        -InstallDns `
        -SafeModeAdministratorPassword $SafeModeAdministratorPassword `
        -NoRebootOnCompletion:$false `
        -Force
}
