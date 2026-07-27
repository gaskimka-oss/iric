FROM python:3.12-slim

WORKDIR /app

# зависимости отдельно — кешируются между сборками
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Каталоги для базы. Если хостинг умеет монтировать постоянный диск —
# он подхватит один из них. Если нет, бот всё равно не потеряет данные:
# копия базы уходит в Telegram и поднимается оттуда при старте.
RUN mkdir -p /data /app/data
VOLUME ["/data", "/app/data"]

ENV PYTHONUNBUFFERED=1

# порт для healthcheck хостинга (бот отвечает 200 OK)
EXPOSE 8080

CMD ["python", "bot.py"]
