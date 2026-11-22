"""
Run Case Study 3 on its test data, check the results and write the Excel reports.

    * the brief's sample      -> expected colours 86 Green / 11 Yellow / 3 Red / 0 Blue
    * multi_fc_may_2025.csv   -> every FC-day compared with expected_scenarios.csv

Reports are written to outputs/case_study_3/<file>_report.xlsx (no database needed).

Usage:
    python scripts/case_study_3/evaluate.py
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # project root
sys.path.insert(0, str(ROOT))

from app.case_study_3.engine import evaluate_day, scenario_of  # noqa: E402
from app.case_study_3.ingest import read_fc_data  # noqa: E402
from app.case_study_3.insights import write_insight  # noqa: E402
from app.case_study_3.report import write_report  # noqa: E402

DATA = ROOT / "data" / "case_study_3"
OUT = ROOT / "outputs" / "case_study_3"
SAMPLE_EXPECTED = {"Red": 3, "Yellow": 11, "Green": 86, "Blue": 0}


def analyse(path: Path):
    data = read_fc_data(str(path))
    days = [evaluate_day(row, data.targets) for row in data.rows]
    for day in days:
        day.insight, day.action = write_insight(day)
    report = write_report(days, data.targets, data.warnings, OUT / f"{path.stem.replace(' ', '_')}_report.xlsx")
    return days, report


def main() -> int:
    failures = 0

    days, report = analyse(DATA / "Case Study 3.xlsx")
    colours = {c: sum(1 for d in days if d.colour.value == c) for c in SAMPLE_EXPECTED}
    ok = colours == SAMPLE_EXPECTED
    failures += not ok
    print(f"Brief's sample      {len(days):>4} FC-days  colours {colours}  {'OK' if ok else 'MISMATCH'}")
    print(f"                    report: {report.relative_to(ROOT)}")

    days, report = analyse(DATA / "multi_fc_may_2025.csv")
    by_key = {(d.fc, d.day.isoformat()): d for d in days}
    with open(DATA / "expected_scenarios.csv", newline="") as handle:
        expected = list(csv.DictReader(handle))
    wrong = [e for e in expected
             if by_key[(e["fc"], e["date"])].colour.value != e["expected_colour"]
             or (e["expected_scenario"] and scenario_of(by_key[(e["fc"], e["date"])]) != e["expected_scenario"])]
    failures += len(wrong)
    print(f"Multi-FC May 2025   {len(days):>4} FC-days  {len(expected) - len(wrong)}/{len(expected)} match expected  "
          f"{'OK' if not wrong else 'MISMATCH'}")
    print(f"                    scenarios: {dict(Counter(scenario_of(d) for d in days))}")
    print(f"                    report: {report.relative_to(ROOT)}")
    for item in wrong:
        print("    x", item)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
