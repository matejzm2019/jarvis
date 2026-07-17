"""Safe process helpers shared by predefined tools."""

from __future__ import annotations

import os


def require_windows() -> None:
    """Reject Windows-only operations on other platforms."""
    if os.name != "nt":
        raise RuntimeError("This operation requires Windows")

