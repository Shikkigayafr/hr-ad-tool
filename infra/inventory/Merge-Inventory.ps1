<#
.SYNOPSIS
    Собирает отчёт по результатам Collect-Inventory.ps1: computers.csv, programs.csv, summary.txt.

.DESCRIPTION
    Читает все *.json из папки, пропуская повреждённые. CSV с разделителем «;» и BOM — открываются в Excel без возни с кодировкой.

.PARAMETER InputPath
    Папка с JSON-файлами (та же, что -OutputPath у Collect-Inventory.ps1).

.PARAMETER ReportPath
    Куда сохранить отчёт. По умолчанию — подпапка report внутри InputPath.

.EXAMPLE
    .\Merge-Inventory.ps1 -InputPath \\server\inventory$
#>
[CmdletBinding()]
param(
    [string]$InputPath = (Join-Path $PSScriptRoot 'out'),
    [string]$ReportPath
)

$ErrorActionPreference = 'Stop'
if (-not $ReportPath) { $ReportPath = Join-Path $InputPath 'report' }
if (-not (Test-Path -LiteralPath $InputPath)) { throw "Папка не найдена: $InputPath" }
New-Item -ItemType Directory -Path $ReportPath -Force | Out-Null

$computers = New-Object System.Collections.Generic.List[object]
$programs  = New-Object System.Collections.Generic.List[object]
$skipped   = 0

foreach ($file in Get-ChildItem -LiteralPath $InputPath -Filter '*.json' -File) {
    try {
        $item = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        if (-not $item.ComputerName) { throw 'нет поля ComputerName' }
    }
    catch {
        Write-Warning "Пропущен $($file.Name): $($_.Exception.Message)"
        $skipped++
        continue
    }
    foreach ($p in @($item.Programs)) {
        if ($p -and $p.Name) {
            $programs.Add([pscustomobject]@{ ComputerName = $item.ComputerName; Name = $p.Name; Version = $p.Version; Publisher = $p.Publisher })
        }
    }
    $flat = $item | Select-Object * -ExcludeProperty Programs
    $flat | Add-Member -NotePropertyName ProgramsCount -NotePropertyValue @($item.Programs).Count -Force
    $computers.Add($flat)
}

if ($computers.Count -eq 0) { throw "В $InputPath нет ни одного корректного JSON" }

$computers | Sort-Object ComputerName | Export-Csv -LiteralPath (Join-Path $ReportPath 'computers.csv') -Delimiter ';' -NoTypeInformation -Encoding UTF8
$programs  | Sort-Object ComputerName, Name | Export-Csv -LiteralPath (Join-Path $ReportPath 'programs.csv') -Delimiter ';' -NoTypeInformation -Encoding UTF8
$programs | Group-Object Name | Sort-Object Count -Descending |
    Select-Object @{n = 'Programme'; e = { $_.Name } }, @{n = 'Computers'; e = { $_.Count } } |
    Export-Csv -LiteralPath (Join-Path $ReportPath 'programs_by_popularity.csv') -Delimiter ';' -NoTypeInformation -Encoding UTF8

# --- Сводка ---
function Count-Where($Items, [scriptblock]$Predicate) { @($Items | Where-Object $Predicate).Count }
function Format-Groups($Items, [scriptblock]$Key) {
    ($Items | Group-Object $Key | Sort-Object Count -Descending | ForEach-Object { "  {0,-45} {1}" -f $_.Name, $_.Count }) -join "`r`n"
}

$total     = $computers.Count
$inDomain  = Count-Where $computers { $_.PartOfDomain }
$home      = Count-Where $computers { $_.OsEdition -match 'Core' }          # Core = Home
$win10     = Count-Where $computers { $_.OsName -eq 'Windows 10' }
$lowRam    = Count-Where $computers { $_.RamGb -lt 8 }
$lowDisk   = Count-Where $computers { $_.SystemDiskFreeGb -ne $null -and $_.SystemDiskFreeGb -lt 15 }
$noLicense = Count-Where $computers { $_.LicenseStatus -ne 'Активирована' }
$win11ok   = Count-Where $computers { $_.Win11Readiness -match '^(Да|Вероятно|Уже)' }
$noAdmin   = Count-Where $computers { -not $_.RanAsAdmin }
$dates     = $computers | ForEach-Object { $_.CollectedAt } | Sort-Object

$summary = @"
ИНВЕНТАРИЗАЦИЯ ПК — СВОДКА
Данные собраны: $($dates[0]) … $($dates[-1])
Файлов прочитано: $total (пропущено повреждённых: $skipped)

ДОМЕН
  В домене:                          $inDomain из $total
  Не в домене (рабочая группа):      $($total - $inDomain)

WINDOWS
  Редакция Home (в домен не вводится): $home
  Windows 10 (поддержка закончилась 14.10.2025): $win10
  Готовы к Windows 11 / уже на ней:  $win11ok из $total

По редакциям и версиям:
$(Format-Groups $computers { "$($_.OsName) $($_.OsEdition) $($_.OsVersion)" })

ЖЕЛЕЗО
  ОЗУ меньше 8 ГБ:                   $lowRam
  Свободно на системном диске < 15 ГБ: $lowDisk

ЛИЦЕНЗИИ (только статус, для учёта)
  Не в статусе «Активирована»:       $noLicense
По типу лицензии:
$(Format-Groups $computers { $_.LicenseChannel })

КАЧЕСТВО ДАННЫХ
  Запущено без прав администратора (TPM/Secure Boot не определены): $noAdmin

Подробности: computers.csv, programs.csv, programs_by_popularity.csv
"@
[IO.File]::WriteAllText((Join-Path $ReportPath 'summary.txt'), $summary, (New-Object System.Text.UTF8Encoding($true)))
Write-Host $summary
Write-Host "`nОтчёт сохранён: $ReportPath" -ForegroundColor Green
