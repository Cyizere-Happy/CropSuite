"""GAEZ v5 evidence adapter (Stage B).

Reads the Kayonza pilot's PRE-EXTRACTED GAEZ v5 values from
data/gaez/kayonza_pilot.json. That file is produced once, offline, by
scripts/fetch_gaez_pilot.py (real GeoTIFF download + pixel sampling at the
pilot coordinates) — raster processing is deliberately kept out of the
per-request path.

If the pilot file is missing or doesn't have an entry for a crop, this
returns None rather than fabricating a suitability value; the feasibility
engine already treats missing GAEZ evidence as MORE_INFORMATION_REQUIRED,
not as a silent pass.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .models import GaezEvidence

PILOT_DATA_PATH = Path(__file__).resolve().parents[2] / "data" / "gaez" / "kayonza_pilot.json"


def load_pilot_evidence(path: Path = PILOT_DATA_PATH) -> dict[str, GaezEvidence]:
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    out: dict[str, GaezEvidence] = {}
    for crop_id, entry in raw.get("crops", {}).items():
        out[crop_id] = GaezEvidence(
            crop_id=crop_id,
            suitability_index=entry.get("suitability_index"),
            suitability_class=entry.get("suitability_class"),
            attainable_yield_kg_ha=entry.get("attainable_yield_kg_ha"),
            scenario=entry.get("scenario", "unknown scenario"),
            source=entry.get("source", "unknown source"),
            retrieval_note=entry.get("retrieval_note", ""),
        )
    return out


def make_gaez_lookup(path: Path = PILOT_DATA_PATH):
    """Returns a `crop_id -> Optional[GaezEvidence]` callable for rotation_engine."""
    cache = load_pilot_evidence(path)

    def lookup(crop_id: str) -> Optional[GaezEvidence]:
        return cache.get(crop_id)

    return lookup
