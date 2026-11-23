"""
Evaluate Case Study 1 against the answer keys.

Runs the same per-frame pipeline as the web app on:
    data/case_study_1/sample/      the 5 frames from the brief (hand-made answer key)
    data/case_study_1/generated/   41 generated frames, one or more per flag

Mode: with GEMINI_API_KEY set (and CS1_USE_VISION not false) the vision agent is used and
results are compared with `expected_status`; otherwise offline mode is compared with
`expected_status_offline` (scene problems can't be seen offline, and the report says so).

Prints status accuracy, value accuracy on OK rows and the number that matters most:
wrong values in OK rows. Writes outputs/case_study_1/<set>_results.csv.

    python scripts/case_study_1/evaluate.py            # mode from .env
    python scripts/case_study_1/evaluate.py --offline  # force offline mode
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.case_study_1.export import CSV_COLUMNS, record_to_row  # noqa: E402
from app.case_study_1.pipeline import process_frame  # noqa: E402
from app.case_study_1.service import display_name  # noqa: E402
from app.case_study_1.vision import create_vision_reader  # noqa: E402
from app.config import Settings  # noqa: E402

SETS = {"sample": ROOT / "data" / "case_study_1" / "sample", "generated": ROOT / "data" / "case_study_1" / "generated"}
OUT = ROOT / "outputs" / "case_study_1"
VALUE_TOLERANCE = {"length_cm": 0.06, "width_cm": 0.06, "height_cm": 0.06, "weight_kg": 0.006}


def load_key(folder: Path) -> list[dict]:
    with open(folder / "answer_key.csv", newline="") as handle:
        return list(csv.DictReader(handle))


def value_errors(result: dict, expected: dict) -> tuple[list[str], list[str]]:
    """(wrong, missing): clean columns that differ from the answer key, and expected values left blank."""
    wrong, missing = [], []
    got_awb = result.get("awb") or ""
    if got_awb != expected["awb"]:
        (missing if not got_awb else wrong).append(f"awb {got_awb or '-'} (expected {expected['awb'] or '-'})")
    for key, tolerance in VALUE_TOLERANCE.items():
        got, want = result.get(key), expected[key]
        if want == "" and got is None:
            continue
        if got is None:
            missing.append(f"{key} (expected {want})")
        elif want == "" or abs(float(got) - float(want)) > tolerance:
            wrong.append(f"{key} {got} (expected {want or '-'})")
    return wrong, missing


def evaluate_set(name: str, folder: Path, vision) -> dict:
    key = load_key(folder)
    status_column = "expected_status" if vision else "expected_status_offline"
    rows, statuses, problems = [], Counter(), []
    correct_status = ok_rows = ok_value_errors = ok_missing = scene_unchecked = 0
    started = time.time()
    for expected in key:
        result, _ = process_frame((folder / expected["image_file"]).read_bytes(), vision)
        data = result.to_dict()
        data["filename"] = display_name(expected["image_file"])
        rows.append(record_to_row(data))
        statuses[data["status"]] += 1

        if data["status"] == expected[status_column]:
            correct_status += 1
        else:
            problems.append(f"{expected['image_file']}: status {data['status']}, expected {expected[status_column]}"
                            f" ({data['status_reason']})")
        if data["status"] == "OK":
            ok_rows += 1
            if expected["expected_status"] != "OK":
                scene_unchecked += 1                      # offline: a scene problem the readers can't see
            else:
                wrong, missing = value_errors(data, expected)
                if wrong:
                    ok_value_errors += 1
                    problems.append(f"{expected['image_file']}: WRONG VALUE in OK row: {'; '.join(wrong)}")
                if missing:
                    ok_missing += 1
                    problems.append(f"{expected['image_file']}: value missing in OK row: {'; '.join(missing)}")

    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"{name}_results.csv", "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return {"name": name, "frames": len(key), "correct_status": correct_status, "ok_rows": ok_rows,
            "ok_value_errors": ok_value_errors, "ok_missing": ok_missing, "scene_unchecked": scene_unchecked, "statuses": statuses,
            "problems": problems, "seconds": time.time() - started}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--offline", action="store_true", help="do not call the vision agent")
    args = parser.parse_args()
    settings = Settings.from_env()
    vision = None if args.offline else create_vision_reader(
        settings.gemini_api_key, settings.cs1_vision_model, settings.cs1_use_vision, settings.cs1_vision_per_minute)
    print(f"Mode: {'vision agent (' + settings.cs1_vision_model + ')' if vision else 'offline (OCR + barcode)'}\n")

    all_good = True
    for name, folder in SETS.items():
        r = evaluate_set(name, folder, vision)
        print(f"{name:<10} {r['frames']:>3} frames  status correct {r['correct_status']}/{r['frames']}"
              f"  ·  OK rows {r['ok_rows']}  ·  wrong values in OK rows: {r['ok_value_errors']}"
              f"  ·  missing values: {r['ok_missing']}"
              f"  ·  {r['seconds']:.0f}s")
        print("           statuses: " + ", ".join(f"{k} {v}" for k, v in sorted(r["statuses"].items())))
        if r["scene_unchecked"]:
            print(f"           {r['scene_unchecked']} OK row(s) are scene problems the offline readers can't see "
                  "(expected in offline mode; the vision agent flags them)")
        for problem in r["problems"]:
            print("           - " + problem)
        print(f"           results: {(OUT / (name + '_results.csv')).relative_to(ROOT)}\n")
        all_good &= r["ok_value_errors"] == 0 and r["ok_missing"] == 0 and r["correct_status"] == r["frames"]
    print("OK" if all_good else "Differences found (listed above)")
    return 0 if all_good else 1


if __name__ == "__main__":
    sys.exit(main())
