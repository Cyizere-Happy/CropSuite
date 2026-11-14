"""Core data structures shared across the FieldShift engine.

These are plain dataclasses with no business logic: the feasibility and
rotation engines consume and produce these types. Keeping them separate
from the engines makes every engine function a pure function of its inputs.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class HouseholdGoal(str, Enum):
    FOOD = "food"
    INCOME = "income"
    BOTH = "both"


class Feasibility(str, Enum):
    FEASIBLE_UNDER_KNOWN_CONSTRAINTS = "FEASIBLE_UNDER_KNOWN_CONSTRAINTS"
    FEASIBLE_WITH_CONCERNS = "FEASIBLE_WITH_CONCERNS"
    MORE_INFORMATION_REQUIRED = "MORE_INFORMATION_REQUIRED"
    INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS = "INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS"


@dataclass(frozen=True)
class FieldLocation:
    """A farmer's field, identified by a point for NASA/GAEZ lookups."""
    latitude: float
    longitude: float
    name: str = ""
    has_irrigation: bool = False


@dataclass(frozen=True)
class FarmerRequest:
    """Everything the farmer told FieldShift about this planning decision."""
    field: FieldLocation
    desired_crops: list[str]                 # crop_id values the farmer asked about
    allow_outside_suggestions: bool
    previous_crops: list[str]                 # most recent first; crop_id values
    planting_window_start: date
    harvest_deadline: date
    household_goal: HouseholdGoal
    budget_rwf: Optional[float] = None
    available_inputs: list[str] = field(default_factory=list)  # e.g. ["certified_seed", "basal_fertilizer"]
    notes: str = ""


@dataclass(frozen=True)
class GaezEvidence:
    """One crop's GAEZ v5 evidence at a pilot point, with full provenance.

    Values must come from `scripts/fetch_gaez_pilot.py` extraction of real
    GAEZ v5 GeoTIFFs — never hand-typed guesses. `source` must identify the
    exact dataset/file/band this came from.
    """
    crop_id: str
    suitability_index: Optional[float]        # 0-100 scale, GAEZ Module V output
    suitability_class: Optional[str]          # GAEZ categorical class label (e.g. "S3 - moderately suitable")
    attainable_yield_kg_ha: Optional[float]    # rainfed, low-input, historical climate
    scenario: str                              # e.g. "historical / rainfed / low-input"
    source: str                                # dataset id, file name, citation
    retrieval_note: str = ""                   # blockers / substitutions, if any


@dataclass(frozen=True)
class ClimateEvidence:
    """NASA POWER-derived statistics for one candidate planting->harvest window.

    This is historical distributional evidence, not a yield prediction, and
    it must never be summed with GAEZ's suitability index.
    """
    crop_id: str
    window_start: date
    window_end: date
    years_analyzed: list[int]
    mean_total_rainfall_mm: float
    rainfall_by_year_mm: dict[int, float]
    mean_longest_dry_spell_days: float
    longest_dry_spell_by_year_days: dict[int, int]
    mean_tmax_c: float
    mean_tmin_c: float
    days_tmax_above_35c_mean: float
    source: str = "NASA POWER Daily Point API (power.larc.nasa.gov), parameters PRECTOTCORR, T2M_MAX, T2M_MIN"


@dataclass(frozen=True)
class CropVariety:
    crop_id: str
    crop_name: str
    variety_name: str
    family: str
    duration_days_min: int
    duration_days_max: int
    planting_windows: list[str]                # human-readable season windows, e.g. "Season A: mid-Sept to mid-Oct"
    field_constraints: list[str]
    rotation_notes: str
    provenance: str                            # source organization + document


@dataclass(frozen=True)
class FeasibilityCheck:
    """One named check and its outcome, kept so the engine's reasoning is auditable."""
    name: str
    passed: bool
    concern: bool                              # True = passed but with a caveat worth surfacing
    detail: str


@dataclass(frozen=True)
class CropPlanAssessment:
    crop_id: str
    classification: Feasibility
    checks: list[FeasibilityCheck]
    gaez_evidence: Optional[GaezEvidence]
    climate_evidence: Optional[ClimateEvidence]
    proposed_planting_window: Optional[tuple[date, date]]
    explanation: str
    open_questions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RotationRecommendation:
    request: FarmerRequest
    assessments: list[CropPlanAssessment]       # one per crop considered
    preferred_crop_id: Optional[str]            # None if no material distinction
    shortlist: list[str]
    following_crop_suggestions: dict[str, list[str]]  # crop_id -> candidate next crop_ids
    decision_rationale: str
