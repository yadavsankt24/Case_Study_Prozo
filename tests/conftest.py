from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SAMPLE = ROOT / "data" / "case_study_2" / "sample"
SYNTHETIC = ROOT / "data" / "case_study_2" / "synthetic"
CS3_DATA = ROOT / "data" / "case_study_3"
CS1_SAMPLE = ROOT / "data" / "case_study_1" / "sample"
CS1_GENERATED = ROOT / "data" / "case_study_1" / "generated"

SAMPLE_WAGESHEET = SAMPLE / "Sample_Wagesheet_Aug25.xlsx"
SAMPLE_PF = SAMPLE / "PF ECR AUG-25 SAMPLE.pdf"
SAMPLE_ESIC = SAMPLE / "ESIC ECR AUG-25 SAMPLE.pdf"


@pytest.fixture(scope="session")
def synthetic_data() -> Path:
    """Generate the synthetic sets once if they are not in the repo yet."""
    if not (SYNTHETIC / "set_03_large_scale" / "pf_ecr.pdf").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "case_study_2" / "generate_test_data.py")], check=True)
    return SYNTHETIC


@pytest.fixture(scope="session")
def cs1_generated() -> Path:
    """Generate the Case Study 1 test frames once if they are not in the repo yet."""
    if not (CS1_GENERATED / "answer_key.csv").exists():
        subprocess.run([sys.executable, str(ROOT / "scripts" / "case_study_1" / "generate_test_data.py")], check=True)
    return CS1_GENERATED
