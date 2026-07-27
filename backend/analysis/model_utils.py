"""Shared device-resolution helpers for the analysis pipeline.

Every stage picks its own model via config, but they all need the same
"cpu" / "cuda" / "cuda:N" / "auto" device string handling, so it lives here
once instead of being copy-pasted into each stage module.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def resolve_device_index(device_setting: str) -> int:
    """Map a device string to the int transformers.pipeline(device=...) expects.

    -1 means CPU; 0+ is a CUDA device index. "auto" resolves to CUDA device 0
    if torch reports CUDA available, otherwise CPU.
    """
    device = (device_setting or "cpu").strip().lower()
    if device == "auto":
        return 0 if _cuda_available() else -1
    if not device.startswith("cuda"):
        return -1
    parts = device.split(":", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return 0


def resolve_torch_device(device_setting: str) -> str:
    """Map a device string to the "cpu"/"cuda"/"cuda:N" string torch/.to() expects."""
    device = (device_setting or "cpu").strip().lower()
    if device == "auto":
        return "cuda:0" if _cuda_available() else "cpu"
    if device.startswith("cuda"):
        return device
    return "cpu"
