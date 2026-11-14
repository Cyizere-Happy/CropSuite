"""Stage G demonstration: real farmer -> GAEZ -> NASA -> Rwanda catalogue ->
feasibility rules -> recommendation trace, for the Kayonza pilot, using only
data this codebase actually retrieved (data/gaez/kayonza_pilot.json from
scripts/fetch_gaez_pilot.py, and live/cached NASA POWER calls).

Run with: .venv/Scripts/python.exe demo/run_demo.py
"""
from __future__ import annotations

import sys
from dataclasses import replace
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fieldshift.crop_catalogue import load_catalogue
from fieldshift.gaez_adapter import make_gaez_lookup
from fieldshift.models import CropVariety, FarmerRequest, FieldLocation, HouseholdGoal
from fieldshift.nasa_power import compute_climate_evidence
from fieldshift.rotation_engine import build_recommendation

CATALOGUE = load_catalogue()
GAEZ_LOOKUP = make_gaez_lookup()
KAYONZA = FieldLocation(latitude=-1.883, longitude=30.644, name="Kayonza pilot field", has_irrigation=False)


def make_climate_lookup(planting_start: date, harvest_deadline: date):
    def lookup(crop_id: str, variety: CropVariety):
        try:
            return compute_climate_evidence(crop_id, KAYONZA.latitude, KAYONZA.longitude,
                                             planting_start, harvest_deadline, years_back=8)
        except RuntimeError as exc:
            print(f"    [climate lookup for {crop_id} failed: {exc}]")
            return None
    return lookup


def print_trace(label: str, request: FarmerRequest):
    print("\n" + "=" * 100)
    print(f"CASE: {label}")
    print("=" * 100)
    print("FARMER INPUT:")
    print(f"  field={request.field}  goal={request.household_goal.value}  "
          f"allow_outside={request.allow_outside_suggestions}")
    print(f"  desired_crops={request.desired_crops}  previous_crops={request.previous_crops}")
    print(f"  planting_window_start={request.planting_window_start}  harvest_deadline={request.harvest_deadline}")
    print(f"  budget_rwf={request.budget_rwf}")

    climate_lookup_fn = make_climate_lookup(request.planting_window_start, request.harvest_deadline)
    rec = build_recommendation(request, CATALOGUE, GAEZ_LOOKUP, climate_lookup_fn)

    for assessment in rec.assessments:
        variety = CATALOGUE[assessment.crop_id]
        print(f"\n  --- {assessment.crop_id.upper()} ({variety.variety_name}) ---")
        if assessment.gaez_evidence:
            g = assessment.gaez_evidence
            print(f"  GAEZ v5 evidence: index={g.suitability_index}  class='{g.suitability_class}'  "
                  f"attainable_yield={g.attainable_yield_kg_ha} kg/ha  scenario={g.scenario}")
        else:
            print("  GAEZ v5 evidence: NOT AVAILABLE")
        if assessment.climate_evidence:
            c = assessment.climate_evidence
            print(f"  NASA POWER evidence ({c.years_analyzed}): mean_rainfall={c.mean_total_rainfall_mm}mm  "
                  f"mean_longest_dry_spell={c.mean_longest_dry_spell_days}d  "
                  f"mean_tmax={c.mean_tmax_c}C  hot_days_mean={c.days_tmax_above_35c_mean}")
        else:
            print("  NASA POWER evidence: NOT AVAILABLE")
        print(f"  Rwanda catalogue: family={variety.family}  duration={variety.duration_days_min}-"
              f"{variety.duration_days_max}d  windows={variety.planting_windows}")
        print(f"  CHECKS:")
        for check in assessment.checks:
            flag = "FAIL" if not check.passed else ("CONCERN" if check.concern else "OK")
            print(f"    [{flag:7s}] {check.name}: {check.detail}")
        print(f"  => CLASSIFICATION: {assessment.classification.value}")
        if assessment.proposed_planting_window:
            print(f"  => proposed planting window: {assessment.proposed_planting_window}")
        if assessment.open_questions:
            print(f"  => open questions: {assessment.open_questions}")

    print(f"\n  PREFERRED CROP: {rec.preferred_crop_id}")
    print(f"  SHORTLIST: {rec.shortlist}")
    print(f"  FOLLOWING-CROP SUGGESTIONS: {rec.following_crop_suggestions}")
    print(f"  RATIONALE: {rec.decision_rationale}")
    return rec


def main():
    # ---- Stage G base case: maize-or-beans, previously maize, no irrigation,
    # household food goal, specified planting date and harvest deadline. ----
    base = FarmerRequest(
        field=KAYONZA,
        desired_crops=["maize", "beans"],
        allow_outside_suggestions=False,
        previous_crops=["maize"],
        planting_window_start=date(2026, 9, 20),
        harvest_deadline=date(2027, 1, 20),
        household_goal=HouseholdGoal.FOOD,
    )
    print_trace("BASE -- Kayonza farmer, maize-or-beans, prior maize, no irrigation, food goal", base)

    # ---- Rerun 1: tighter harvest deadline (planting deadline change) ----
    tight_deadline = replace(base, harvest_deadline=date(2026, 12, 15))
    print_trace("RERUN 1 -- harvest deadline pulled in to 2026-12-15 (was 2027-01-20)", tight_deadline)

    # ---- Rerun 2: crop choice narrowed to beans only ----
    beans_only = replace(base, desired_crops=["beans"])
    print_trace("RERUN 2 -- crop choice narrowed to beans only", beans_only)

    # ---- Rerun 3: irrigation becomes available ----
    irrigated_field = FieldLocation(latitude=KAYONZA.latitude, longitude=KAYONZA.longitude,
                                     name=KAYONZA.name, has_irrigation=True)
    irrigated = replace(base, field=irrigated_field)
    print_trace("RERUN 3 -- irrigation now available", irrigated)

    # ---- Rerun 4: household objective switches to income ----
    income_goal = replace(base, household_goal=HouseholdGoal.INCOME)
    print_trace("RERUN 4 -- household objective switched to income", income_goal)

    # ---- Rerun 5: outside-crop suggestions now permitted ----
    # (catalogue only has maize/beans for this pilot slice, so this rerun is
    # demonstrated by narrowing desired_crops to maize alone while allowing
    # outside suggestions -- beans should reappear as a candidate only now.)
    outside_ok = replace(base, desired_crops=["maize"], allow_outside_suggestions=True)
    print_trace("RERUN 5 -- desired_crops=[maize] only, but outside suggestions now permitted", outside_ok)

    # ---- Stage H: a second, distinct reproducible case (different prior crop + tight timing) ----
    case_2 = FarmerRequest(
        field=KAYONZA,
        desired_crops=["maize"],
        allow_outside_suggestions=True,
        previous_crops=["beans"],
        planting_window_start=date(2026, 11, 1),
        harvest_deadline=date(2027, 1, 10),
        household_goal=HouseholdGoal.INCOME,
        budget_rwf=50000,
    )
    print_trace("CASE 2 -- prior crop beans, wants maize for income, tight 70-day window, has a budget", case_2)

    # ---- Stage H: a third, distinct reproducible case (beans after beans, concern case) ----
    case_3 = FarmerRequest(
        field=KAYONZA,
        desired_crops=["beans"],
        allow_outside_suggestions=False,
        previous_crops=["beans"],
        planting_window_start=date(2026, 9, 15),
        harvest_deadline=date(2027, 1, 15),
        household_goal=HouseholdGoal.BOTH,
    )
    print_trace("CASE 3 -- beans after beans (no family rotation break), household wants both food and income", case_3)


if __name__ == "__main__":
    main()
