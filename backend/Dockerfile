# syntax=docker/dockerfile:1.7
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend

# Build deps cover psycopg and the document-extraction stack's native
# dependencies. tesseract-ocr(-eng) backs pytesseract for the OCR extraction
# path (scanned PDFs, images) - pytesseract itself is just a subprocess wrapper
# around it.
#
# Acquire::Retries covers the flaky-CDN case: a dropped connection to a Debian
# mirror mid-download otherwise fails the whole layer, and this layer is the
# expensive one to redo.
RUN apt-get -o Acquire::Retries=5 update && \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
    build-essential \
    curl \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    tesseract-ocr \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install -r requirements.txt

COPY . .

RUN mkdir -p /app/storage

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
