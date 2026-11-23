"""
Offline barcode reading (zxing-cpp). An exact, independent confirmation of the AWB
when the label's barcode is sharp enough to decode.
"""

from __future__ import annotations

import importlib.util
import logging

from PIL import Image

log = logging.getLogger(__name__)

MAX_UPSCALED_SIDE_PX = 6400   # labels are small in a sorter frame: thin bars often decode only at 2x


def barcodes_available() -> bool:
    return importlib.util.find_spec("zxingcpp") is not None


def read_barcodes(image: Image.Image) -> list[str]:
    """Every distinct barcode value found (1D and 2D), in the order found. Never raises."""
    try:
        import zxingcpp
    except ImportError:
        return []
    rgb = image.convert("RGB")
    found = _decode(zxingcpp, rgb)
    if not found and max(rgb.size) * 2 <= MAX_UPSCALED_SIDE_PX:
        found = _decode(zxingcpp, rgb.resize((rgb.width * 2, rgb.height * 2), Image.BICUBIC))
    return found


def _decode(zxingcpp, image: Image.Image) -> list[str]:
    found: list[str] = []
    try:
        for result in zxingcpp.read_barcodes(image):
            text = result.text.strip()
            if text and text not in found:
                found.append(text)
    except Exception as exc:  # unusual image modes, decoder errors
        log.warning("Barcode reading failed: %s", exc)
    return found
