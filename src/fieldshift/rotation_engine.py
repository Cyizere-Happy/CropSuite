"""Top-level orchestration (Stage E/F/G): wires farmer request + catalogue +
GAEZ evidence + NASA climate evidence into a RotationRecommendation.

This module decides *which* crops to assess (respecting
`allow_outside_suggestions`), calls the feasibility engine per crop, picks a
preferred crop only when justified, and proposes a following crop using the
catalogue's documented rotation relationships (never an invented one).
"""
from __future__ import annotations

from typing import Callable, Optional

from .feasibility_engine import assess_crop_plan, pick_preferred_crop
from .models import (
    ClimateEvidence,
    CropPlanAssessment,
    CropVariety,
    Feasibility,
    FarmerRequest,
    GaezEvidence,
    HouseholdGoal,
    RotationRecommendation,
)

GaezLookup = Callable[[str], Optional[GaezEvidence]]
ClimateLookup = Callable[[str, CropVariety], Optional[ClimateEvidence]]


def _candidate_crop_ids(request: FarmerRequest, catalogue: dict[str, CropVariety]) -> list[str]:
    candidates = [c for c in request.desired_crops if c in catalogue]
    if request.allow_outside_suggestions:
        for crop_id in catalogue:
            if crop_id not in candidates:
                candidates.append(crop_id)
    return candidates


def _suggest_following_crops(crop_id: str, catalogue: dict[str, CropVariety],
                              request: FarmerRequest) -> list[str]:
    """Suggest a following crop by documented family-rotation relationship only.
    Restricted to crops the farmer permitted unless outside suggestions are allowed.
    """
    variety = catalogue.get(crop_id)
    if variety is None:
        return []
    allowed_pool = catalogue.keys() if request.allow_outside_suggestions else set(request.desired_crops) | {crop_id}
    return [
        other_id for other_id, other in catalogue.items()
        if other_id != crop_id and other.family != variety.family and other_id in allowed_pool
    ]


def _household_goal_note(request: FarmerRequest, assessments: list[CropPlanAssessment]) -> str:
    if request.household_goal == HouseholdGoal.FOOD:
        return ("Household goal is stated as food: timing against the harvest deadline and dry-spell "
                "risk weigh at least as heavily as yield potential in the checks above.")
    if request.household_goal == HouseholdGoal.INCOME:
        return ("Household goal is stated as income: a GAEZ attainable-yield figure is modeled production "
                "potential under rainfed low-input assumptions, not a market price or profit estimate -- no "
                "profit claim is made without verified prices and cost data, which were not supplied.")
    return ("Household goal is stated as both food and income: neither timing nor yield potential is treated "
            "as the sole deciding factor.")


def build_recommendation(request: FarmerRequest,
                          catalogue: dict[str, CropVariety],
                          gaez_lookup: GaezLookup,
                          climate_lookup: ClimateLookup) -> RotationRecommendation:
    candidate_ids = _candidate_crop_ids(request, catalogue)
    assessments: list[CropPlanAssessment] = []
    for crop_id in candidate_ids:
        variety = catalogue[crop_id]
        gaez_evidence = gaez_lookup(crop_id)
        climate_evidence = climate_lookup(crop_id, variety)
        assessments.append(assess_crop_plan(request, variety, gaez_evidence, climate_evidence, catalogue))

    preferred, shortlist, rationale = pick_preferred_crop(assessments)
    following = {
        a.crop_id: _suggest_following_crops(a.crop_id, catalogue, request)
        for a in assessments
        if a.classification != Feasibility.INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS
    }

    full_rationale = rationale + " " + _household_goal_note(request, assessments)
    if not request.allow_outside_suggestions and len(candidate_ids) < len(catalogue):
        full_rationale += (" Outside-crop suggestions were not permitted by the farmer, so only "
                            "farmer-selected crops were assessed.")

    return RotationRecommendation(
        request=request,
        assessments=assessments,
        preferred_crop_id=preferred,
        shortlist=shortlist,
        following_crop_suggestions=following,
        decision_rationale=full_rationale,
    )
