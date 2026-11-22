"""
Generate Case Study 3 test data (deterministic seed).

Writes to data/case_study_3/:
    multi_fc_may_2025.csv     4 FCs x 31 days (Date, FC, Revenue, 6 cost lines)
    expected_scenarios.csv    the scenario planted in every FC-day + its expected colour
    fc_managers.csv           which manager receives which FC's digest (example addresses)
    bad_inputs/               files that must produce clear error / warning messages

How the scenarios are built (all percentages of revenue):
    clean          every cost inside its range with a safety margin -> CM1 66.8-69.2%, CM2 18.4-27.6% (Green)
    line_only      as clean, then ONE overhead-type line pushed 0.5-1.5 pts above max
                   -> cost flagged, CM1 / CM2 still inside tolerance (Green)
    yellow         Power & Overheads raised so CM2 lands at 12.5-14.5%
    cm2_breach     Manpower and Power far above max -> CM2 below 12% (Red)
    blue           FC Rent not booked (2% instead of ~16%) -> CM2 above 33% (Blue)

Fixed events (to demonstrate memory / trends in the digest):
    FC-Kolkata   27-29 May: three Red days in a row
    FC-Bengaluru 15 May: rent not booked (Blue)
"""

from __future__ import annotations

import csv
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]          # project root
sys.path.insert(0, str(ROOT))

from app.case_study_3 import rules  # noqa: E402

OUT = ROOT / "data" / "case_study_3"
FCS = ["FC-Gurgaon", "FC-Bhiwandi", "FC-Bengaluru", "FC-Kolkata"]
START, DAYS = date(2025, 5, 1), 31
MARGIN = 0.4
WEIGHTS = {"clean": 45, "line_only": 35, "yellow": 8, "cm2_breach": 8, "blue": 4}
FIXED = {("FC-Kolkata", date(2025, 5, d)): "cm2_breach" for d in (27, 28, 29)}
FIXED[("FC-Bengaluru", date(2025, 5, 15))] = "blue"
EXPECTED_LABEL = {"clean": "clean day", "line_only": "line-item-only breach", "cm2_breach": "CM2 breach",
                  "blue": "suspiciously high CM2"}


def clean_mix(rng: random.Random) -> dict[str, float]:
    return {line: rng.uniform(low + MARGIN, high - MARGIN) for line, (low, high) in rules.DEFAULT_TARGETS.items()}


def make_day(rng: random.Random, scenario: str) -> dict[str, float]:
    mix = clean_mix(rng)
    if scenario == "line_only":
        line = rng.choice(rules.CM2_COSTS)
        mix[line] = rules.DEFAULT_TARGETS[line][1] + rng.uniform(0.5, 1.5)
    elif scenario == "yellow":
        target_cm2 = rng.uniform(12.5, 14.5)
        gap = (100 - sum(mix.values())) - target_cm2
        mix["Power & Fuel"] += gap / 2
        mix["Overheads"] += gap / 2
    elif scenario == "cm2_breach":
        mix["Manpower"] = rng.uniform(31, 33)
        mix["Power & Fuel"] = rng.uniform(15, 16.5)
        mix["Overheads"] = rng.uniform(12.5, 13.5)
    elif scenario == "blue":
        mix["FC Rent"] = 2.0
    return mix


def colour_of(revenue: int, costs: dict[str, int]) -> str:
    cm2 = 100 * (revenue - sum(costs.values())) / revenue
    if cm2 < 12:
        return "Red"
    if cm2 > 33:
        return "Blue"
    return "Green" if 15 <= cm2 <= 30 else "Yellow"


def main() -> None:
    rng = random.Random(2025)
    OUT.mkdir(parents=True, exist_ok=True)
    names, weights = zip(*WEIGHTS.items())

    data_rows, expected_rows = [], []
    for fc in FCS:
        base_revenue = rng.randint(95_000, 140_000)
        for offset in range(DAYS):
            day = START + timedelta(days=offset)
            scenario = FIXED.get((fc, day)) or rng.choices(names, weights=weights)[0]
            revenue = int(base_revenue * rng.uniform(0.85, 1.15))
            costs = {line: round(revenue * share / 100) for line, share in make_day(rng, scenario).items()}
            data_rows.append([day.isoformat(), fc, revenue] + [costs[line] for line in rules.COST_LINES])
            expected_rows.append([fc, day.isoformat(), scenario, EXPECTED_LABEL.get(scenario, ""),
                                  colour_of(revenue, costs)])

    with open(OUT / "multi_fc_may_2025.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Date", "FC", "Revenue"] + rules.COST_LINES)
        writer.writerows(data_rows)
    with open(OUT / "expected_scenarios.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["fc", "date", "planted", "expected_scenario", "expected_colour"])
        writer.writerows(expected_rows)
    with open(OUT / "fc_managers.csv", "w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["fc", "manager", "email"])
        writer.writerow(["FC-01", "Sample FC Manager", "fc01.manager@example.com"])
        for fc in FCS:
            city = fc.split("-")[1]
            writer.writerow([fc, f"{city} FC Manager", f"{city.lower()}.fc@example.com"])

    write_bad_inputs(OUT / "bad_inputs")
    print(f"{len(data_rows)} FC-days written; scenarios:",
          {s: sum(1 for r in expected_rows if r[2] == s) for s in WEIGHTS})


def write_bad_inputs(folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    header = ["Date", "FC", "Revenue"] + rules.COST_LINES
    (folder / "header_only.csv").write_text(",".join(header) + "\n")
    (folder / "missing_overheads_column.csv").write_text(
        ",".join(header[:-1]) + "\n2025-05-01,FC-X,100000,26000,6000,11000,16000,6000\n")
    (folder / "some_bad_rows.csv").write_text("\n".join([
        ",".join(header),
        "2025-05-01,FC-X,100000,26000,6000,11000,16000,6000,11000",   # fine
        "2025-05-02,FC-X,0,26000,6000,11000,16000,6000,11000",        # zero revenue -> skipped
        "2025-05-03,FC-X,100000,abc,6000,11000,16000,6000,11000",     # text -> skipped
        "2025-05-04,FC-X,100000,-500,6000,11000,16000,6000,11000",    # negative -> skipped
        "31-02-2025,FC-X,100000,26000,6000,11000,16000,6000,11000",   # invalid date -> skipped
        "2025-05-05,FC-X,98000,25000,5500,10500,15500,5500,10500",    # fine
    ]) + "\n")
    (folder / "not_a_pnl_file.csv").write_text("Name,Department,Salary\nAnil,Ops,13520\n")


if __name__ == "__main__":
    main()
