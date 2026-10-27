# Используем официальный легкий образ Python
FROM python:3.11-slim

# Логи сразу в stdout (docker logs), без .pyc
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Приложение работает не от root: отдельный пользователь с фиксированным uid
RUN groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости и ставим их (версии закреплены в requirements.txt)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта (секреты, .env и логи исключены в .dockerignore)
COPY --chown=app:app . .

# Каталоги, куда приложению разрешена запись (остальная файловая система может быть read-only)
RUN mkdir -p /app/logs /app/backups /app/instance /app/static/avatars \
 && chown -R app:app /app/logs /app/backups /app/instance /app/static/avatars

USER app

# Открываем порт
EXPOSE 5000

# При старте применяем миграции БД (идемпотентно), затем запускаем Gunicorn
# с gevent-воркером для WebSockets
CMD ["sh", "-c", "flask --app app upgrade-db && exec gunicorn --worker-class gevent -w 1 -b 0.0.0.0:5000 app:app"]
