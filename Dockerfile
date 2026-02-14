FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

WORKDIR /app

# Install system dependencies including those needed for torch and audio processing
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    libsndfile1 \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Install Python packages
# Note: If using GPU, ensure CUDA drivers are available on host
# and use nvidia-docker runtime
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Expose port for Django/Daphne
EXPOSE 8000

# Run with Daphne for WebSocket support
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "core.asgi:application"]