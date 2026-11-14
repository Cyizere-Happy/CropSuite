"""Loads the source-backed Rwanda crop catalogue (Stage C).

The catalogue itself lives in data/rwanda_crops/catalogue.json and is
hand-curated from real sources (RAB, FAO, CGIAR/PABRA, etc.) — this module
only loads and validates it. See that file's "provenance" fields for
citations. Nothing here invents variety names, durations or windows.
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import CropVariety

CATALOGUE_PATH = Path(__file__).resolve().parents[2] / "data" / "rwanda_crops" / "catalogue.json"


def load_catalogue(path: Path = CATALOGUE_PATH) -> dict[str, CropVariety]:
    raw = json.loads(path.read_text())
    catalogue: dict[str, CropVariety] = {}
    for entry in raw["crops"]:
        variety = CropVariety(
            crop_id=entry["crop_id"],
            crop_name=entry["crop_name"],
            variety_name=entry["variety_name"],
            family=entry["family"],
            duration_days_min=entry["duration_days_min"],
            duration_days_max=entry["duration_days_max"],
            planting_windows=entry["planting_windows"],
            field_constraints=entry["field_constraints"],
            rotation_notes=entry["rotation_notes"],
            provenance=entry["provenance"],
        )
        catalogue[variety.crop_id] = variety
    return catalogue
