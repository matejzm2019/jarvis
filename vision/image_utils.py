"""In-memory resize and JPEG encoding for local Ollama image input."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from PIL import Image

from config import VisionConfig
from utils.paths import PROJECT_ROOT


@dataclass(frozen=True, slots=True)
class PreparedImage:
    """Bounded JPEG payload plus dimensions used for coordinate validation."""

    data: bytes
    width: int
    height: int
    original_width: int
    original_height: int

    @property
    def base64(self) -> str:
        return base64.b64encode(self.data).decode("ascii")


def prepare_image(image: Image.Image, config: VisionConfig) -> PreparedImage:
    """Resize without upscaling and encode a screenshot as bounded RGB JPEG."""
    original_width, original_height = image.size
    prepared = image.convert("RGB")
    prepared.thumbnail((config.max_width, config.max_height), Image.Resampling.LANCZOS)
    output = io.BytesIO()
    prepared.save(output, format="JPEG", quality=config.jpeg_quality, optimize=True)
    width, height = prepared.size
    prepared.close()
    return PreparedImage(output.getvalue(), width, height, original_width, original_height)


def save_debug_image(image: PreparedImage, source: str) -> Path:
    """Persist a prepared screenshot only after explicit debug opt-in."""
    directory = PROJECT_ROOT / "debug_screenshots"
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    path = directory / f"{source}-{stamp}-{uuid4().hex[:8]}.jpg"
    path.write_bytes(image.data)
    return path
