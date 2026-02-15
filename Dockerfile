FROM python:3.12-slim

# Install system dependencies including WeasyPrint requirements
RUN apt-get update && apt-get install -y \
    libsndfile1 \
    curl \
    gcc \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    libgobject-2.0-0 \
    libcairo2 \
    libpangoft2-1.0-0 \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD python manage.py migrate && daphne -b 0.0.0.0 -p 8000 core.asgi:application
