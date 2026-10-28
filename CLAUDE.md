# HR → AD Панель (Эвостор)

Flask-панель, через которую HR создаёт учётные записи в Active Directory (и, при включении `SABY_ENABLED`, карточки в Saby/СБИС). Общаться с владельцем проекта (Карим, сисадмин) — **на русском**.

## Стек и запуск
- Python 3.11, Flask 3, Flask-SQLAlchemy, Flask-Migrate (Alembic), Flask-SocketIO, APScheduler, ldap3, pysaby. Версии закреплены в `requirements.txt`.
- БД: **PostgreSQL** в Docker, SQLite (`instance/hr.db`) для локальной разработки. Схема — только через миграции.
- Docker: `python scripts/init_secrets.py` → `docker compose up --build -d` → `docker exec -it hr_ad_panel flask --app app init-db`. Контейнер сам делает `upgrade-db` при старте. Gunicorn + gevent, 1 воркер. Healthcheck `/health`, autoheal, сервис `db-backup` (pg_dump раз в сутки, 7 копий). Контейнер приложения: пользователь `app` (uid 10001), `read_only`, `cap_drop: ALL`, `no-new-privileges`, лимиты памяти/процессов; запись только в именованные тома `avatars` и `logs` и в `/tmp` (tmpfs).
- CI: `.github/workflows/ci.yml` (тесты SQLite 3.11/3.12, тесты PostgreSQL, Docker-образ + /health + non-root, PowerShell-парсер); Dependabot раз в неделю.
- Локально: `pip install -r requirements-dev.txt`, `.env` по `.env.example`, `flask --app app init-db`, `python app.py`.
- Тесты: `python -m pytest` (только `tests/`, AD имитируется `DRY_RUN`, БД в памяти). На PostgreSQL: `TEST_DATABASE_URL=postgresql://... python -m pytest`. В образе приложение работает не от root — для pip в тестовом контейнере нужен `--user root`.
- Миграции: правка `models.py` → `flask --app app db migrate -m "..." --rev-id 000N` → проверить → `flask --app app db upgrade`. Ревизия `0001` = схема, которую создавал старый `create_all()` (с неё «усыновляются» старые БД). `0002` — индексы и `password_hash` 255, `0003` — поля отключения сотрудника и `must_change_password`. Булевы `server_default` в миграциях — только `sa.true()/sa.false()` (`sa.text('1')` ломает PostgreSQL).

## Структура
- `app.py` — тонкая точка входа (`gunicorn app:app`, `flask --app app`). Вся логика в пакете `hrpanel/`:
  - `__init__.py` — фабрика `create_app()`; `config.py` — настройки из окружения; `extensions.py` — db, socketio, migrate.
  - `security.py` — сессии, CSRF, блокировка входа, декораторы прав; `services.py` — журнал, оповещения, выборки по правам; `validators.py` — проверки, генератор паролей.
  - `logging_config.py` — JSON-логи, `audit()`, логирование запросов; `errors.py`, `sockets.py`, `cli.py` (`upgrade-db`, `init-db`).
  - `employee_service.py` — создание сотрудника (общее для формы и CSV-импорта) и разбор CSV; `blueprints/` — `pages`, `auth`, `dashboard`, `employees`, `panel_users`, `profile`, `system`.
- В корне остались: `models.py`, `ad_utils.py` (LDAPS: создание, группы, удаление, сброс пароля), `saby_utils.py`/`saby_config.py`, `backup_utils.py`, `secret_utils.py` (чтение секретов).
- `templates/`, `static/` — Jinja, чистый JS, `style.css`. Все данные из API вставляются через `esc()` (в `base.html`).
- `migrations/`, `scripts/` (`init_secrets.py`, `sqlite_to_postgres.py`), `tests/`.
- `monitoring/` — шаблон Zabbix 6.0, Prometheus (`prometheus.yml`, `alerts.yml`), Grafana (provisioning + дашборд `hrpanel.json`), `README.md` со списком метрик. Метрики: `hrpanel/metrics.py` (эндпоинт `/metrics` в `blueprints/system.py`, токен `METRICS_TOKEN`; без токена 404), вызовы AD/Saby оборачивает `hrpanel/integrations.py` (`call_ad`, `call_saby`) — новые операции с AD вызывать только через них. Дашборд и шаблон Zabbix сгенерированы скриптами (в репозитории только результат): правьте осторожно, `tests/test_metrics.py` проверяет, что они ссылаются лишь на существующие метрики.
- `infra/` — `inventory/` (инвентаризация ПК без домена), `ad/` (структура AD, GPO как код; `structure.json` обязан совпадать с `saby_config.py` — это проверяет тест), `deploy/` (раздача программ через GPO). Все `.ps1` — в UTF-8 **с BOM** (иначе Windows PowerShell 5.1 портит кириллицу), `.bat` — только ASCII.
- `scripts/saby_debug/` — разовые отладочные скрипты (`probe_*.py`, `get_*.py`) для **боевого** Saby, не тесты (`pytest.ini` собирает только `tests/`). Запускать вручную из корня проекта: `python scripts/saby_debug/get_ids.py`. `scripts/check_logs.py` — вывод журнала из БД.

## Роли и права
- `admin` — всё, управляет пользователями панели (`/users`), создаёт Старших.
- `hr` — только свой отдел: создаёт Стажёр/Основной, отключает/возвращает и сбрасывает пароль только стажёрам, не повышает.
- `manager` — только свой отдел: видит, повышает, отключает/возвращает, сбрасывает пароли, видит ленту отдела.
- Удаление сотрудника навсегда — только `admin` и только после отключения (`DELETE` отвечает 409 для работающего). Отключённые не попадают в статистику, с ними нельзя повысить/сбросить пароль.
- Пользователь панели, созданный админом (или чей пароль сбросил админ), имеет `must_change_password`: до смены доступны только профиль, смена пароля, выход (`PASSWORD_CHANGE_ALLOWED` в `security.py`).
- Роль и отдел перечитываются из БД на каждый запрос, удалённый пользователь теряет сессию сразу.
- Группы AD: `Sbis_Stager`, `Sbis_Main`, `Sbis_Senior`.

## Флаги в `.env` (все выключены по умолчанию)
- `DRY_RUN` — не обращаться к AD.
- `SABY_ENABLED` — после AD создавать сотрудника в Saby (ошибка Saby не отменяет создание в AD).
- `AD_SYNC_CHANGES` — «Повысить»/«Отключить»/«Вернуть»/«Удалить»/сброс пароля меняют ещё и AD (сброс пароля без флага работает только при `DRY_RUN`). **Код не проверялся на живом AD** — сначала тестовый стенд.
- `TRUST_PROXY`, `SESSION_COOKIE_SECURE`, `CORS_ORIGINS`, `LOG_*` — см. `.env.example`.

## Секреты и логи
- Секрет `NAME` ищется: файл `NAME_FILE` → `/run/secrets/name` → переменная `NAME`. Через Docker secrets идут `SECRET_KEY`, `POSTGRES_PASSWORD`, `AD_PASSWORD`, `SABY_PASSWORD` (файлы в `secrets/`, в git не попадают).
- Логи — JSON, одна строка = один объект; stdout + `logs/app.log` (ротация). Логгеры: `hrpanel.request`, `hrpanel.audit`. Пароли в логи не писать.
- CSRF: токен в сессии и в `<meta name="csrf-token">`, `fetch` в `base.html` добавляет `X-CSRF-Token` ко всем POST/DELETE.
- Вход: блокировка по таблице `LoginHistory` (5 неудач на пару IP+логин за 30 мин, 30 на IP). За proxy — `TRUST_PROXY=true`.

## Окружение и константы
- Домен AD: `corp.local` (`AD_DOMAIN`, `BASE_DN`, `GROUPS_OU` в `.env`); пользователи создаются в `OU=<отдел>,OU=Departments,<BASE_DN>` (имя `Departments` зашито в `ad_utils.py`).
- Сервисная учётка и домен сейчас тестовые (лаборатория на Proxmox), боевого AD ещё нет.
- Разработка идёт на ПК вне домена, поэтому для проверки без AD ставить `DRY_RUN=true`.
- Список отделов один: ключи `SABY_DEPARTMENTS` в `saby_config.py`.

## Известные ограничения Saby
- `sabyEmployee.UpdatePosition` работает с **кадровой** структурой и требует `organization`; управленческая (визуальное дерево) этим методом не заполняется.
- По документации `СБИС.ЗаписатьСотрудника`: если передан `НашаОрганизация`, подразделение ищется в юридической структуре, без него — в управленческой. Гипотеза для проверки на работе: убрать `НашаОрганизация` и использовать ID управленческой папки. Текущие ID отделов в `saby_config.py` получены с фильтром по организации.
- `structureType` в `sabyDepartment`: 0 — управленческое, 1 — кадровое, 2 — оба (по справочнику; на практике API отвечал, что принимает 0 или 1 — перепроверить).

## Что ещё не сделано
- Реальная работа с AD и Saby не проверена (нет доступа вне офиса): `change_group`, `delete_user`, `disable_user`, `enable_user`, `reset_password`, интеграция Saby в `/api/create`, а также набор прав в `infra/ad/02-Configure-AD.ps1` (проверить в лаборатории, уточнить минимально нужные).
- PowerShell-скрипты `infra/` проверены только парсером (не запускались): сначала лаборатория / один тестовый ПК.
- Windows Home в домен не вводится — `infra/inventory` покажет, где какая редакция.
- Проверка сертификата LDAPS включается переменной `AD_CA_CERTS_FILE` (путь к PEM с сертификатом DC); пока она не задана, работает режим `CERT_NONE` с предупреждением. Включить на работе и проверить.
- Шаблон Zabbix проверен на Zabbix 6.0.49 (импорт, сбор, триггеры); на 7.0 не проверялся. Особенности формата: триггеры — отдельный блок верхнего уровня; агрегация в Prometheus pattern — `function` + `sum`; `value_type` указывать всегда; `nodata()` требует хранимой истории элемента.
- `scripts/create_admin.py` — старая утилита; админа лучше заводить через `init-db`.

## Правила работы
- Не запускать скрипты, создающие/меняющие записи в боевом Saby или AD, без явного согласия владельца.
- `.env`, `secrets/`, `logs/`, `instance/`, `backups/` в git не попадают — не коммитить.
- Новые ошибки и их решения дописывать в `TROUBLESHOOTING.md`, прогресс — в `PROGRESS.md`.
