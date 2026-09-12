FROM python:3.12-slim

# ocrmypdf and tesseract back the OCR fallback path (PRD 6.1 step 3).
RUN apt-get update && apt-get install -y --no-install-recommends \
      ocrmypdf \
      tesseract-ocr \
      ghostscript \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data/statements

EXPOSE 8000
# Hosts such as Render assign the port through $PORT; exec keeps uvicorn as PID 1 so
# SIGTERM reaches it. Docker Compose overrides this command with an explicit port.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
