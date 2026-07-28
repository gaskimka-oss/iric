FROM python:3.12-slim

WORKDIR /app

# зависимости отдельно — кешируются между сборками
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Постоянное хранилище Bothost — это /app/data.
# Папка исключена из синхронизации с Git и переживает пересборку.
# ВАЖНО: объявлять VOLUME нельзя — это ломает bind mount хостинга.
ENV DATA_DIR=/app/data
RUN mkdir -p /app/data && chmod 777 /app/data

ENV PYTHONUNBUFFERED=1

# порт для проверки живости (бот читает PORT из окружения)
EXPOSE 8080

CMD ["python", "bot.py"]
