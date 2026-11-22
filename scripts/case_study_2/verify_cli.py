"""
Command-line verification (no web server, no database).

    python scripts/case_study_2/verify_cli.py --wagesheet W.xlsx --pf PF.pdf --esic ESIC.pdf --out report.xlsx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # project root
sys.path.insert(0, str(ROOT))

from app.shared.errors import InputError  # noqa: E402
from app.case_study_2.pipeline import VerificationPipeline  # noqa: E402
from app.case_study_2.report import ExcelReportWriter  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a wagesheet against PF and ESIC ECRs.")
    parser.add_argument("--wagesheet", required=True)
    parser.add_argument("--pf", required=True, help="PF ECR PDF")
    parser.add_argument("--esic", required=True, help="ESIC ECR PDF")
    parser.add_argument("--out", default="verification_report.xlsx")
    args = parser.parse_args()

    def show_progress(stage: str, percent: int, message: str) -> None:
        print(f"[{percent:3d}%] {message}")

    try:
        report = VerificationPipeline(progress=show_progress).run(args.wagesheet, args.pf, args.esic)
    except InputError as error:
        print(f"Input problem: {error.message}", file=sys.stderr)
        return 2

    path = ExcelReportWriter().write(report, args.out)
    print(json.dumps(report.summary(), indent=2))
    for warning in report.warnings:
        print("WARNING:", warning)
    print(f"Report written to {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
