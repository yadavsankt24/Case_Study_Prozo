"""
Run the verification on every test set and compare with its answer key.

For each folder containing wagesheet + PF ECR + ESIC ECR + expected_results.csv:
  * runs the same pipeline the web app uses
  * writes the Excel report to outputs/case_study_2/<set>/verification_report.xlsx
  * prints accuracy and every disagreement

Usage:
    python scripts/case_study_2/evaluate.py         # sample + all synthetic sets
    python scripts/case_study_2/evaluate.py --set data/case_study_2/synthetic/set_02_messy_vendor_file
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # project root
sys.path.insert(0, str(ROOT))

from app.case_study_2.pipeline import VerificationPipeline  # noqa: E402
from app.case_study_2.report import ExcelReportWriter  # noqa: E402

DEFAULT_SETS = [
    ROOT / "data" / "case_study_2" / "sample",
    ROOT / "data" / "case_study_2" / "synthetic" / "set_01_name_variants",
    ROOT / "data" / "case_study_2" / "synthetic" / "set_02_messy_vendor_file",
    ROOT / "data" / "case_study_2" / "synthetic" / "set_03_large_scale",
]


def find_inputs(folder: Path) -> tuple[Path, Path, Path]:
    def pick(patterns: list[str]) -> Path:
        for pattern in patterns:
            matches = sorted(folder.glob(pattern))
            if matches:
                return matches[0]
        raise FileNotFoundError(f"No file matching {patterns} in {folder}")

    return (pick(["wagesheet.xlsx", "*Wagesheet*.xlsx", "*.xlsx"]),
            pick(["pf_ecr.pdf", "PF*.pdf"]),
            pick(["esic_ecr.pdf", "ESIC*.pdf"]))


def evaluate(folder: Path) -> dict:
    wagesheet, pf, esic = find_inputs(folder)
    started = time.perf_counter()
    report = VerificationPipeline().run(str(wagesheet), str(pf), str(esic))
    seconds = time.perf_counter() - started

    out = ROOT / "outputs" / "case_study_2" / folder.name / "verification_report.xlsx"
    ExcelReportWriter().write(report, out)

    with open(folder / "expected_results.csv", newline="") as handle:
        expected = {int(r["row_number"]): r for r in csv.DictReader(handle)}

    disagreements, confusion = [], Counter()
    for emp in report.employees:
        exp = expected.get(emp.row.row_number)
        if exp is None:
            disagreements.append(f"row {emp.row.row_number}: not in answer key")
            continue
        for check, got, want, scenario in (("PF", emp.pf, exp["expected_pf_status"], exp["pf_scenario"]),
                                           ("ESIC", emp.esic, exp["expected_esic_status"], exp["esic_scenario"])):
            confusion[(check, want, got.status.value)] += 1
            if got.status.value != want:
                disagreements.append(f"row {emp.row.row_number} {check} [{scenario}] expected {want}, "
                                     f"got {got.status.value}: {got.reason}")

    checks = 2 * len(report.employees)
    correct = checks - len(disagreements)
    return {
        "set": folder.name,
        "employees": len(report.employees),
        "pages": f"PF {report.pf_log.pages} / ESIC {report.esic_log.pages}",
        "accuracy": round(100 * correct / checks, 2) if checks else 0,
        "seconds": round(seconds, 2),
        "reconciliation_ok": all(r.ok for r in report.reconciliation),
        "warnings": report.warnings,
        "disagreements": disagreements,
        "report": str(out.relative_to(ROOT)),
        "summary": report.summary(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--set", action="append", type=Path, help="test-set folder (repeatable)")
    args = parser.parse_args()

    failures = 0
    print(f"{'Test set':30} {'Employees':>9} {'Pages':>16} {'Accuracy':>9} {'Time(s)':>8}  Totals")
    for folder in args.set or DEFAULT_SETS:
        result = evaluate(folder)
        print(f"{result['set']:30} {result['employees']:>9} {result['pages']:>16} {result['accuracy']:>8}% "
              f"{result['seconds']:>8}  {'OK' if result['reconciliation_ok'] else 'CHECK'}")
        for line in result["disagreements"]:
            print("    x", line)
        for warning in result["warnings"]:
            print("    !", warning)
        failures += len(result["disagreements"])
    print("\nReports written to outputs/case_study_2/<set>/verification_report.xlsx")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
