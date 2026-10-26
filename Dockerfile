# Используем официальный легкий образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл с зависимостями и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код
COPY . .

# Открываем порт (для документации, сам по себе не открывает)
EXPOSE 5000

# Запускаем сервер через SocketIO (важно, так как у нас WebSockets)
CMD ["python", "app.py"]