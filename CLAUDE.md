# HR → AD Панель (Эвостор)

Flask-панель, через которую HR создаёт учётные записи в Active Directory (и, при включении `SABY_ENABLED`, карточки в Saby/СБИС). Общаться с владельцем проекта (Карим, сисадмин) — **на русском**.

## Стек и запуск
- Python 3.11, Flask, Flask-SQLAlchemy (SQLite `instance/hr.db`), Flask-SocketIO, APScheduler, ldap3, pysaby.
- Локально: `python -m venv .venv`, `pip install -r requirements-dev.txt`, создать `.env` по `.env.example`, `flask --app app init-db` (`--demo` добавит тестового HR; пароли печатаются в консоль), `python app.py` (порт 5000).
- Docker: `docker compose up --build -d`, затем `docker exec -it hr_ad_panel flask --app app init-db`. `.env` передаётся через `env_file`. Прод: Gunicorn + gevent, 1 воркер. Healthcheck `/health`, autoheal.
- Бэкапы БД: `backup_utils.py`, ежедневно в 03:00, хранится 7 копий в `backups/`.
- Тесты: `python -m pytest` (только папка `tests/`, AD имитируется через `DRY_RUN`, БД в памяти).

## Структура
- `app.py` — маршруты (страницы, `/api/*`), логин, роли, SocketIO, CLI `init-db`.
- `models.py` — `User`, `Employee`, `ActionLog`, `LoginHistory`.
- `ad_utils.py` — `create_user`, `change_group`, `delete_user` через LDAPS (порт 636, `Tls(validate=CERT_NONE)`); `DRY_RUN` имитирует всё без подключения.
- `saby_utils.py`, `saby_config.py` — создание сотрудника в Saby; вызывается из `app.py` только при `SABY_ENABLED=true`.
- `templates/`, `static/` — Jinja, чистый JS, `style.css`. Все данные из API вставляются через `esc()` (определён в `base.html`).
- `tests/` — pytest. Корневые `test_*.py`, `get_saby_*.py`, `check_*.py` — разовые отладочные скрипты для боевого Saby, **не тесты** (pytest их не собирает, `pytest.ini`).

## Роли и права
- `admin` — всё, управляет пользователями панели (`/users`), создаёт Старших.
- `hr` — только свой отдел: создаёт Стажёр/Основной, удаляет только стажёров, не повышает.
- `manager` — только свой отдел: видит, повышает, удаляет, видит ленту отдела.
- Роль и отдел перечитываются из БД на каждый запрос (`before_request`), удалённый пользователь теряет сессию сразу.
- Группы AD: `Sbis_Stager`, `Sbis_Main`, `Sbis_Senior`.

## Флаги в `.env` (все выключены по умолчанию)
- `DRY_RUN` — не обращаться к AD.
- `SABY_ENABLED` — после AD создавать сотрудника в Saby (ошибка Saby не отменяет создание в AD).
- `AD_SYNC_CHANGES` — «Повысить»/«Удалить» меняют ещё и AD. **Код не проверялся на живом AD** — сначала тестовый стенд.
- `TRUST_PROXY`, `SESSION_COOKIE_SECURE`, `CORS_ORIGINS` — см. `.env.example`.

## Окружение и константы
- Домен AD: `corp.local` (`AD_DOMAIN`, `BASE_DN`, `GROUPS_OU` в `.env`); пользователи создаются в `OU=<отдел>,OU=Departments,<BASE_DN>`.
- Сервисная учётка `svc_hr` (права выданы через `dsacls`, см. `TROUBLESHOOTING.md`).
- Разработка идёт на ПК вне домена, поэтому для проверки без AD ставить `DRY_RUN=true`.
- Список отделов один: ключи `SABY_DEPARTMENTS` в `saby_config.py` (форма создания берёт его с сервера).
- CSRF: токен лежит в сессии и в `<meta name="csrf-token">`, `fetch` в `base.html` добавляет его в `X-CSRF-Token` ко всем POST/DELETE; сервер проверяет (`check_csrf`).
- Вход: блокировка по таблице `LoginHistory` (5 неудач на пару IP+логин за 30 мин, 30 на IP), cookie не используется.

## Известные ограничения Saby
- `sabyEmployee.UpdatePosition` работает с **кадровой** структурой и требует `organization`; управленческая (визуальное дерево) этим методом не заполняется.
- По документации `СБИС.ЗаписатьСотрудника`: если передан `НашаОрганизация`, подразделение ищется в юридической структуре, без него — в управленческой. Гипотеза для проверки на работе: убрать `НашаОрганизация` и использовать ID управленческой папки. Текущие ID отделов в `saby_config.py` получены с фильтром по организации.
- `structureType` в `sabyDepartment`: 0 — управленческое, 1 — кадровое, 2 — оба (по справочнику; на практике API отвечал, что принимает 0 или 1 — перепроверить).

## Что ещё не сделано
- Реальная работа с AD и Saby не проверена (нет доступа вне офиса): `change_group`, `delete_user`, интеграция Saby в `/api/create`.
- Проверка сертификата LDAPS включается переменной `AD_CA_CERTS_FILE` (путь к PEM с сертификатом DC); пока она не задана, работает старый режим `CERT_NONE` с предупреждением. Включить на работе и проверить.
- `create_admin.py` — старая утилита; админа лучше заводить через `init-db`.

## Правила работы
- Не запускать скрипты, создающие/меняющие записи в боевом Saby или AD, без явного согласия владельца.
- `.env`, `instance/`, `backups/` в git не попадают — не коммитить.
- Новые ошибки и их решения дописывать в `TROUBLESHOOTING.md`, прогресс — в `PROGRESS.md`.
