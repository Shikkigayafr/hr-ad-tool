<#
.SYNOPSIS
    Шаг 2. Создаёт структуру AD для HR-панели: OU, группы, сервисную учётку и делегирует ей права.

.DESCRIPTION
    Идемпотентный: повторный запуск ничего не дублирует. Структура берётся из structure.json,
    поэтому боевой домен настраивается тем же скриптом, что и лаборатория.
    ВАЖНО: набор делегируемых прав составлен по документации и по TROUBLESHOOTING.md и ещё не проверен
    на живом домене. Сначала прогоните в лаборатории (-WhatIf, затем без него) и проверьте из панели:
    создание, отключение/возврат, сброс пароля, повышение. Минимально достаточные права уточните там.

.PARAMETER StructurePath
    Путь к structure.json (по умолчанию рядом со скриптом).

.PARAMETER ServiceAccountPassword
    Пароль сервисной учётки. Если не передан — будет запрошен. Его же впишите в secrets/ad_password.txt панели.

.PARAMETER ApplyPasswordPolicy
    Дополнительно применить политику паролей домена из structure.json (по умолчанию НЕ применяется).

.EXAMPLE
    .\02-Configure-AD.ps1 -WhatIf
    .\02-Configure-AD.ps1
#>
#Requires -Modules ActiveDirectory
[CmdletBinding(SupportsShouldProcess)]
param(
    [string]$StructurePath = (Join-Path $PSScriptRoot 'structure.json'),
    [securestring]$ServiceAccountPassword,
    [switch]$ApplyPasswordPolicy
)

$ErrorActionPreference = 'Stop'
Import-Module ActiveDirectory

$cfg = Get-Content -LiteralPath $StructurePath -Raw -Encoding UTF8 | ConvertFrom-Json
$domain = Get-ADDomain
$root = $domain.DistinguishedName
if ($domain.DNSRoot -ne $cfg.domain.name) {
    Write-Warning "Текущий домен '$($domain.DNSRoot)' отличается от structure.json ('$($cfg.domain.name)'). Используется текущий."
}
$netbios = $domain.NetBIOSName

function Ensure-OU([string]$Name, [string]$ParentDn) {
    $dn = "OU=$Name,$ParentDn"
    $exists = Get-ADOrganizationalUnit -Filter "distinguishedName -eq '$dn'" -ErrorAction SilentlyContinue
    if ($exists) { Write-Host "  = OU уже есть: $dn" }
    elseif ($PSCmdlet.ShouldProcess($dn, 'Создать OU')) {
        New-ADOrganizationalUnit -Name $Name -Path $ParentDn -ProtectedFromAccidentalDeletion $true
        Write-Host "  + OU создана: $dn" -ForegroundColor Green
    }
    return $dn
}

function Grant([string]$TargetDn, [string]$Principal, [string[]]$Rights, [string]$Inherit) {
    foreach ($right in $Rights) {
        if ($PSCmdlet.ShouldProcess($TargetDn, "dsacls: $Principal -> $right (/I:$Inherit)")) {
            $output = & dsacls.exe $TargetDn /G "${Principal}:${right}" "/I:$Inherit" 2>&1
            if ($LASTEXITCODE -ne 0) { throw "dsacls завершился с ошибкой для '$right' на $TargetDn`n$output" }
        }
    }
}

# --- 1. OU ---
Write-Host '== Подразделения (OU) ==' -ForegroundColor Cyan
$ou = @{}
foreach ($key in 'departments', 'groups', 'newUsers', 'disabled', 'workstations', 'serviceAccounts') {
    $ou[$key] = Ensure-OU $cfg.ous.$key $root
}
foreach ($dept in $cfg.departments) { [void](Ensure-OU $dept $ou['departments']) }

# --- 2. Группы ролей ---
Write-Host '== Группы безопасности ==' -ForegroundColor Cyan
foreach ($group in $cfg.groups) {
    if (Get-ADGroup -Filter "Name -eq '$group'" -SearchBase $ou['groups'] -ErrorAction SilentlyContinue) {
        Write-Host "  = группа уже есть: $group"
    }
    elseif ($PSCmdlet.ShouldProcess($group, 'Создать группу')) {
        New-ADGroup -Name $group -SamAccountName $group -GroupScope Global -GroupCategory Security `
            -Path $ou['groups'] -Description 'Роль в Saby/СБИС, управляется HR-панелью'
        Write-Host "  + группа создана: $group" -ForegroundColor Green
    }
}

# --- 3. Сервисная учётка ---
Write-Host '== Сервисная учётка ==' -ForegroundColor Cyan
$svc = $cfg.serviceAccount.name
$svcUser = Get-ADUser -Filter "SamAccountName -eq '$svc'" -ErrorAction SilentlyContinue
if ($svcUser) {
    Write-Host "  = учётка уже есть: $svc"
    # Учётку, созданную вручную (обычно в CN=Users), переносим в ServiceAccounts — как на свежем домене
    if ($svcUser.DistinguishedName -notlike "*,$($ou['serviceAccounts'])" -and
        $PSCmdlet.ShouldProcess($svcUser.DistinguishedName, "Перенести в $($ou['serviceAccounts'])")) {
        Move-ADObject -Identity $svcUser.DistinguishedName -TargetPath $ou['serviceAccounts']
        Write-Host "  + перенесена в $($ou['serviceAccounts'])" -ForegroundColor Green
    }
}
elseif ($PSCmdlet.ShouldProcess($svc, 'Создать сервисную учётку')) {
    if (-not $ServiceAccountPassword) { $ServiceAccountPassword = Read-Host "Пароль для $svc" -AsSecureString }
    New-ADUser -Name $svc -SamAccountName $svc -UserPrincipalName "$svc@$($domain.DNSRoot)" `
        -Description $cfg.serviceAccount.description -Path $ou['serviceAccounts'] `
        -AccountPassword $ServiceAccountPassword -Enabled $true -PasswordNeverExpires $true -CannotChangePassword $true
    Write-Host "  + учётка создана: $svc" -ForegroundColor Green
}

# --- 4. Делегирование прав (dsacls) ---
Write-Host '== Делегирование прав сервисной учётке ==' -ForegroundColor Cyan
$principal = "$netbios\$svc"

# Права на пользователей: создание/удаление, сброс пароля, включение/отключение, снятие блокировки, описание
$userRights = @(
    'CCDC;user',                       # создавать и удалять учётки
    'CA;Reset Password;user',          # сброс пароля
    'WP;userAccountControl;user',      # включить / отключить
    'WP;lockoutTime;user',             # снять блокировку
    'WP;pwdLastSet;user',              # «сменить пароль при входе»
    'WP;description;user'              # причина отключения
)

# /I:S — права получают объекты ВНУТРИ OU (OU каждого отдела); /I:T — сама OU и всё внутри
Grant $ou['departments'] $principal $userRights 'S'
Grant $ou['newUsers']    $principal $userRights 'S'
Grant $ou['disabled']    $principal $userRights 'S'     # сюда переезжают отключённые; /I:S — права на user-объекты в OU (с типом объекта dsacls требует S, не T)
Grant $ou['groups']      $principal @('WP;member;group') 'S'   # состав групп ролей

# --- 4b. Перемещение учётки между OU (увольнение → Disabled и возврат) ---
# Проверено в лаборатории: одного CCDC;user мало. Перенос (LDAP modDN) требует ещё:
#  (а) запись свойств самого объекта (имя/расположение) — WP на user-объекты в обеих OU;
#  (б) create/delete child на САМОЙ OU Disabled, а не только на её содержимом
#      (dept-OU это право наследуют от Departments, а Disabled — лист, её надо делегировать напрямую).
Grant $ou['departments'] $principal @('WP;;user') 'S'
Grant $ou['disabled']    $principal @('WP;;user') 'S'
if ($PSCmdlet.ShouldProcess($ou['disabled'], 'dsacls: create/delete child user на самом контейнере Disabled')) {
    $out = & dsacls.exe $ou['disabled'] /G "${principal}:CCDC;user" 2>&1   # без /I — право ложится на сам контейнер
    if ($LASTEXITCODE -ne 0) { throw "dsacls (контейнер Disabled) завершился с ошибкой:`n$out" }
}

# --- 5. Политика паролей (по желанию) ---
if ($ApplyPasswordPolicy) {
    Write-Host '== Политика паролей домена ==' -ForegroundColor Cyan
    $p = $cfg.passwordPolicy
    if ($PSCmdlet.ShouldProcess($domain.DNSRoot, 'Изменить политику паролей домена')) {
        Set-ADDefaultDomainPasswordPolicy -Identity $domain.DNSRoot `
            -MinPasswordLength $p.minLength -ComplexityEnabled $p.complexity -PasswordHistoryCount $p.historyCount `
            -MaxPasswordAge ([TimeSpan]::FromDays($p.maxAgeDays)) `
            -LockoutThreshold $p.lockoutThreshold `
            -LockoutDuration ([TimeSpan]::FromMinutes($p.lockoutDurationMinutes)) `
            -LockoutObservationWindow ([TimeSpan]::FromMinutes($p.lockoutDurationMinutes))
        Write-Host '  + политика применена' -ForegroundColor Green
    }
}

Write-Host "`nГотово. Для панели в .env: AD_USER=$principal, BASE_DN=$root, AD_DOMAIN=$($domain.DNSRoot)," -ForegroundColor Cyan
Write-Host "DISABLED_OU=$($ou['disabled']); пароль учётки — в secrets/ad_password.txt." -ForegroundColor Cyan
