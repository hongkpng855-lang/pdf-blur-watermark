FROM python:3.11-slim

WORKDIR /app

# Install system deps: fonts for watermark + PyMuPDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-dejavu-core \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway assigns PORT env var automatically
EXPOSE 8777

CMD gunicorn --bind 0.0.0.0:$PORT --workers 2 --timeout 120 pdf_blur_app:app
