# Инфраструктура AD как код

Скрипты разворачивают структуру Active Directory, нужную HR-панели, и базовые групповые политики. Всё описано в `structure.json`, поэтому **лабораторию и боевой домен настраивает один и тот же код**.

> ⚠️ Скрипты проверены только на синтаксис (парсер PowerShell). **Запускать сначала в лаборатории** (ВМ в Proxmox, которую можно снести), всегда с `-WhatIf`, и только потом на боевом домене. Набор делегируемых прав в `02-Configure-AD.ps1` составлен по документации и `TROUBLESHOOTING.md`, его минимальность нужно подтвердить на живом AD.

## Порядок

| Шаг | Скрипт | Где запускать | Что делает |
|---|---|---|---|
| 1 | `01-Install-ADDS.ps1` | чистый Windows Server, от администратора | роли AD DS + DNS, новый лес, перезагрузка |
| 2 | `02-Configure-AD.ps1` | контроллер домена или ПК с RSAT | OU отделов, группы `Sbis_*`, учётка `svc_hr`, права |
| 3 | `03-Create-Gpos.ps1` | контроллер домена или ПК с RSAT | GPO для рабочих станций, публикация скриптов в NETLOGON |

```powershell
.\01-Install-ADDS.ps1 -DomainName corp.local -WhatIf   # сначала посмотреть
.\01-Install-ADDS.ps1 -DomainName corp.local
# ...после перезагрузки:
.\02-Configure-AD.ps1 -WhatIf
.\02-Configure-AD.ps1
.\03-Create-Gpos.ps1
```

Скрипты 2 и 3 идемпотентны: повторный запуск ничего не дублирует.

## Что создаётся

```
corp.local
├── Departments/        ← OU каждого отдела (14 шт., список = saby_config.py)
├── Groups/             ← Sbis_Stager, Sbis_Main, Sbis_Senior
├── NewUsers/
├── Disabled/           ← сюда панель переносит отключённых сотрудников
├── Workstations/       ← компьютеры, на них действуют GPO
└── ServiceAccounts/    ← svc_hr
```

Права `svc_hr` (на OU отделов, `NewUsers` и `Disabled`): создание/удаление учёток, сброс пароля, включение/отключение (`userAccountControl`), снятие блокировки, «сменить пароль при входе» (`pwdLastSet`), запись `description`. На `Groups` — запись состава групп (`member`). Это ровно то, что делает панель: создание, отключение/возврат, сброс пароля, повышение.

## Подключение панели к созданному домену

После шага 2 скрипт подскажет значения для `.env`:

```
AD_USER=CORP\svc_hr
AD_DOMAIN=corp.local
BASE_DN=DC=corp,DC=local
GROUPS_OU=OU=Groups,DC=corp,DC=local
DISABLED_OU=OU=Disabled,DC=corp,DC=local
```
Пароль `svc_hr` — в `secrets/ad_password.txt`. Затем `DRY_RUN=false`, а `AD_SYNC_CHANGES=true` включайте после проверки на тестовых сотрудниках.

## Раздача программ при загрузке компьютера

1. `03-Create-Gpos.ps1` копирует `infra/deploy/` в `\\corp.local\NETLOGON\deploy` и создаёт пустую GPO **Workstations - Software deploy**.
2. Один раз в консоли GPMC: GPO → Изменить → Конфигурация компьютера → Политики → Конфигурация Windows → Сценарии → **Автозагрузка** → «Сценарии PowerShell» → Добавить: `\\corp.local\NETLOGON\deploy\Install-Software.ps1`.
3. Список программ — `infra/deploy/software.json` (winget-пакеты, а также `msi`/`exe` с сетевой папки). Скрипт идемпотентен: поставленное пропускает. Проверка без установки: `.\Install-Software.ps1 -DryRun`.
4. Лог на каждом ПК: `C:\ProgramData\ITDeploy\deploy.log`.

Ограничения: для `winget` нужен интернет и App Installer (Windows 10 21H2+/11); редакция **Home в домен не вводится** (см. `infra/inventory`, он покажет, где что стоит). Первый раз проверяйте на одном ПК в отдельной OU.

## Чего здесь нет намеренно
* Подключение стартап-скрипта к GPO через файлы SYSVOL — это хрупко; шаг выполняется вручную (см. выше).
* Политика паролей применяется только с ключом `-ApplyPasswordPolicy` — это решение руководства, а не админа.
* Резервное копирование DC: перед боевыми изменениями сделайте `Backup-GPO -All` и резерв состояния системы.
