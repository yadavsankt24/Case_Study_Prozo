"""The format-free overlay parser on every layout seen so far."""

from __future__ import annotations

import pytest

from app.case_study_1.overlay_parser import (merge_passes, normalise_awb, parse_dimensions_text, parse_overlay,
                                             parse_weight, pick_awb, split_pairs)


@pytest.mark.parametrize("rows, awb, dims, weight, inferred", [
    # sample 1: panel below the photo, L without unit (shared from W / H), A.W in grams
    (["MID:44732", "L:39 A.W:2320g", "W:28.5cm V.W:32233.5g", "H:29 cm", "AWB:19108610769602"],
     "19108610769602", (39.0, 28.5, 29.0), 2.32, False),
    # sample 2: one string, no L/W/H words, zero-padded mm, no weight
    (["AWB_No: 19108610787894", "Dimension: 0208X0148X0163", "Volume: 005134809"],
     "19108610787894", (20.8, 14.8, 16.3), None, True),
    # sample 3: 'Barcode:' key, L-H-W order, weight without unit (grams)
    (["Barcode:19108610817924", "Dimension:L0213XH0148XW0178", "Weight:01190"],
     "19108610817924", (21.3, 17.8, 14.8), 1.19, True),
    # sample 4: separate keys with decimals, weight in gm
    (["AWB No: 19108610906662", "Length: 35.900 cm", "Width: 34.500 cm", "Height: 15.700 cm", "Weight: 2210.000 gm"],
     "19108610906662", (35.9, 34.5, 15.7), 2.21, False),
    # sample 5: unit inside the key
    (["AWB_NO :77873372404", "LENGTH(cm) : 21.40", "WIDTH(cm) : 16.40", "HEIGHT(cm) : 6.20", "WEIGHT(Kg) : 0.58"],
     "77873372404", (21.4, 16.4, 6.2), 0.58, False),
    # never seen in the samples
    (["Waybill No: 19108525920475", "Size: 54.1 x 14.3 x 25.4 cm", "Wt: 8.79 kg"],
     "19108525920475", (54.1, 14.3, 25.4), 8.79, False),
    (["ShipmentNo:19108573138457", "Dims（mm):582*307*341", "Gross Weight:5750 g"],    # full-width bracket from OCR
     "19108573138457", (58.2, 30.7, 34.1), 5.75, False),
])
def test_layouts(rows, awb, dims, weight, inferred):
    fields = parse_overlay(rows)
    assert fields.awb == awb
    assert fields.dimensions.as_cm() == dims
    assert fields.dimensions.unit_inferred is inferred
    assert (fields.weight.value if fields.weight else None) == weight
    assert fields.problems == []


def test_two_pairs_on_one_row_and_spilled_words():
    assert split_pairs("L:39 A.W:2320g") == [("L", "39"), ("A.W", "2320g")]
    # an unknown word before a known key goes back to the previous value
    assert split_pairs("LOCATION CODE : ITG AWB_NO : 77873372404") == [("LOCATION CODE", "ITG"), ("AWB_NO", "77873372404")]


def test_extra_fields_are_copied():
    fields = parse_overlay(["Location: Kolkata_Gateway(West Bengal)", "Time: 2025-05-17..20:41:11.008", "Sorter_ID: DA1"])
    assert (fields.location, fields.scan_time, fields.machine_id) == (
        "Kolkata_Gateway(West Bengal)", "2025-05-17..20:41:11.008", "DA1")


def test_label_text_does_not_fill_overlay_fields():
    rows = ["Sorter_ID: DA1", "Order: 212113 Qty: 1 Tracking ID: 19108193959674", "Tracking ID: 19108193959674"]
    assert parse_overlay(rows).machine_id == "DA1"
    assert parse_overlay(["Tracking ID: 19108193959674"]).machine_id is None


def test_value_on_the_row_below_its_key():
    assert parse_overlay(["AWB_No:", "19108610787894"]).awb == "19108610787894"


def test_awb_rules():
    assert normalise_awb("1910 8610-787894") == "19108610787894"
    assert normalise_awb("NOREAD") is None and normalise_awb("12345") is None
    assert pick_awb("1 19108193959674") == "19108193959674"          # stray OCR character ignored
    assert pick_awb("19108193959674 19108193959675") is None          # two candidates: never guess


def test_problems_are_reported():
    assert parse_overlay(["AWB_No: NOREAD"]).problems == ["AWB not in a valid format: 'NOREAD'"]
    assert "only some of length / width / height are printed" in parse_overlay(["W: 26 cm", "H: 9.7 cm"]).problems
    assert parse_overlay(["AWB: 19108610769602", "Barcode: 19108610769603"]).problems[0].startswith("different AWB")


def test_units():
    assert parse_dimensions_text("39 x 28.5 x 29 cm").as_cm() == (39.0, 28.5, 29.0)
    assert parse_dimensions_text("300 * 200 * 100").length.unit == "mm"             # > 250: must be mm
    assert parse_dimensions_text("12 x 10 x 4 in").as_cm() == (30.48, 25.4, 10.16)
    assert parse_weight("0.75").value == 0.75 and parse_weight("0.75").unit_inferred
    assert parse_weight("2 lb").value == 0.907
    assert parse_dimensions_text("39 x 28.5") is None


def test_merge_two_passes():
    first = parse_overlay(["W: 26 cm", "H: 9.7 cm", "AWB:19108788401148"])          # L missed by the first pass
    second = parse_overlay(["L: 58.9 cm", "W: 26 cm", "H: 9.7 cm", "AWB:19108788401148"])
    merged = merge_passes(first, second)
    assert merged.dimensions.as_cm() == (58.9, 26.0, 9.7) and merged.problems == []

    conflicting = merge_passes(parse_overlay(["AWB:19108788401148"]), parse_overlay(["AWB:19108788401149"]))
    assert conflicting.problems == ["two OCR passes read different AWBs (19108788401148, 19108788401149)"]
