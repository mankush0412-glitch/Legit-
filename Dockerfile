FROM python:3.11-slim

  WORKDIR /app

  # Install system deps (needed for cryptg / Telethon)
  RUN apt-get update && apt-get install -y --no-install-recommends \
      gcc \
      libffi-dev \
      && rm -rf /var/lib/apt/lists/*

  # Upgrade pip + setuptools first (fixes Pillow build issues)
  RUN pip install --upgrade pip setuptools wheel

  COPY requirements.txt .
  RUN pip install --no-cache-dir -r requirements.txt

  COPY . .

  EXPOSE 10000

  CMD ["python", "-m", "bot.main"]
  