FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV TZ=America/Edmonton PYTHONUNBUFFERED=1
# Base image is from 2024; refresh timezone data so America/Edmonton reflects
# Alberta's permanent UTC-6 (no fall-back from Nov 1, 2026).
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .

CMD ["python", "main.py"]
