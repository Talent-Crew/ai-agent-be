FROM python:3.12-slim

# Install minimal system dependencies
RUN apt-get update && apt-get install -y \
    libsndfile1 \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
# Updated CMD in Dockerfile
CMD python manage.py migrate && daphne -b 0.0.0.0 -p 8000 core.asgi:application