FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if analyzer.py uses OpenCV/Pillow
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure the app knows it's in a container
ENV PYTHONUNBUFFERED=1

CMD ["python", "src/main.py"]