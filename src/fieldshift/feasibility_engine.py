"""Deterministic, pure-function feasibility engine (Stage E/F).

Every function here takes plain data (FarmerRequest, CropVariety,
GaezEvidence, ClimateEvidence) and returns a structured result. No network
calls, no randomness, no hidden state — the same inputs always produce the
same CropPlanAssessment, and every classification traces back to a named
FeasibilityCheck so the reasoning is auditable.

GAEZ suitability-class thresholds used in `_check_gaez_suitability` reflect
GAEZ's own published class scheme (see docs/gaez_v5_assumptions.md for the
source citation); the suitability INDEX and CLASS are never combined
arithmetically with NASA climate statistics — they are two independent
lines of evidence that are each surfaced to the classification logic.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from .models import (
    ClimateEvidence,
    CropPlanAssessment,
    CropVariety,
    Feasibility,
    FeasibilityCheck,
    FarmerRequest,
    GaezEvidence,
    HouseholdGoal,
)

# GAEZ v5 suitability-class labels are categorical (VS/S/MS/mS/vmS/NS). We match on
# the full descriptive words, never the short codes: "mS" (marginally, 20-40% of max
# attainable yield) and "MS" (moderately, 40-60%) differ only by case, which a
# case-insensitive match on short codes would collide. "Marginally"/"moderately" don't.
# mS and vmS (<40% of max attainable yield) are treated as a concern, NS as a hard
# fail, everything >=40% (MS/S/VS) as a clean pass. We never invent a numeric index
# cutoff that GAEZ itself did not publish for v5 -- see docs/gaez_v5_assumptions.md.
GAEZ_CONCERN_CLASSES = {"marginally suitable", "very marginally suitable"}
GAEZ_HARD_FAIL_CLASSES = {"not suitable"}

DRY_SPELL_CONCERN_DAYS = 10     # a run this long with no meaningful rain during the window is agronomically material
HOT_DAYS_CONCERN = 5.0          # mean days >=35C in the window


def _check_growing_period(request: FarmerRequest, variety: CropVariety) -> FeasibilityCheck:
    available_days = (request.harvest_deadline - request.planting_window_start).days
    if available_days < variety.duration_days_min:
        return FeasibilityCheck(
            name="growing_period_compatibility",
            passed=False,
            concern=False,
            detail=(
                f"{variety.crop_name} needs at least {variety.duration_days_min} days "
                f"({variety.variety_name}); only {available_days} days are available between "
                f"the stated planting start and harvest deadline."
            ),
        )
    if available_days < variety.duration_days_max:
        return FeasibilityCheck(
            name="growing_period_compatibility",
            passed=True,
            concern=True,
            detail=(
                f"{available_days} available days covers the variety's minimum "
                f"({variety.duration_days_min}d) but not its full typical range up to "
                f"{variety.duration_days_max}d -- a late planting or any delay narrows this further."
            ),
        )
    return FeasibilityCheck(
        name="growing_period_compatibility",
        passed=True,
        concern=False,
        detail=f"{available_days} available days comfortably covers {variety.variety_name}'s "
               f"{variety.duration_days_min}-{variety.duration_days_max} day range.",
    )


def _check_gaez_suitability(evidence: Optional[GaezEvidence]) -> FeasibilityCheck:
    if evidence is None or evidence.suitability_class is None:
        return FeasibilityCheck(
            name="gaez_suitability",
            passed=True,
            concern=True,
            detail="No GAEZ v5 suitability evidence could be retrieved for this crop at this "
                   "location -- treat suitability as unknown, not as approved.",
        )
    cls = evidence.suitability_class.lower()
    if any(h in cls for h in GAEZ_HARD_FAIL_CLASSES):
        return FeasibilityCheck(
            name="gaez_suitability",
            passed=False,
            concern=False,
            detail=f"GAEZ v5 classifies this crop as '{evidence.suitability_class}' "
                   f"(suitability index {evidence.suitability_index}) under {evidence.scenario} "
                   f"at this location ({evidence.source}).",
        )
    if any(c in cls for c in GAEZ_CONCERN_CLASSES):
        return FeasibilityCheck(
            name="gaez_suitability",
            passed=True,
            concern=True,
            detail=f"GAEZ v5 classifies this crop as '{evidence.suitability_class}' "
                   f"(suitability index {evidence.suitability_index}) under {evidence.scenario} "
                   f"at this location -- modeled suitability is marginal, not ruled out.",
        )
    return FeasibilityCheck(
        name="gaez_suitability",
        passed=True,
        concern=False,
        detail=f"GAEZ v5 classifies this crop as '{evidence.suitability_class}' "
               f"(suitability index {evidence.suitability_index}) under {evidence.scenario} at this location.",
    )


def _check_crop_history(request: FarmerRequest, variety: CropVariety, catalogue: dict[str, CropVariety]) -> FeasibilityCheck:
    if not request.previous_crops:
        return FeasibilityCheck(
            name="crop_history",
            passed=True,
            concern=True,
            detail="No previous-crop history was supplied -- rotation benefit/risk can't be assessed.",
        )
    last_crop_id = request.previous_crops[0]
    last_variety = catalogue.get(last_crop_id)
    if last_variety is None:
        return FeasibilityCheck(
            name="crop_history",
            passed=True,
            concern=True,
            detail=f"Previous crop '{last_crop_id}' is not in the catalogue -- family/rotation effect unknown.",
        )
    if last_variety.crop_id == variety.crop_id:
        return FeasibilityCheck(
            name="crop_history",
            passed=True,
            concern=True,
            detail=f"Same crop ({variety.crop_name}) was grown last season -- no family rotation break; "
                   f"documented pest/disease and soil-nutrient rationale favors alternating with a different family.",
        )
    if last_variety.family != variety.family:
        return FeasibilityCheck(
            name="crop_history",
            passed=True,
            concern=False,
            detail=f"Previous crop ({last_variety.crop_name}, {last_variety.family}) differs in family from "
                   f"{variety.crop_name} ({variety.family}) -- consistent with documented rotation guidance. "
                   f"{variety.rotation_notes}",
        )
    return FeasibilityCheck(
        name="crop_history",
        passed=True,
        concern=True,
        detail=f"Previous crop ({last_variety.crop_name}) shares family {variety.family} with {variety.crop_name}.",
    )


def _check_irrigation_and_climate(request: FarmerRequest, climate: Optional[ClimateEvidence]) -> FeasibilityCheck:
    if climate is None:
        return FeasibilityCheck(
            name="irrigation_and_climate",
            passed=True,
            concern=True,
            detail="No NASA POWER climate evidence could be computed for this window -- "
                   "dry-spell and heat exposure risk is unknown.",
        )
    concerns = []
    if climate.mean_longest_dry_spell_days >= DRY_SPELL_CONCERN_DAYS and not request.field.has_irrigation:
        concerns.append(
            f"historical windows average a {climate.mean_longest_dry_spell_days:.0f}-day longest dry spell "
            f"with no irrigation available"
        )
    if climate.days_tmax_above_35c_mean >= HOT_DAYS_CONCERN:
        concerns.append(f"an average of {climate.days_tmax_above_35c_mean:.0f} days/season above 35C")
    if concerns:
        return FeasibilityCheck(
            name="irrigation_and_climate",
            passed=True,
            concern=True,
            detail=(
                f"NASA POWER history ({', '.join(str(y) for y in climate.years_analyzed)}) for this window shows "
                + "; ".join(concerns) + f". Mean total rainfall across those years: "
                f"{climate.mean_total_rainfall_mm:.0f} mm."
            ),
        )
    return FeasibilityCheck(
        name="irrigation_and_climate",
        passed=True,
        concern=False,
        detail=(
            f"NASA POWER history ({', '.join(str(y) for y in climate.years_analyzed)}) shows mean rainfall "
            f"{climate.mean_total_rainfall_mm:.0f} mm and longest dry spell averaging "
            f"{climate.mean_longest_dry_spell_days:.0f} days -- no material concern flagged "
            f"against this crop's documented water needs."
        ),
    )


def _check_affordability(request: FarmerRequest, variety: CropVariety) -> FeasibilityCheck:
    if request.budget_rwf is None:
        return FeasibilityCheck(
            name="affordability",
            passed=True,
            concern=False,
            detail="No budget was stated -- affordability not evaluated.",
        )
    # We deliberately do not fabricate input prices. Without a verified price list
    # in the catalogue, affordability against a stated budget cannot be computed,
    # so we flag it as needing more information rather than guessing a cost.
    return FeasibilityCheck(
        name="affordability",
        passed=True,
        concern=True,
        detail=f"Budget of {request.budget_rwf:.0f} RWF was stated, but no verified input-price data for "
               f"{variety.variety_name} is in the catalogue -- affordability could not be checked against it.",
    )


def assess_crop_plan(request: FarmerRequest, variety: CropVariety,
                      gaez_evidence: Optional[GaezEvidence],
                      climate_evidence: Optional[ClimateEvidence],
                      catalogue: dict[str, CropVariety]) -> CropPlanAssessment:
    checks = [
        _check_growing_period(request, variety),
        _check_gaez_suitability(gaez_evidence),
        _check_crop_history(request, variety, catalogue),
        _check_irrigation_and_climate(request, climate_evidence),
        _check_affordability(request, variety),
    ]

    hard_fail = [c for c in checks if not c.passed]
    missing_evidence = gaez_evidence is None or climate_evidence is None
    concerns = [c for c in checks if c.passed and c.concern]

    if hard_fail:
        classification = Feasibility.INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS
    elif missing_evidence:
        classification = Feasibility.MORE_INFORMATION_REQUIRED
    elif concerns:
        classification = Feasibility.FEASIBLE_WITH_CONCERNS
    else:
        classification = Feasibility.FEASIBLE_UNDER_KNOWN_CONSTRAINTS

    proposed_window = None
    if not hard_fail:
        proposed_window = (
            request.planting_window_start,
            min(
                request.planting_window_start + timedelta(days=variety.duration_days_max),
                request.harvest_deadline,
            ),
        )

    explanation_parts = [c.detail for c in checks if not c.passed] or [c.detail for c in checks]
    explanation = " ".join(explanation_parts)

    open_questions = []
    if gaez_evidence is None:
        open_questions.append(f"GAEZ v5 suitability evidence for {variety.crop_name} at this field could not be retrieved.")
    if climate_evidence is None:
        open_questions.append("NASA POWER climate evidence could not be computed for this window.")
    if request.budget_rwf is not None:
        open_questions.append("Verified input prices are needed to check affordability against the stated budget.")

    return CropPlanAssessment(
        crop_id=variety.crop_id,
        classification=classification,
        checks=checks,
        gaez_evidence=gaez_evidence,
        climate_evidence=climate_evidence,
        proposed_planting_window=proposed_window,
        explanation=explanation,
        open_questions=open_questions,
    )


_CLASSIFICATION_RANK = {
    Feasibility.FEASIBLE_UNDER_KNOWN_CONSTRAINTS: 0,
    Feasibility.FEASIBLE_WITH_CONCERNS: 1,
    Feasibility.MORE_INFORMATION_REQUIRED: 2,
    Feasibility.INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS: 3,
}


def pick_preferred_crop(assessments: list[CropPlanAssessment]) -> tuple[Optional[str], list[str], str]:
    """Stage F preference policy: only name a leading crop when there's a
    justified, material distinction. Otherwise return a shortlist + a
    targeted question instead of forcing a ranking.
    """
    if not assessments:
        return None, [], "No crop plans were assessed."

    ranked = sorted(assessments, key=lambda a: _CLASSIFICATION_RANK[a.classification])
    best_rank = _CLASSIFICATION_RANK[ranked[0].classification]
    tied = [a for a in assessments if _CLASSIFICATION_RANK[a.classification] == best_rank]

    feasible_tiers = {Feasibility.FEASIBLE_UNDER_KNOWN_CONSTRAINTS, Feasibility.FEASIBLE_WITH_CONCERNS}
    if best_rank == _CLASSIFICATION_RANK[Feasibility.INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS]:
        return None, [], ("All assessed crops are INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS given the stated "
                           "planting window, harvest deadline and field constraints.")

    if len(tied) == 1 and ranked[0].classification in feasible_tiers:
        other = ranked[1] if len(ranked) > 1 else None
        if other is None or _CLASSIFICATION_RANK[other.classification] > best_rank:
            return tied[0].crop_id, [a.crop_id for a in assessments], (
                f"{tied[0].crop_id} is classified {tied[0].classification.value}, a materially better "
                f"outcome than the other candidate(s)."
            )

    shortlist = [a.crop_id for a in tied]
    return None, shortlist, (
        f"{len(tied)} crop(s) tie at {ranked[0].classification.value} with no material distinction between "
        f"them under current evidence -- more targeted information (e.g. stated priority between the tied "
        f"crops, or resolving an open question above) would be needed to prefer one."
    )
