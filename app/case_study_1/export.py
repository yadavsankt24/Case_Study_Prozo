"""CSV export: one row per frame, in upload order. Columns are listed once, here."""

from __future__ import annotations

import csv
import io

CSV_COLUMNS = [
    "image_file", "status", "status_reason", "awb",
    "length_cm", "width_cm", "height_cm", "weight_kg", "volume_cm3",
    "location", "scan_time", "machine_id",
    "awb_as_read", "dimensions_as_read", "weight_as_read", "label_barcodes",
    "units_inferred", "confidence", "reviewed", "notes",
]


def record_to_row(record: dict) -> dict:
    """A stored record (MongoDB document) -> one CSV row."""
    row = {column: record.get(column) for column in CSV_COLUMNS}
    row["image_file"] = record.get("filename")
    row["label_barcodes"] = "; ".join(record.get("label_barcodes") or [])
    row["notes"] = "; ".join(record.get("notes") or [])
    row["units_inferred"] = "yes" if record.get("units_inferred") else "no"
    row["reviewed"] = "yes" if record.get("reviewed") else "no"
    return {k: ("" if v is None else v) for k, v in row.items()}


def records_to_csv(records: list[dict]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for record in records:
        writer.writerow(record_to_row(record))
    return buffer.getvalue()
