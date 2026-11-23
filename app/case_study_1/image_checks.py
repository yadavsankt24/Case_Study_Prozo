"""
Quick checks before any reading: does the file open, is it big enough, and how bright
and sharp is it (used only to explain an UNREADABLE result, never to decide one).
"""

from __future__ import annotations

import io

from PIL import Image, ImageFilter, ImageOps, ImageStat

from app.case_study_1 import rules
from app.case_study_1.models import ImageCheck


def open_image(content: bytes) -> Image.Image:
    """Open image bytes and apply the phone/camera rotation stored in EXIF."""
    image = Image.open(io.BytesIO(content))
    image.load()
    return ImageOps.exif_transpose(image)


def check_image(content: bytes) -> tuple[ImageCheck, Image.Image | None]:
    try:
        image = open_image(content)
    except Exception:
        return ImageCheck(ok=False, problem="the file is not a readable image"), None
    width, height = image.size
    if min(width, height) < rules.MIN_IMAGE_SIDE_PX:
        return ImageCheck(ok=False, width=width, height=height,
                          problem=f"the image is too small to read ({width} x {height} px)"), None
    gray = image.convert("L")
    gray.thumbnail((800, 800))
    brightness = ImageStat.Stat(gray).mean[0]
    sharpness = ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]
    return ImageCheck(ok=True, width=width, height=height, brightness=round(brightness, 1),
                      sharpness=round(sharpness, 1)), image


def quality_hint(check: ImageCheck) -> str:
    """A short phrase for the reason text, e.g. 'the frame is very dark'."""
    if check.brightness < 25:
        return "the frame is very dark"
    if check.brightness > 235:
        return "the frame is overexposed"
    if check.sharpness < 15:
        return "the frame looks blurred"
    return ""


def make_thumbnail(image: Image.Image) -> bytes:
    thumb = image.convert("RGB")
    thumb.thumbnail((rules.THUMBNAIL_MAX_SIDE_PX, rules.THUMBNAIL_MAX_SIDE_PX))
    buffer = io.BytesIO()
    thumb.save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()
