"""Minimal FastAPI backend wiring the farmer questionnaire UI to the real
FieldShift engine: NASA POWER (live, cached) + GAEZ v5 pilot evidence +
Rwanda crop catalogue + the deterministic feasibility/rotation engine.

Run with: .venv/Scripts/python.exe -m uvicorn web.app:app --reload --port 8000
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from fieldshift.crop_catalogue import load_catalogue
from fieldshift.gaez_adapter import make_gaez_lookup
from fieldshift.models import CropVariety, FarmerRequest, FieldLocation, HouseholdGoal
from fieldshift.nasa_power import compute_climate_evidence
from fieldshift.rotation_engine import build_recommendation

app = FastAPI(title="FieldShift")
CATALOGUE = load_catalogue()
GAEZ_LOOKUP = make_gaez_lookup()


class RecommendRequest(BaseModel):
    latitude: float
    longitude: float
    has_irrigation: bool = False
    desired_crops: list[str]
    allow_outside_suggestions: bool = False
    previous_crops: list[str] = []
    planting_window_start: str   # ISO date
    harvest_deadline: str        # ISO date
    household_goal: str          # "food" | "income" | "both"
    budget_rwf: Optional[float] = None


@app.get("/api/catalogue")
def get_catalogue():
    return jsonable_encoder(CATALOGUE)


@app.post("/api/recommend")
def recommend(req: RecommendRequest):
    field = FieldLocation(latitude=req.latitude, longitude=req.longitude, has_irrigation=req.has_irrigation)
    planting_start = datetime.strptime(req.planting_window_start, "%Y-%m-%d").date()
    harvest_deadline = datetime.strptime(req.harvest_deadline, "%Y-%m-%d").date()

    request = FarmerRequest(
        field=field,
        desired_crops=req.desired_crops,
        allow_outside_suggestions=req.allow_outside_suggestions,
        previous_crops=req.previous_crops,
        planting_window_start=planting_start,
        harvest_deadline=harvest_deadline,
        household_goal=HouseholdGoal(req.household_goal),
        budget_rwf=req.budget_rwf,
    )

    def climate_lookup(crop_id: str, variety: CropVariety):
        try:
            return compute_climate_evidence(
                crop_id, field.latitude, field.longitude,
                planting_start, harvest_deadline, years_back=8,
            )
        except RuntimeError:
            return None

    recommendation = build_recommendation(request, CATALOGUE, GAEZ_LOOKUP, climate_lookup)
    return jsonable_encoder(recommendation)


app.mount("/", StaticFiles(directory=str(Path(__file__).parent / "static"), html=True), name="static")
