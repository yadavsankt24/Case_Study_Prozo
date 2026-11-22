from __future__ import annotations

from app.case_study_2.parsers.esic_ecr import parse_esic_ecr
from app.case_study_2.parsers.pf_ecr import parse_pf_ecr
from app.case_study_2.parsers.wagesheet import read_wagesheet
from tests.conftest import SAMPLE_ESIC, SAMPLE_PF, SAMPLE_WAGESHEET


def test_sample_pf_ecr():
    doc = parse_pf_ecr(str(SAMPLE_PF))
    assert len(doc.members) == 11
    assert doc.header["wage_month"] == "AUG-2025"
    assert doc.header["total_epf_contribution"] == sum(m.ee_share for m in doc.members) == 16330
    vikram = next(m for m in doc.members if m.uan == "999912340011")
    assert (vikram.name_ecr, vikram.ee_share, vikram.epf_wages) == ("VIKRAM THAKUR", 1354, 13780)


def test_sample_esic_ecr():
    doc = parse_esic_ecr(str(SAMPLE_ESIC))
    assert len(doc.members) == 10
    assert doc.header["total_ip_contribution"] == sum(m.ip_contribution for m in doc.members) == 933
    assert next(m for m in doc.members if m.ip_number == "9912340008").name == "RENU SHARMA"


def test_sample_wagesheet():
    rows = read_wagesheet(str(SAMPLE_WAGESHEET))
    assert len(rows) == 12
    assert rows[0].uan == "999912340001" and rows[0].pf_amount == 1622 and rows[0].esic_amount == 102


def test_multi_page_ecr_without_repeated_headers(synthetic_data):
    folder = synthetic_data / "set_03_large_scale"
    doc = parse_pf_ecr(str(folder / "pf_ecr.pdf"))
    assert doc.log.pages > 40
    assert len(doc.members) == doc.header["total_members"]
    assert sum(m.ee_share for m in doc.members) == doc.header["total_epf_contribution"]


def test_wrapped_names_are_joined(synthetic_data):
    doc = parse_pf_ecr(str(synthetic_data / "set_02_messy_vendor_file" / "pf_ecr.pdf"))
    assert doc.log.wrapped_name_lines > 0
    assert all("  " not in m.name_ecr for m in doc.members)


def test_vendor_headers_and_messy_ids(synthetic_data):
    rows = read_wagesheet(str(synthetic_data / "set_02_messy_vendor_file" / "wagesheet.xlsx"))
    assert len(rows) == 220
    assert rows[0].row_number == 4           # title row + blank row + header row above
    assert sum(1 for r in rows if r.uan) >= 210
