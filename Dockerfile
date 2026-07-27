FROM python:3.11-slim

WORKDIR /app

# зависимости отдельно — кешируются между сборками
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# база хранится в volume, чтобы переживать перезапуски
VOLUME ["/app/data"]

CMD ["python", "bot.py"]
