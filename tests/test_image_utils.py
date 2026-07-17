import base64
import io

from PIL import Image

from config import VisionConfig
from vision.image_utils import prepare_image


def test_prepare_image_resizes_without_upscaling() -> None:
    large = Image.new("RGB", (3200, 1800), "navy")
    prepared = prepare_image(large, VisionConfig(max_width=1600, max_height=900, jpeg_quality=80))
    assert (prepared.width, prepared.height) == (1600, 900)
    assert (prepared.original_width, prepared.original_height) == (3200, 1800)
    decoded = Image.open(io.BytesIO(base64.b64decode(prepared.base64)))
    assert decoded.size == (1600, 900)

    small = prepare_image(Image.new("RGB", (200, 100)), VisionConfig())
    assert (small.width, small.height) == (200, 100)
