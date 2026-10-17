FROM mcr.microsoft.com/playwright/python:v1.48.0-jammy

ENV TZ=America/Edmonton PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ .

CMD ["python", "main.py"]
