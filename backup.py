FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    dpkg-dev binutils gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/backend
COPY ../agent /app/agent
COPY ../agent-linux /app/agent-linux
COPY ../agent-android /app/agent-android

WORKDIR /app/backend

RUN mkdir -p /app/agent-builds

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
