# Spider backend for Hugging Face Spaces (Docker).
# Python 3.12 so crawl4ai installs cleanly (3.13/3.14 have no wheels yet).
FROM python:3.12-slim

# Build deps so any source-built wheel (lxml etc.) succeeds, + curl for health.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-spider.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-spider.txt

COPY . .

# HF Spaces routes to this port (matches app_port in README.md).
ENV PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-7860}"]
