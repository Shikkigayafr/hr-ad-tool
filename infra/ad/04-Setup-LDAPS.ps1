<#
.SYNOPSIS
    Шаг 4. Включает LDAPS на контроллере домена: сертификат с именем и IP сервера, выгрузка его для панели.

.DESCRIPTION
    Без сертификата контроллер не слушает 636, а панель работает только через LDAPS (пароли меняются только по TLS).
    Скрипт выпускает самоподписанный сертификат «Проверка подлинности сервера» для FQDN, короткого имени
    и IPv4-адресов контроллера (панель может подключаться по IP), кладёт его в LocalMachine\My и просит
    службу каталогов перечитать сертификат (без перезагрузки). Открытая часть выгружается в PEM —
    это файл для AD_CA_CERTS_FILE в .env панели.
    Идемпотентный: если подходящий действующий сертификат уже есть, новый не выпускается. Поддерживает -WhatIf.
    Если в домене есть свой центр сертификации (AD CS), лучше выдать сертификат им — тогда этот шаг не нужен,
    а в AD_CA_CERTS_FILE кладётся корневой сертификат CA.

.PARAMETER IPAddress
    IPv4-адреса для сертификата. По умолчанию — все адреса сервера, кроме 127.* и 169.254.*.

.PARAMETER ValidYears
    Срок действия нового сертификата (по умолчанию 5 лет).

.PARAMETER ExportPath
    Куда выгрузить открытую часть сертификата в PEM (по умолчанию рядом со скриптом: ldaps-<имя>.pem).

.PARAMETER ReplaceExisting
    Удалить из LocalMachine\My другие самоподписанные сертификаты этого сервера с назначением «Проверка
    подлинности сервера» (например, сделанные вручную без IP), чтобы служба каталогов не выбрала старый.

.EXAMPLE
    .\04-Setup-LDAPS.ps1 -WhatIf
    .\04-Setup-LDAPS.ps1 -ReplaceExisting
#>
#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess)]
param(
    [string[]]$IPAddress,
    [int]$ValidYears = 5,
    [string]$ExportPath,
    [switch]$ReplaceExisting
)

$ErrorActionPreference = 'Stop'
$serverAuth = '1.3.6.1.5.5.7.3.1'

$hostName = $env:COMPUTERNAME
$fqdn = [System.Net.Dns]::GetHostEntry('localhost').HostName
if ($fqdn -notlike "$hostName.*") {
    $fqdn = "$hostName.$((Get-CimInstance Win32_ComputerSystem).Domain)"
}
if (-not $IPAddress) {
    $IPAddress = Get-NetIPAddress -AddressFamily IPv4 |
        Where-Object { $_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*' } |
        ForEach-Object IPAddress
}
if (-not $ExportPath) { $ExportPath = Join-Path $PSScriptRoot "ldaps-$hostName.pem" }
Write-Host "Сервер: $fqdn  |  IP: $($IPAddress -join ', ')" -ForegroundColor Cyan

function Get-SanText([System.Security.Cryptography.X509Certificates.X509Certificate2]$Cert) {
    $ext = $Cert.Extensions | Where-Object { $_.Oid.Value -eq '2.5.29.17' }
    if ($ext) { $ext.Format($false) } else { '' }
}

function Test-Covers([System.Security.Cryptography.X509Certificates.X509Certificate2]$Cert) {
    $san = Get-SanText $Cert
    $hasEku = $Cert.EnhancedKeyUsageList.ObjectId -contains $serverAuth
    $names = @($fqdn) + $IPAddress
    $hasNames = -not ($names | Where-Object { $san -notmatch [regex]::Escape($_) })
    return ($hasEku -and $hasNames -and $Cert.HasPrivateKey -and $Cert.NotAfter -gt (Get-Date).AddDays(30))
}

# --- 1. Сертификат ---
Write-Host '== Сертификат LDAPS ==' -ForegroundColor Cyan
$mine = Get-ChildItem Cert:\LocalMachine\My | Where-Object {
    $_.EnhancedKeyUsageList.ObjectId -contains $serverAuth -and (Get-SanText $_) -match [regex]::Escape($fqdn)
}
$cert = $mine | Where-Object { Test-Covers $_ } | Sort-Object NotAfter -Descending | Select-Object -First 1

if ($cert) {
    Write-Host "  = подходящий сертификат уже есть: $($cert.Thumbprint) (до $($cert.NotAfter.ToString('d')))"
}
elseif ($PSCmdlet.ShouldProcess($fqdn, "Выпустить самоподписанный сертификат LDAPS на $ValidYears лет")) {
    $san = (@("DNS=$fqdn", "DNS=$hostName") + ($IPAddress | ForEach-Object { "IPAddress=$_" })) -join '&'
    $cert = New-SelfSignedCertificate -Subject "CN=$fqdn" -CertStoreLocation Cert:\LocalMachine\My `
        -TextExtension @("2.5.29.17={text}$san", "2.5.29.37={text}$serverAuth") `
        -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 -KeyExportPolicy NonExportable `
        -NotAfter (Get-Date).AddYears($ValidYears) -FriendlyName 'LDAPS (infra/ad/04-Setup-LDAPS.ps1)'
    Write-Host "  + выпущен: $($cert.Thumbprint) (до $($cert.NotAfter.ToString('d')))" -ForegroundColor Green
}

# --- 1b. Доверенный корень ---
# Самоподписанный сертификат сам себе корень. Если его нет в «Доверенных корневых»,
# Schannel не строит доверенную цепочку и НЕ выбирает его как учётные данные сервера
# (System-событие Schannel 36886, LDAPS не слушает). Поэтому кладём копию в LocalMachine\Root.
if ($cert -and $cert.Subject -eq $cert.Issuer) {
    $inRoot = Test-Path "Cert:\LocalMachine\Root\$($cert.Thumbprint)"
    if (-not $inRoot -and $PSCmdlet.ShouldProcess('LocalMachine\Root', 'Добавить самоподписанный сертификат в доверенные корневые')) {
        $rootStore = New-Object System.Security.Cryptography.X509Certificates.X509Store('Root', 'LocalMachine')
        $rootStore.Open('ReadWrite'); $rootStore.Add($cert); $rootStore.Close()
        Write-Host '  + добавлен в доверенные корневые (иначе служба каталогов его не выберет)' -ForegroundColor Green
    }
    elseif ($inRoot) { Write-Host '  = уже в доверенных корневых' }
}

# --- 2. Старые сертификаты ---
$old = $mine | Where-Object { $_.Subject -eq $_.Issuer -and (-not $cert -or $_.Thumbprint -ne $cert.Thumbprint) }
foreach ($o in $old) {
    if (-not $ReplaceExisting) {
        Write-Warning "Есть другой самоподписанный сертификат сервера: $($o.Thumbprint) (до $($o.NotAfter.ToString('d'))). Служба каталогов может выбрать его. Удалить: -ReplaceExisting"
    }
    elseif ($PSCmdlet.ShouldProcess($o.Thumbprint, 'Удалить старый самоподписанный сертификат')) {
        Remove-Item -LiteralPath "Cert:\LocalMachine\My\$($o.Thumbprint)"
        Write-Host "  - удалён старый: $($o.Thumbprint)" -ForegroundColor Yellow
    }
}

# --- 3. Служба каталогов перечитывает сертификат (без перезагрузки) ---
if ($cert -and $PSCmdlet.ShouldProcess('RootDSE', 'renewServerCertificate')) {
    $rootDse = [ADSI]'LDAP://localhost/RootDSE'
    $rootDse.Put('renewServerCertificate', 1)
    $rootDse.SetInfo()
    Write-Host '  + служба каталогов перечитала сертификат' -ForegroundColor Green
}

# --- 4. Выгрузка для панели ---
if ($cert -and $PSCmdlet.ShouldProcess($ExportPath, 'Выгрузить открытую часть в PEM')) {
    $b64 = [Convert]::ToBase64String($cert.RawData, 'InsertLineBreaks')
    $pem = "-----BEGIN CERTIFICATE-----`r`n$b64`r`n-----END CERTIFICATE-----`r`n"
    [System.IO.File]::WriteAllText($ExportPath, $pem, [System.Text.Encoding]::ASCII)
    Write-Host "  + выгружен: $ExportPath" -ForegroundColor Green
}

Write-Host @"

Дальше на ПК с панелью:
  1. Скопируйте $(Split-Path $ExportPath -Leaf) в папку проекта (например, secrets\ldaps-ca.pem).
  2. В .env: AD_CA_CERTS_FILE=secrets/ldaps-ca.pem
  3. Проверка: python scripts/check_ad.py  (должно быть «сертификат проверен»)
"@ -ForegroundColor Cyan
