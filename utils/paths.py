"""Project path helpers."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"


def ensure_runtime_directories() -> None:
    """Create only Jarvis-owned runtime directories."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
