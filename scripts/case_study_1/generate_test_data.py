"""
Generate the Case Study 1 test set: synthetic sorter frames with known answers.

The 5 sample frames cannot cover every flag, so this builds frames on purpose:
the 5 overlay layouts seen in the samples plus 2 layouts never seen before, unit
quirks (mm / g with no unit), a wrong printed volume, an impossible weight, half
frames, two parcels, empty frames, a hand over the label, frames without overlay
(label only), blurred and dark frames, a corrupt file and a tiny image.

Courier names on the labels are fictional. Output (fixed seed, same result every run):
    data/case_study_1/generated/*.jpg|png
    data/case_study_1/generated/answer_key.csv

    python scripts/case_study_1/generate_test_data.py
"""

from __future__ import annotations

import csv
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "case_study_1" / "generated"
SEED = 20251122
FONT_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/Library/Fonts/Arial.ttf",
              "/System/Library/Fonts/Supplemental/Arial.ttf", "C:/Windows/Fonts/arial.ttf"]
MONO_PATHS = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "/System/Library/Fonts/Menlo.ttc",
              "C:/Windows/Fonts/consola.ttf"]
COURIERS = ["SWIFTLINE EXPRESS", "PARCELWAY", "NORTHSTAR CARGO", "QUICKDROP LOGISTICS"]


@dataclass
class Parcel:
    awb: str
    length: float      # cm
    width: float
    height: float
    weight: float      # kg


@dataclass
class Case:
    name: str
    expected_status: str
    expected_status_offline: str
    parcel: Optional[Parcel]
    what_it_tests: str
    expect_values: bool = True               # are AWB / values expected in the clean columns?
    expect_dims: bool = True
    expect_weight: bool = True
    image: Optional[Image.Image] = None
    raw_bytes: Optional[bytes] = None
    extra: dict = field(default_factory=dict)


# ---------------------------------------------------------------- drawing helpers

def font(size: int, mono: bool = False) -> ImageFont.ImageFont:
    for path in (MONO_PATHS if mono else FONT_PATHS):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def barcode_image(text: str, scale: int = 3) -> Image.Image:
    import zxingcpp
    if hasattr(zxingcpp, "create_barcode"):
        array = zxingcpp.create_barcode(text, zxingcpp.BarcodeFormat.Code128).to_image(scale=scale)
    else:  # zxing-cpp 2.x
        array = zxingcpp.write_barcode(zxingcpp.BarcodeFormat.Code128, text, width=len(text) * 22 * scale // 3, height=60 * scale // 3)
    return Image.fromarray(array).convert("RGB")


def belt(rng: random.Random, size=(1400, 900), shade: int = 28) -> Image.Image:
    """Dark conveyor-belt background with a little noise and two rails."""
    image = Image.effect_noise(size, 12).convert("RGB")
    image = Image.blend(Image.new("RGB", size, (shade, shade, shade + 2)), image, 0.18)
    draw = ImageDraw.Draw(image)
    for x in (int(size[0] * 0.18), int(size[0] * 0.92)):
        draw.rectangle([x, 0, x + 10, size[1]], fill=(55, 55, 58))
    return image


def label_image(rng: random.Random, awb: str, readable: bool = True) -> Image.Image:
    """A fictional courier label: courier name, barcode, tracking number, order lines."""
    label = Image.new("RGB", (430, 300), (240, 240, 236))
    draw = ImageDraw.Draw(label)
    draw.rectangle([0, 0, 429, 299], outline=(40, 40, 40), width=3)
    draw.text((16, 12), rng.choice(COURIERS), font=font(24), fill=(20, 20, 20))
    code = barcode_image(awb, 3)
    code = code.resize((min(400, code.width), 90))
    label.paste(code, (15, 55))
    draw.text((16, 152), f"Tracking ID: {awb}", font=font(22, mono=True), fill=(10, 10, 10))
    draw.text((16, 190), f"Order: {rng.randint(100000, 999999)}   Qty: 1", font=font(18), fill=(30, 30, 30))
    draw.text((16, 220), "Mode: SURFACE   COD: 0.00", font=font(18), fill=(30, 30, 30))
    if not readable:
        label = label.filter(ImageFilter.GaussianBlur(9))
    return label


def parcel_image(rng: random.Random, awb: str, size=(520, 420), readable_label: bool = True,
                 hand: bool = False) -> Image.Image:
    tone = rng.randint(120, 165)
    box = Image.new("RGBA", size, (tone, tone - 12, tone - 30, 255))
    draw = ImageDraw.Draw(box)
    draw.rectangle([0, size[1] // 2 - 18, size[0], size[1] // 2 + 18], fill=(tone - 25, tone - 32, tone - 45, 255))  # tape
    label = label_image(rng, awb, readable_label)
    box.paste(label, ((size[0] - label.width) // 2, (size[1] - label.height) // 2))
    if hand:
        draw.ellipse([size[0] * 0.18, size[1] * 0.22, size[0] * 0.78, size[1] * 0.86], fill=(196, 150, 120, 255))
        for i in range(4):
            x = size[0] * (0.22 + 0.13 * i)
            draw.rounded_rectangle([x, size[1] * 0.02, x + size[0] * 0.1, size[1] * 0.45], radius=25, fill=(190, 145, 116, 255))
    return box


def place(frame: Image.Image, item: Image.Image, center: tuple[int, int], angle: float) -> None:
    rotated = item.rotate(angle, expand=True, resample=Image.BICUBIC)
    frame.paste(rotated, (center[0] - rotated.width // 2, center[1] - rotated.height // 2), rotated)


def draw_overlay(frame: Image.Image, rows: list[str], colour=(235, 205, 40), size: int = 30, origin=(30, 24),
                 mono: bool = False) -> None:
    draw = ImageDraw.Draw(frame)
    for i, row in enumerate(rows):
        draw.text((origin[0], origin[1] + i * int(size * 1.35)), row, font=font(size, mono), fill=colour)


# ---------------------------------------------------------------- overlay layouts

def layout_rows(layout: str, p: Parcel, rng: random.Random, volume_override: Optional[float] = None) -> list[str]:
    mm = [round(v * 10) for v in (p.length, p.width, p.height)]
    if layout == "kolkata":      # one string, mm, zero padded, no L/W/H words, volume in mm3, no weight
        volume = volume_override or mm[0] * mm[1] * mm[2] * rng.uniform(0.985, 1.025)
        return ["Location: Kolkata_Gateway(West Bengal)", f"AWB_No:  {p.awb}",
                f"Dimension: {mm[0]:04d} X {mm[1]:04d} X {mm[2]:04d}", f"Volume:  {int(volume):09d}",
                "Time:  2025-05-17..20:41:11.008", "Sorter_ID: DA1"]
    if layout == "bilaspur":     # 'Barcode:', L-H-W order, weight in grams without unit
        return ["Location:Delhi_Bilaspur", f"Barcode:{p.awb}", f"Dimension:L{mm[0]:04d}XH{mm[2]:04d}XW{mm[1]:04d}",
                f"Weight:{round(p.weight * 1000):05d}", "Time:20250605034844086", "Sorter_ID:DA03"]
    if layout == "hoskote":      # separate keys, cm with decimals, volume cm3, weight gm
        volume = volume_override or p.length * p.width * p.height * rng.uniform(0.985, 1.015)
        return ["Location:   Bangalore_Hoskote_GW (Karnataka)", f"AWB No:   {p.awb}", f"Length:   {p.length:.3f} cm",
                f"Width:   {p.width:.3f} cm", f"Height:   {p.height:.3f} cm", f"R.Vol.:   {volume:.3f} cm (cubic)",
                f"Weight:   {p.weight * 1000:.3f} gm", "Time:   7/22/2025 8:43:19 AM"]
    if layout == "itg":          # unit inside the key
        return ["LOCATION CODE : ITG", f"AWB_NO   : {p.awb}", f"LENGTH(cm)   : {p.length:.2f}",
                f"WIDTH(cm)   : {p.width:.2f}", f"HEIGHT(cm)  : {p.height:.2f}", f"WEIGHT(Kg)  : {p.weight:.2f}",
                "DATETIME : 04-06-2025 08:43:33.827", "ID : 04"]
    if layout == "waybill":      # never seen in the samples
        return ["Hub: Pune_Chakan", f"Waybill No: {p.awb}", f"Size: {p.length:g} x {p.width:g} x {p.height:g} cm",
                f"Wt: {p.weight:.2f} kg", "Scan Time: 2025-08-02 11:05:40"]
    if layout == "shipment":     # never seen in the samples
        return ["Site: Hyderabad_Medchal", f"Shipment No: {p.awb}",
                f"Dims (mm): {mm[0]} * {mm[1]} * {mm[2]}", f"Gross Weight: {round(p.weight * 1000)} g",
                "Device ID: HYD-07"]
    raise ValueError(layout)


def panel_frame(rng: random.Random, p: Parcel) -> Image.Image:
    """Layout seen in sample 1: photo on top, light panel below with coloured L / W / H."""
    frame = Image.new("RGB", (600, 900), (232, 232, 232))
    photo = belt(rng, (540, 600), shade=95)
    place(photo, parcel_image(rng, p.awb, (470, 380)), (270, 300), rng.uniform(-6, 6))
    frame.paste(photo, (30, 70))
    draw = ImageDraw.Draw(frame)
    f = font(28, mono=True)
    draw.text((30, 18), f"MID: {rng.randint(10000, 99999)}", font=f, fill=(20, 20, 20))
    draw.text((30, 690), f"L: {p.length:g} cm", font=f, fill=(20, 140, 40))
    draw.text((30, 735), f"W: {p.width:g} cm", font=f, fill=(30, 60, 200))
    draw.text((30, 780), f"H: {p.height:g} cm", font=f, fill=(210, 40, 40))
    draw.text((330, 690), f"A.W: {round(p.weight * 1000)} g", font=f, fill=(20, 20, 20))
    draw.text((330, 735), f"V.W: {p.length * p.width * p.height:g} g", font=f, fill=(20, 20, 20))
    draw.text((30, 830), f"AWB: {p.awb}", font=f, fill=(60, 100, 190))
    return frame


# ---------------------------------------------------------------- frames

def random_parcel(rng: random.Random, awb_digits: int = 14) -> Parcel:
    awb = "19108" + "".join(str(rng.randint(0, 9)) for _ in range(awb_digits - 5)) if awb_digits == 14 \
        else "7787" + "".join(str(rng.randint(0, 9)) for _ in range(awb_digits - 4))
    return Parcel(awb, round(rng.uniform(12, 60), 1), round(rng.uniform(10, 45), 1),
                  round(rng.uniform(4, 35), 1), round(rng.uniform(0.2, 9.0), 2))


def standard_frame(rng: random.Random, p: Parcel, layout: str, *, offset=(0, 0), extra_parcel: Optional[Parcel] = None,
                   no_parcel: bool = False, hand: bool = False, overlay_rows: Optional[list[str]] = None,
                   readable_label: bool = True, shade: int = 28) -> Image.Image:
    frame = belt(rng, shade=shade)
    if not no_parcel:
        centre = (930 + offset[0], 540 + offset[1])
        place(frame, parcel_image(rng, p.awb, readable_label=readable_label, hand=hand), centre, rng.uniform(-12, 12))
    if extra_parcel:
        place(frame, parcel_image(rng, extra_parcel.awb, (460, 360)), (1150, 700), rng.uniform(-20, 20))
    rows = overlay_rows if overlay_rows is not None else layout_rows(layout, p, rng)
    if rows:
        colour = (240, 240, 240) if layout in ("kolkata", "bilaspur") else (235, 205, 40)
        draw_overlay(frame, rows, colour=colour, mono=layout in ("kolkata", "bilaspur"))
    return frame


def build_cases(rng: random.Random) -> list[Case]:
    cases: list[Case] = []
    layouts = ["kolkata", "bilaspur", "hoskote", "itg", "waybill", "shipment"]

    # 1. clean frames in every layout (3 each) + the panel layout
    for layout in layouts:
        for i in range(3):
            p = random_parcel(rng, 11 if layout == "itg" else 14)
            cases.append(Case(f"clean_{layout}_{i + 1}", "OK", "OK", p, f"clean frame, {layout} layout",
                              expect_weight=layout != "kolkata", image=standard_frame(rng, p, layout)))
    for i in range(3):
        p = random_parcel(rng)
        cases.append(Case(f"clean_panel_{i + 1}", "OK", "OK", p, "clean frame, panel-below layout (sample 1)",
                          image=panel_frame(rng, p)))

    # 2. checks that work offline
    for i, layout in enumerate(["kolkata", "hoskote"]):
        p = random_parcel(rng)
        wrong = (p.length * p.width * p.height * (1000 if layout == "kolkata" else 1)) * 1.4
        rows = layout_rows(layout, p, rng, volume_override=wrong)
        cases.append(Case(f"volume_mismatch_{i + 1}", "NEEDS_REVIEW", "NEEDS_REVIEW", p,
                          "printed volume 40% off L x W x H (a digit misread)", expect_values=False,
                          expect_weight=layout != "kolkata", image=standard_frame(rng, p, layout, overlay_rows=rows)))
    p = random_parcel(rng, 11)
    p_heavy = Parcel(p.awb, p.length, p.width, p.height, 250.0)
    cases.append(Case("weight_out_of_range", "NEEDS_REVIEW", "NEEDS_REVIEW", p_heavy, "weight 250 kg is outside 0.01-100 kg",
                      expect_values=False, image=standard_frame(rng, p_heavy, "itg")))

    # 3. scene problems (need the vision agent; offline they read as OK)
    for i, layout in enumerate(["itg", "bilaspur"]):
        p = random_parcel(rng, 11 if layout == "itg" else 14)
        cases.append(Case(f"parcel_partial_{i + 1}", "PARCEL_PARTIAL", "OK", p, "parcel half out of the frame",
                          expect_values=False, image=standard_frame(rng, p, layout, offset=(520, 300))))
    for i, layout in enumerate(["hoskote", "waybill"]):
        p, other = random_parcel(rng), random_parcel(rng)
        cases.append(Case(f"multiple_parcels_{i + 1}", "MULTIPLE_PARCELS", "OK", p, "two parcels in the frame",
                          expect_values=False, image=standard_frame(rng, p, layout, offset=(-120, -60), extra_parcel=other)))
    for i, layout in enumerate(["itg", "hoskote"]):
        p = random_parcel(rng, 11 if layout == "itg" else 14)
        cases.append(Case(f"view_obstructed_{i + 1}", "VIEW_OBSTRUCTED", "OK", p, "a hand covers the parcel and its label",
                          expect_values=False, image=standard_frame(rng, p, layout, hand=True)))
    for i in range(2):
        rows = ["Location: Kolkata_Gateway(West Bengal)", "AWB_No:  NOREAD", "Dimension: 0000 X 0000 X 0000",
                "Volume:  000000000", "Time:  2025-05-17..21:02:45.120", "Sorter_ID: DA1"]
        cases.append(Case(f"no_parcel_{i + 1}", "NO_PARCEL", "NEEDS_REVIEW", None,
                          "empty belt; machine printed NOREAD and zero dimensions", expect_values=False,
                          image=standard_frame(rng, random_parcel(rng), "kolkata", no_parcel=True, overlay_rows=rows)))

    # 4. no overlay: label only
    for i in range(2):
        p = random_parcel(rng, 11)
        cases.append(Case(f"label_only_{i + 1}", "OK", "OK", p, "no machine overlay; AWB from the label barcode",
                          expect_dims=False, expect_weight=False, image=standard_frame(rng, p, "itg", overlay_rows=[])))
    for i in range(2):
        p = random_parcel(rng, 11)
        cases.append(Case(f"unreadable_blurred_{i + 1}", "UNREADABLE", "UNREADABLE", p,
                          "no overlay and a blurred label", expect_values=False,
                          image=standard_frame(rng, p, "itg", overlay_rows=[], readable_label=False)))
    p = random_parcel(rng, 11)
    dark = standard_frame(rng, p, "itg", overlay_rows=[], shade=4).filter(ImageFilter.GaussianBlur(3)).point(lambda v: int(v * 0.06))
    cases.append(Case("unreadable_dark", "UNREADABLE", "UNREADABLE", p, "no overlay and a very dark frame",
                      expect_values=False, image=dark))

    # 5. duplicate AWB in one batch (both OK, with a note)
    p = random_parcel(rng)
    for i, layout in enumerate(["hoskote", "waybill"]):
        cases.append(Case(f"duplicate_awb_{i + 1}", "OK", "OK", p, "same AWB scanned twice (note on both)",
                          image=standard_frame(rng, p, layout)))

    # 6. broken files
    cases.append(Case("corrupt_file", "INVALID_IMAGE", "INVALID_IMAGE", None, "not an image (bytes of text)",
                      expect_values=False, raw_bytes=b"this is not an image\n" * 20, extra={"suffix": ".jpg"}))
    cases.append(Case("tiny_image", "INVALID_IMAGE", "INVALID_IMAGE", None, "120 x 90 px, too small to read",
                      expect_values=False, image=belt(rng, (120, 90))))
    return cases


def main() -> None:
    rng = random.Random(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*"):
        old.unlink()
    rows = []
    for number, case in enumerate(build_cases(rng), start=1):
        suffix = case.extra.get("suffix") or (".png" if number % 10 == 4 else ".jpg")   # a few PNGs, the rest JPG
        filename = f"{number:02d}_{case.name}{suffix}"
        if case.raw_bytes is not None:
            (OUT / filename).write_bytes(case.raw_bytes)
        elif suffix == ".png":
            case.image.save(OUT / filename)
        else:
            case.image.convert("RGB").save(OUT / filename, quality=88)
        p = case.parcel if case.expect_values else None
        rows.append({
            "image_file": filename,
            "expected_status": case.expected_status,
            "expected_status_offline": case.expected_status_offline,
            "awb": p.awb if p else "",
            "length_cm": p.length if p and case.expect_dims else "",
            "width_cm": p.width if p and case.expect_dims else "",
            "height_cm": p.height if p and case.expect_dims else "",
            "weight_kg": p.weight if p and case.expect_weight else "",
            "what_it_tests": case.what_it_tests,
        })
    with open(OUT / "answer_key.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} frames + answer_key.csv to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
