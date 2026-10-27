<#
.SYNOPSIS
    Ставит программы из software.json. Предназначен для запуска как скрипт автозагрузки компьютера (GPO) от SYSTEM.

.DESCRIPTION
    Идемпотентный: уже установленное пропускается, поэтому безопасно выполнять при каждой загрузке.
    Источники программ (поле "type" в software.json):
      winget — пакет из репозитория winget ("id"), нужен интернет и App Installer (Windows 10 21H2+/11);
      msi    — MSI с сетевой папки ("path"), тихая установка через msiexec;
      exe    — EXE с сетевой папки ("path") с тихими ключами ("args").
    Для msi/exe признак «уже установлено» — "detect": маска DisplayName в реестре (например "1C:Enterprise*").
    Лог: %ProgramData%\ITDeploy\deploy.log (ротация при 1 МБ).

.PARAMETER ConfigPath
    Путь к software.json (по умолчанию рядом со скриптом).

.PARAMETER DryRun
    Только показать, что было бы установлено.

.EXAMPLE
    .\Install-Software.ps1 -DryRun
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = (Join-Path $PSScriptRoot 'software.json'),
    [string]$LogPath = (Join-Path $env:ProgramData 'ITDeploy\deploy.log'),
    [switch]$DryRun
)

$ErrorActionPreference = 'Continue'   # ошибка одной программы не должна останавливать остальные

function Write-Log([string]$Message, [string]$Level = 'INFO') {
    $line = '{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message
    Write-Host $line
    try {
        $dir = Split-Path $LogPath
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        if ((Test-Path $LogPath) -and (Get-Item $LogPath).Length -gt 1MB) { Move-Item $LogPath "$LogPath.old" -Force }
        Add-Content -LiteralPath $LogPath -Value $line -Encoding UTF8
    }
    catch { }   # лог не должен ломать установку
}

function Test-Installed([string]$Pattern) {
    $paths = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*', 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*'
    [bool](Get-ItemProperty -Path $paths -ErrorAction SilentlyContinue | Where-Object { $_.DisplayName -like $Pattern } | Select-Object -First 1)
}

function Get-WingetPath {
    # От SYSTEM winget нет в PATH — ищем в каталоге App Installer, берём самую свежую версию
    $found = Get-ChildItem 'C:\Program Files\WindowsApps\Microsoft.DesktopAppInstaller_*_*__8wekyb3d8bbwe\winget.exe' -ErrorAction SilentlyContinue |
        Sort-Object { [version]($_.Directory.Name -split '_')[1] } -Descending | Select-Object -First 1
    if ($found) { return $found.FullName }
    $cmd = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    return $null
}

if (-not (Test-Path -LiteralPath $ConfigPath)) { Write-Log "Нет файла $ConfigPath" 'ERROR'; exit 1 }
$items = @(Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json)
Write-Log "Старт на $env:COMPUTERNAME, программ в списке: $($items.Count)$(if ($DryRun) { ' (DryRun)' })"

$winget = $null
$stats = @{ Installed = 0; Skipped = 0; Failed = 0 }

foreach ($item in $items) {
    $name = if ($item.name) { $item.name } else { $item.id }
    $code = $null   # остаётся пустым, если установка не запускалась (уже стоит / DryRun)
    try {
        switch ($item.type) {
            'winget' {
                if (-not $winget) { $winget = Get-WingetPath }
                if (-not $winget) { throw 'winget не найден на этом компьютере' }
                & $winget list --id $item.id --exact --accept-source-agreements 2>&1 | Out-Null
                if ($LASTEXITCODE -eq 0) { Write-Log "$name — уже установлено"; $stats.Skipped++; break }
                if ($DryRun) { Write-Log "$name — будет установлено (winget $($item.id))"; break }
                & $winget install --id $item.id --exact --silent --scope machine --accept-package-agreements --accept-source-agreements 2>&1 | Out-Null
                $code = $LASTEXITCODE
            }
            { $_ -in 'msi', 'exe' } {
                if (Test-Installed $item.detect) { Write-Log "$name — уже установлено"; $stats.Skipped++; break }
                if (-not (Test-Path -LiteralPath $item.path)) { throw "Установщик недоступен: $($item.path)" }
                if ($DryRun) { Write-Log "$name — будет установлено ($($item.path))"; break }
                if ($item.type -eq 'msi') {
                    $extra = if ($item.args) { $item.args } else { '/qn /norestart' }
                    $proc = Start-Process msiexec.exe -ArgumentList "/i `"$($item.path)`" $extra" -Wait -PassThru
                }
                else {
                    $proc = Start-Process -FilePath $item.path -ArgumentList $item.args -Wait -PassThru
                }
                $code = $proc.ExitCode
            }
            default { throw "Неизвестный тип '$($item.type)'" }
        }
        # break внутри switch лишь выходит из switch, поэтому «ничего не запускалось» проверяем здесь
        if ($null -eq $code) { continue }
        # 0 — успех, 3010 — успех, нужна перезагрузка
        if ($code -in 0, 3010) { Write-Log "$name — установлено (код $code)"; $stats.Installed++ }
        else { throw "код возврата $code" }
    }
    catch {
        Write-Log "$name — ОШИБКА: $($_.Exception.Message)" 'ERROR'
        $stats.Failed++
    }
}

Write-Log ("Итог: установлено {0}, пропущено {1}, ошибок {2}" -f $stats.Installed, $stats.Skipped, $stats.Failed)
exit 0   # статус скрипта автозагрузки на загрузку не влияет, подробности — в логе
