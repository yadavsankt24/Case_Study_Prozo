from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "case_study_2" / "sample"
SYNTHETIC = ROOT / "data" / "case_study_2" / "synthetic"
CS3_DATA = ROOT / "data" / "case_study_3"

SAMPLE_WAGESHEET = SAMPLE / "Sample_Wagesheet_Aug25.xlsx"
SAMPLE_PF = SAMPLE / "PF ECR AUG-25 SAMPLE.pdf"
SAMPLE_ESIC = SAMPLE / "ESIC ECR AUG-25 SAMPLE.pdf"


@pytest.fixture(scope="session")
def synthetic_data() -> Path:
    """Generate the synthetic sets once if they are not in the repo yet."""
    if not (SYNTHETIC / "set_03_large_scale" / "pf_ecr.pdf").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "case_study_2" / "generate_test_data.py")], check=True)
    return SYNTHETIC
