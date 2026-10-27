# Используем официальный легкий образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости и ставим их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь код проекта
COPY . .

# Открываем порт
EXPOSE 5000

# Запускаем через Gunicorn (gevent-воркер) для WebSockets
CMD ["gunicorn", "--worker-class", "gevent", "-w", "1", "-b", "0.0.0.0:5000", "app:app"]