---
title: Strata Scraper
emoji: 🕷️
colorFrom: red
colorTo: yellow
sdk: docker
app_port: 7860
pinned: false
---

# Strata Scraper Backend

FastAPI service for the Strata Media dashboard's deep-crawl mode, plus the
scrape and chat endpoints. Runs on Hugging Face Spaces (Docker, Python 3.12 ->
the Crawl4AI engine is active when installed).

Endpoints:
- `GET /api/health`
- `GET /api/spider/stream?seed=&depth=&pages=` - SSE live crawl
- `GET /api/feeds`
- `POST /api/chat`

The dashboard points `VITE_SPIDER_URL` at this service.

