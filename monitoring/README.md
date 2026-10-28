# Мониторинг HR-панели

Панель отдаёт свои метрики на `/metrics` в формате Prometheus. Этот формат понимают **Zabbix 6.0+** и **Prometheus/Grafana**, поэтому настроено и то и другое. Стандартные шаблоны Zabbix (загрузка сервера, место на диске, статус ВМ) остаются как есть — это метрики **самого приложения**: что делают пользователи, жива ли связь с AD/Saby и БД, не подбирают ли пароль.

## 1. Токен

`/metrics` защищён токеном и **выключен (404), пока токен не задан**. Токен создаёт `python scripts/init_secrets.py` в `secrets/metrics_token.txt` (в Docker он подключён как secret). Без Docker — переменная `METRICS_TOKEN` в `.env`.

Проверка: `curl -H "Authorization: Bearer $(cat secrets/metrics_token.txt)" http://localhost:5000/metrics`

Токен принимается только в заголовке (в URL не принимается — адреса попадают в логи). В метриках нет логинов, ФИО и паролей; только числа и справочные значения (отделы, роли, названия операций).

## 2. Zabbix (6.0 и новее)

1. **Шаблон:** Data collection → Templates → Import → `monitoring/zabbix/template_hrpanel_by_http.yaml`.
2. **Хост:** создайте хост (например `hr-panel`), привяжите шаблон **HR AD Panel by HTTP**. Интерфейс не нужен (элементы — HTTP-агент).
3. **Макросы хоста:**
   * `{$HRPANEL.URL}` — адрес панели с точки зрения Zabbix-сервера, например `http://192.168.88.20:5000` (без `/` в конце);
   * `{$HRPANEL.METRICS.TOKEN}` — содержимое `secrets/metrics_token.txt`; тип макроса — **Secret text**.
4. Через минуту в Latest data появятся 25 элементов, ещё через минуту — скорости (они считаются по двум опросам).

**Что собирается (25 элементов):** доступность БД и время запроса; сотрудников работает/отключено, создано за 24 ч; входы (успешные за сутки, неудачные за 15 мин); запросы и ошибки 5xx в секунду; операции с AD (успешные / отказы / нет связи) и Saby; создание сотрудников и сбросы паролей в секунду; WebSocket-клиенты; память, CPU и дескрипторы процесса; флаги `DRY_RUN`, `AD_SYNC_CHANGES`, `SABY_ENABLED`.

**Триггеры (7):**

| Серьёзность | Условие |
|---|---|
| High | `/metrics` не отвечает 5 минут (панель остановлена, нет сети, неверный токен) |
| High | база данных недоступна |
| Average | нет связи с AD за последние 15 минут |
| Warning | AD отклоняет операции (нет прав, занятый логин) |
| Warning | неудачных входов за 15 мин ≥ `{$HRPANEL.LOGIN_FAILED.MAX}` (по умолчанию 20) — возможный подбор пароля |
| Warning | есть ответы 5xx |
| Warning | запрос к БД дольше `{$HRPANEL.DB_LATENCY.MAX}` (0.5 с) 5 минут |

Что ещё стоит добавить стандартными средствами Zabbix (агент на хосте): возраст свежего файла в `backups/` (`vfs.file.time`) — это страхует `db-backup`, который работает вне приложения; состояние контейнеров (`docker ps`) через шаблон Docker by Zabbix agent 2.

Если БД недоступна, приложение отдаёт только `hrpanel_database_up 0`, остальные бизнес-метрики пропадают — элементы временно станут «не поддерживается», это ожидаемо; сработает триггер «база данных недоступна».

## 3. Prometheus + Grafana (необязательно)

```bash
python scripts/init_secrets.py            # создаст и пароль Grafana: secrets/grafana_admin_password.txt
docker compose -f docker-compose.yml -f docker-compose.monitoring.yml up -d
```

* Grafana: http://127.0.0.1:3000 — логин `admin`, пароль из `secrets/grafana_admin_password.txt`. Дашборд **«HR → AD Панель»** (папка «HR-панель») уже подключён: статус БД, сотрудники, запросы и время ответа (p50/p95/p99), события пользователей, вход/блокировки, операции с AD и Saby, сотрудники по отделам, процесс приложения.
* Prometheus: http://127.0.0.1:9090 — цель `hrpanel` и 7 правил оповещений (`monitoring/prometheus/alerts.yml`, вкладка Alerts). Хранение — 30 дней.
* Порты открыты только на `127.0.0.1`. Для доступа с других ПК поставьте reverse-proxy с HTTPS, а не открывайте порты наружу.
* Дашборд хранится в репозитории (`monitoring/grafana/dashboards/hrpanel.json`) и подключается автоматически; правки в интерфейсе не сохраняются — меняйте JSON.
* Уведомления (Telegram, почта) в Prometheus требуют Alertmanager; проще настроить их в Grafana Alerting или оставить оповещения Zabbix.

## 4. Список метрик

| Метрика | Что показывает |
|---|---|
| `hrpanel_http_requests_total{method,endpoint,status}` | запросы по эндпоинтам Flask (не по URL — кардинальность низкая) |
| `hrpanel_http_request_duration_seconds` | время ответа (гистограмма) |
| `hrpanel_http_requests_handled_total`, `hrpanel_http_server_errors_total` | все запросы / ответы 5xx (без меток, всегда есть) |
| `hrpanel_audit_events_total{event}` | входы, блокировки, создание, отключение, сброс паролей и т.д. |
| `hrpanel_ad_operations_total{operation,result}` | операции с AD: `ok` / `fail` (AD отказал) / `error` (нет связи) |
| `hrpanel_ad_operation_duration_seconds`, `hrpanel_ad_last_success_timestamp_seconds` | время операций и когда была последняя успешная |
| `hrpanel_saby_*` | то же для Saby |
| `hrpanel_employees{status,role}`, `hrpanel_employees_by_department{department,status}` | сотрудники (читаются из БД при каждом опросе) |
| `hrpanel_employees_created_last_24h`, `hrpanel_panel_users{role}`, `hrpanel_panel_users_pending_password_change` | динамика и пользователи панели |
| `hrpanel_logins_recent{result,window}` | входы за 15 минут и 24 часа |
| `hrpanel_database_up`, `hrpanel_database_query_seconds` | доступность БД и задержка |
| `hrpanel_websocket_clients`, `hrpanel_http_requests_in_progress` | подключённые вкладки, запросы «в работе» |
| `hrpanel_feature_flag{flag}`, `hrpanel_info` | флаги интеграций, версия (`APP_VERSION`) |
| `process_*`, `python_*` | память, CPU, дескрипторы, сборка мусора процесса (в контейнере на Linux) |

Тест `tests/test_metrics.py` проверяет, что дашборд, правила и шаблон Zabbix ссылаются только на существующие метрики: переименуете метрику в коде и забудете обновить дашборд — тест упадёт.

## 5. Что проверено

На изолированном стенде (Docker): приложение на PostgreSQL → Prometheus (цель `up`, 7 правил) → Grafana (источник данных OK, все 29 запросов дашборда выполняются без ошибок) и Zabbix 6.0.49 (шаблон импортируется, 25 из 25 элементов собирают значения, 7 триггеров вычисляются; при остановленной БД сработал триггер «база данных недоступна»). Не проверялись Zabbix 7.0 (формат шаблона 6.0 в нём импортируется) и боевой AD/Saby — счётчики AD/Saby проверены только на имитации (`DRY_RUN`) и подмене ошибок в тестах.
