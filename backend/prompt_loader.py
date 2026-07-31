"""Loads LLM system prompts from the repo-level storage/ folder as plain text.

Keeping prompt copy in text files instead of Python string constants lets it be
edited and reviewed as content rather than code, and gives every module one
place to load it from instead of each re-implementing its own file read.
"""

from __future__ import annotations

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR.parent / "storage"


def load_prompt(filename: str, fallback: str = "") -> str:
    try:
        return (STORAGE_DIR / filename).read_text(encoding="utf-8").strip()
    except Exception:
        return fallback.strip()
