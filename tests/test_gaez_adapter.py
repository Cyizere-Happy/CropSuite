"""Proves the real, retrieved GAEZ v5 pilot evidence (not a fixture) is what
the feasibility engine actually consumes, and that GAEZ evidence changes the
classification independently of climate evidence.
"""
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fieldshift.crop_catalogue import load_catalogue
from fieldshift.feasibility_engine import assess_crop_plan
from fieldshift.gaez_adapter import load_pilot_evidence, make_gaez_lookup
from fieldshift.models import Feasibility, FarmerRequest, FieldLocation, HouseholdGoal
from tests.test_feasibility_engine import calm_climate

CATALOGUE = load_catalogue()
KAYONZA = FieldLocation(latitude=-1.883, longitude=30.644, has_irrigation=False)


def test_real_pilot_file_has_both_crops_with_provenance():
    evidence = load_pilot_evidence()
    assert "maize" in evidence and "beans" in evidence
    for crop_id, gaez in evidence.items():
        assert gaez.suitability_index is not None
        assert gaez.suitability_class is not None
        assert "storage.googleapis.com" in gaez.source  # real GAEZ GCS source, not a fixture
        assert gaez.scenario.startswith("SSP=HIST")


def test_real_gaez_evidence_flows_into_engine_classification():
    lookup = make_gaez_lookup()
    request = FarmerRequest(
        field=KAYONZA, desired_crops=["maize"], allow_outside_suggestions=False,
        previous_crops=["beans"], planting_window_start=date(2026, 9, 20),
        harvest_deadline=date(2027, 1, 20), household_goal=HouseholdGoal.FOOD,
    )
    real_gaez = lookup("maize")
    assert real_gaez is not None
    result = assess_crop_plan(request, CATALOGUE["maize"], real_gaez, calm_climate("maize"), CATALOGUE)
    gaez_check = next(c for c in result.checks if c.name == "gaez_suitability")
    # Both crops landed in GAEZ's "mS - marginally suitable" class at the Kayonza pixel
    # (see data/gaez/kayonza_pilot.json) -- the engine must surface that as a concern,
    # not silently pass it as fully suitable.
    assert "marginally suitable" in gaez_check.detail
    assert gaez_check.concern is True
    assert result.classification == Feasibility.FEASIBLE_WITH_CONCERNS
