FROM python:3.11-slim

WORKDIR /app

# System deps for Pillow + cryptg
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev libjpeg-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["python", "-m", "bot.main"]
