<#
.SYNOPSIS
    Собирает инвентарь ЭТОГО компьютера и сохраняет <ИМЯ_ПК>.json в указанную папку (например, общую).

.DESCRIPTION
    Только чтение: скрипт ничего не меняет в системе и не устанавливает программ.
    Работает в Windows PowerShell 5.1 и новее, права администратора НЕ обязательны:
    без них часть полей (TPM, Secure Boot) будет помечена как «нет данных».
    Каждый ПК пишет свой файл, поэтому одновременный запуск на десятках компьютеров безопасен.
    Сводный отчёт строит Merge-Inventory.ps1.

.PARAMETER OutputPath
    Куда сохранить JSON. По умолчанию — папка out рядом со скриптом.
    Для обхода по сети укажите общую папку: -OutputPath \\server\inventory$

.PARAMETER SkipPrograms
    Не собирать список установленных программ (быстрее, файл меньше).

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File .\Collect-Inventory.ps1 -OutputPath \\server\inventory$
#>
[CmdletBinding()]
param(
    [string]$OutputPath = (Join-Path $PSScriptRoot 'out'),
    [switch]$SkipPrograms
)

$ErrorActionPreference = 'Stop'
$SchemaVersion = 1

# Выполняет блок и при ошибке возвращает значение по умолчанию (часть данных недоступна без прав админа)
function Invoke-Safe([scriptblock]$Block, $Default = $null) {
    try { & $Block } catch { $Default }
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    (New-Object Security.Principal.WindowsPrincipal($identity)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-InstalledPrograms {
    $paths = @(
        'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
        'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    )
    Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName -and -not $_.SystemComponent -and -not $_.ParentKeyName } |
        Select-Object @{n = 'Name'; e = { $_.DisplayName.Trim() } },
                      @{n = 'Version'; e = { $_.DisplayVersion } },
                      @{n = 'Publisher'; e = { $_.Publisher } } |
        Sort-Object Name, Version -Unique
}

$licenseStatusNames = @{
    0 = 'Не активирована'; 1 = 'Активирована'; 2 = 'Льготный период (OOB)'; 3 = 'Льготный период (OOT)'
    4 = 'Не подлинная (льготный период)'; 5 = 'Уведомление'; 6 = 'Расширенный льготный период'
}

# --- Базовые данные ---
$cs   = Get-CimInstance Win32_ComputerSystem
$os   = Get-CimInstance Win32_OperatingSystem
$bios = Get-CimInstance Win32_BIOS
$cpu  = @(Get-CimInstance Win32_Processor)[0]
$ver  = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion'

$build = [int]$ver.CurrentBuild
if ($build -ge 22000)     { $osName = 'Windows 11' }
elseif ($build -ge 10240) { $osName = 'Windows 10' }
else                      { $osName = $os.Caption }
$displayVersion = if ($ver.DisplayVersion) { $ver.DisplayVersion } else { $ver.ReleaseId }

# --- Диск с системой ---
$sysDrive = Get-CimInstance Win32_LogicalDisk -Filter "DeviceID='$($env:SystemDrive)'"
$diskType = Invoke-Safe { (Get-PhysicalDisk | Sort-Object DeviceId | Select-Object -First 1).MediaType } 'нет данных'

# --- Загрузка, TPM ---
$isUefi     = Test-Path 'HKLM:\SYSTEM\CurrentControlSet\Control\SecureBoot\State'
$secureBoot = Invoke-Safe { if (Confirm-SecureBootUEFI) { 'Включён' } else { 'Выключен' } } 'нет данных'
$tpm        = Invoke-Safe { Get-Tpm } $null
$tpmVersion = 'нет данных'
if ($tpm) {
    if (-not $tpm.TpmPresent) { $tpmVersion = 'отсутствует' }
    else {
        $spec = Invoke-Safe { (Get-CimInstance -Namespace 'root\cimv2\Security\MicrosoftTpm' -ClassName Win32_Tpm).SpecVersion } $null
        $tpmVersion = if ($spec) { ($spec -split ',')[0].Trim() } else { 'есть (версия не определена)' }
    }
}

# --- Лицензия Windows (только статус, для учёта) ---
$license = Invoke-Safe {
    Get-CimInstance SoftwareLicensingProduct -Filter "ApplicationId='55c92734-d682-4d71-983e-d6ec3f16059f' AND PartialProductKey IS NOT NULL" |
        Select-Object -First 1
} $null
$licenseStatus  = if ($license) { $licenseStatusNames[[int]$license.LicenseStatus] } else { 'нет данных' }
$licenseChannel = 'нет данных'
if ($license -and $license.Description -match '(OEM_DM|OEM_SLP|RETAIL|VOLUME_KMSCLIENT|VOLUME_MAK|OEM|TIMEBASED|GVLK)') { $licenseChannel = $Matches[1] }

# --- Сеть ---
$net = Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=true' | Select-Object -First 1
$ip  = if ($net -and $net.IPAddress) { @($net.IPAddress | Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' })[0] } else { $null }

# --- Готовность к Windows 11 (приблизительно: процессор по списку Microsoft не проверяется) ---
$ramGb = [math]::Round($cs.TotalPhysicalMemory / 1GB, 1)
$diskGb = if ($sysDrive) { [math]::Round($sysDrive.Size / 1GB, 0) } else { 0 }
$blockers = New-Object System.Collections.Generic.List[string]
if ($ramGb -lt 3.8)           { $blockers.Add('ОЗУ < 4 ГБ') }
if ($diskGb -lt 64)           { $blockers.Add('Диск < 64 ГБ') }
if (-not $isUefi)             { $blockers.Add('Загрузка не UEFI') }
if ($tpmVersion -eq 'отсутствует' -or ($tpmVersion -match '^\d' -and $tpmVersion -notmatch '^2')) { $blockers.Add('Нет TPM 2.0') }
if (-not [Environment]::Is64BitOperatingSystem) { $blockers.Add('32-разрядная ОС') }
$tpmUnknown = $tpmVersion -eq 'нет данных'
if ($build -ge 22000)         { $win11 = 'Уже Windows 11' }
elseif ($blockers.Count -gt 0) { $win11 = 'Нет: ' + ($blockers -join ', ') }
elseif ($tpmUnknown)          { $win11 = 'Вероятно (TPM не проверен: запустите от администратора)' }
else                          { $win11 = 'Да (процессор не проверялся)' }

$result = [ordered]@{
    SchemaVersion   = $SchemaVersion
    CollectedAt     = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    RanAsAdmin      = Test-IsAdmin
    ComputerName    = $env:COMPUTERNAME
    LoggedOnUser    = $cs.UserName
    PartOfDomain    = [bool]$cs.PartOfDomain
    DomainOrWorkgroup = $cs.Domain
    Manufacturer    = $cs.Manufacturer
    Model           = $cs.Model
    SerialNumber    = $bios.SerialNumber
    Cpu             = ($cpu.Name -replace '\s+', ' ').Trim()
    CpuCores        = $cpu.NumberOfCores
    RamGb           = $ramGb
    SystemDiskGb    = $diskGb
    SystemDiskFreeGb = if ($sysDrive) { [math]::Round($sysDrive.FreeSpace / 1GB, 0) } else { $null }
    SystemDiskType  = "$diskType"
    OsName          = $osName
    OsEdition       = $ver.EditionID
    OsVersion       = $displayVersion
    OsBuild         = "$build.$($ver.UBR)"
    OsInstallDate   = $os.InstallDate.ToString('yyyy-MM-dd')
    LastBoot        = $os.LastBootUpTime.ToString('yyyy-MM-dd HH:mm')
    BootMode        = if ($isUefi) { 'UEFI' } else { 'Legacy BIOS' }
    SecureBoot      = $secureBoot
    TpmVersion      = $tpmVersion
    Win11Readiness  = $win11
    LicenseStatus   = $licenseStatus
    LicenseChannel  = $licenseChannel
    Ip              = $ip
    Mac             = if ($net) { $net.MACAddress } else { $null }
    Dhcp            = if ($net) { [bool]$net.DHCPEnabled } else { $null }
    DefenderEnabled = Invoke-Safe { (Get-MpComputerStatus).AntivirusEnabled } $null
}
if (-not $SkipPrograms) { $result['Programs'] = @(Get-InstalledPrograms) }

# --- Сохранение (сначала во временный файл, чтобы не оставить половину данных) ---
$json = $result | ConvertTo-Json -Depth 5
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
$fileName = "$($env:COMPUTERNAME).json"
try {
    if (-not (Test-Path -LiteralPath $OutputPath)) { New-Item -ItemType Directory -Path $OutputPath -Force | Out-Null }
    $target = Join-Path $OutputPath $fileName
    $tmp = "$target.tmp"
    [IO.File]::WriteAllText($tmp, $json, $utf8NoBom)
    Move-Item -LiteralPath $tmp -Destination $target -Force
    Write-Host "Готово: $target" -ForegroundColor Green
    Write-Host ("{0} | {1} {2} ({3}) | RAM {4} ГБ | в домене: {5} | Win11: {6}" -f $env:COMPUTERNAME, $osName, $ver.EditionID, $displayVersion, $ramGb, $result.PartOfDomain, $win11)
    exit 0
}
catch {
    # Общая папка недоступна — сохраняем локально, чтобы данные не потерялись
    $fallback = Join-Path $PSScriptRoot 'out'
    New-Item -ItemType Directory -Path $fallback -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $fallback $fileName), $json, $utf8NoBom)
    Write-Warning "Не удалось записать в '$OutputPath': $($_.Exception.Message). Сохранено локально: $fallback\$fileName"
    exit 2
}
