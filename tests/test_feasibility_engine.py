"""Unit tests for the deterministic feasibility engine.

These use constructed GaezEvidence/ClimateEvidence fixtures (not live
network calls) so the engine's branching logic is tested in isolation.
test_nasa_power_integration.py separately proves the live NASA POWER
pipeline produces the ClimateEvidence shape these tests assume.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fieldshift.crop_catalogue import load_catalogue
from fieldshift.feasibility_engine import assess_crop_plan, pick_preferred_crop
from fieldshift.models import (
    ClimateEvidence,
    Feasibility,
    FarmerRequest,
    FieldLocation,
    GaezEvidence,
    HouseholdGoal,
)

CATALOGUE = load_catalogue()
KAYONZA = FieldLocation(latitude=-1.883, longitude=30.644, name="Kayonza pilot field", has_irrigation=False)


def base_request(**overrides) -> FarmerRequest:
    defaults = dict(
        field=KAYONZA,
        desired_crops=["maize"],
        allow_outside_suggestions=False,
        previous_crops=["beans"],
        planting_window_start=date(2026, 9, 20),
        harvest_deadline=date(2027, 1, 20),
        household_goal=HouseholdGoal.FOOD,
    )
    defaults.update(overrides)
    return FarmerRequest(**defaults)


def good_gaez(crop_id="maize") -> GaezEvidence:
    return GaezEvidence(
        crop_id=crop_id, suitability_index=78.0, suitability_class="S - suitable",
        attainable_yield_kg_ha=4200.0, scenario="historical / rainfed / low-input",
        source="test fixture",
    )


def calm_climate(crop_id="maize") -> ClimateEvidence:
    return ClimateEvidence(
        crop_id=crop_id, window_start=date(2026, 9, 20), window_end=date(2026, 12, 20),
        years_analyzed=[2021, 2022, 2023], mean_total_rainfall_mm=550.0,
        rainfall_by_year_mm={2021: 520.0, 2022: 560.0, 2023: 570.0},
        mean_longest_dry_spell_days=5.0, longest_dry_spell_by_year_days={2021: 5, 2022: 4, 2023: 6},
        mean_tmax_c=26.0, mean_tmin_c=15.0, days_tmax_above_35c_mean=0.0,
    )


def harsh_climate(crop_id="maize") -> ClimateEvidence:
    return ClimateEvidence(
        crop_id=crop_id, window_start=date(2026, 9, 20), window_end=date(2026, 12, 20),
        years_analyzed=[2021, 2022, 2023], mean_total_rainfall_mm=180.0,
        rainfall_by_year_mm={2021: 150.0, 2022: 190.0, 2023: 200.0},
        mean_longest_dry_spell_days=18.0, longest_dry_spell_by_year_days={2021: 20, 2022: 17, 2023: 17},
        mean_tmax_c=31.0, mean_tmin_c=17.0, days_tmax_above_35c_mean=8.0,
    )


def test_feasible_under_known_constraints_with_good_evidence():
    request = base_request(harvest_deadline=date(2027, 2, 28))
    variety = CATALOGUE["maize"]
    result = assess_crop_plan(request, variety, good_gaez(), calm_climate(), CATALOGUE)
    assert result.classification == Feasibility.FEASIBLE_UNDER_KNOWN_CONSTRAINTS


def test_nasa_climate_data_actually_changes_the_classification():
    """Proves NASA climate evidence is consumed by the comparison logic, not
    just displayed: identical farmer input + GAEZ evidence, only the climate
    evidence differs, and the classification must differ as a result.
    """
    request = base_request(harvest_deadline=date(2027, 2, 28))
    variety = CATALOGUE["maize"]

    calm_result = assess_crop_plan(request, variety, good_gaez(), calm_climate(), CATALOGUE)
    harsh_result = assess_crop_plan(request, variety, good_gaez(), harsh_climate(), CATALOGUE)

    assert calm_result.classification == Feasibility.FEASIBLE_UNDER_KNOWN_CONSTRAINTS
    assert harsh_result.classification == Feasibility.FEASIBLE_WITH_CONCERNS
    assert calm_result.classification != harsh_result.classification

    climate_check = next(c for c in harsh_result.checks if c.name == "irrigation_and_climate")
    assert climate_check.concern is True
    assert "dry spell" in climate_check.detail


def test_irrigation_removes_the_dry_spell_concern():
    """Same harsh climate, but the field has irrigation -- the dry-spell
    concern should no longer fire, proving irrigation status is actually
    consumed by the check rather than always flagging on rainfall alone.
    """
    irrigated_field = FieldLocation(latitude=KAYONZA.latitude, longitude=KAYONZA.longitude, has_irrigation=True)
    request = base_request(field=irrigated_field, harvest_deadline=date(2027, 2, 28))
    variety = CATALOGUE["maize"]
    result = assess_crop_plan(request, variety, good_gaez(), harsh_climate(), CATALOGUE)
    climate_check = next(c for c in result.checks if c.name == "irrigation_and_climate")
    assert "dry spell" not in climate_check.detail


def test_growing_period_too_short_is_infeasible():
    request = base_request(planting_window_start=date(2026, 12, 1), harvest_deadline=date(2026, 12, 20))
    variety = CATALOGUE["maize"]
    result = assess_crop_plan(request, variety, good_gaez(), calm_climate(), CATALOGUE)
    assert result.classification == Feasibility.INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS
    assert any(not c.passed for c in result.checks)


def test_not_suitable_gaez_class_is_infeasible():
    request = base_request(harvest_deadline=date(2027, 2, 28))
    variety = CATALOGUE["maize"]
    ns_gaez = GaezEvidence(
        crop_id="maize", suitability_index=5.0, suitability_class="NS - not suitable",
        attainable_yield_kg_ha=0.0, scenario="historical / rainfed / low-input", source="test fixture",
    )
    result = assess_crop_plan(request, variety, ns_gaez, calm_climate(), CATALOGUE)
    assert result.classification == Feasibility.INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS


def test_missing_evidence_is_more_information_required():
    request = base_request(harvest_deadline=date(2027, 2, 28))
    variety = CATALOGUE["maize"]
    result = assess_crop_plan(request, variety, None, None, CATALOGUE)
    assert result.classification == Feasibility.MORE_INFORMATION_REQUIRED


def test_same_family_history_flags_rotation_concern():
    request = base_request(previous_crops=["maize"], harvest_deadline=date(2027, 2, 28))
    variety = CATALOGUE["maize"]
    result = assess_crop_plan(request, variety, good_gaez(), calm_climate(), CATALOGUE)
    history_check = next(c for c in result.checks if c.name == "crop_history")
    assert history_check.concern is True


def test_pick_preferred_crop_requires_material_distinction():
    # previous_crops left empty so neither candidate gets a rotation-history
    # edge over the other -- isolates the "no material distinction" case.
    request = base_request(desired_crops=["maize", "beans"], previous_crops=[],
                            harvest_deadline=date(2027, 2, 28))
    maize = assess_crop_plan(request, CATALOGUE["maize"], good_gaez("maize"), calm_climate("maize"), CATALOGUE)
    beans = assess_crop_plan(request, CATALOGUE["beans"], good_gaez("beans"), calm_climate("beans"), CATALOGUE)
    preferred, shortlist, rationale = pick_preferred_crop([maize, beans])
    assert preferred is None
    assert set(shortlist) == {"maize", "beans"}


def test_pick_preferred_crop_picks_clear_winner():
    request = base_request(desired_crops=["maize", "beans"], harvest_deadline=date(2027, 2, 28))
    maize = assess_crop_plan(request, CATALOGUE["maize"], good_gaez("maize"), calm_climate("maize"), CATALOGUE)
    bad_gaez = GaezEvidence(
        crop_id="beans", suitability_index=3.0, suitability_class="NS - not suitable",
        attainable_yield_kg_ha=0.0, scenario="historical / rainfed / low-input", source="test fixture",
    )
    beans = assess_crop_plan(request, CATALOGUE["beans"], bad_gaez, calm_climate("beans"), CATALOGUE)
    preferred, shortlist, rationale = pick_preferred_crop([maize, beans])
    assert preferred == "maize"
