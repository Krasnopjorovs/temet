FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -U pip setuptools wheel && pip install --no-cache-dir -r requirements.txt
COPY . .
ENV SE_EPHE_PATH=/app/ephe PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
