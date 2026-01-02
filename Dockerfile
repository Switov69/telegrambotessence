# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем системные зависимости
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Создаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем зависимости Python
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем остальные файлы
COPY . .

# Создаем директорию для базы данных
RUN mkdir -p /data && chmod 777 /data

# Устанавливаем переменные окружения
ENV PYTHONUNBUFFERED=1
ENV TZ=Europe/Moscow

# Команда запуска
CMD ["python", "bot.py"]