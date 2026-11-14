# FieldShift (Kayonza pilot)

A farmer-specific crop-and-rotation feasibility engine for Rwanda, built on
real FAO GAEZ v5 suitability/yield evidence, real NASA POWER historical
climate data, and a source-backed Rwanda crop catalogue (maize + beans).
Deterministic, pure-function recommendation logic -- no AI model, no
fabricated scores.

## Setup

```
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

## Run

```
# One-off: download real GAEZ v5 rasters and extract the Kayonza pilot pixel
.venv/Scripts/python.exe scripts/fetch_gaez_pilot.py

# Run the full test suite (13 tests: engine logic, live NASA POWER integration,
# and real-GAEZ-data-flows-into-the-engine integration)
.venv/Scripts/python.exe -m pytest tests/ -q

# Stage G demonstration trace (base case + 5 sensitivity reruns + 2 more
# reproducible cases), printed to stdout
.venv/Scripts/python.exe demo/run_demo.py

# Web app (farmer questionnaire -> real engine)
.venv/Scripts/python.exe -m uvicorn web.app:app --port 8000
# then open http://127.0.0.1:8000/
```

## Architecture

```
src/fieldshift/
  models.py            plain dataclasses shared by every module
  nasa_power.py         real NASA POWER Daily Point API client + historical
                        rainfall/dry-spell/temperature statistics
  gaez_adapter.py        loads pre-extracted real GAEZ v5 pilot evidence
  crop_catalogue.py      loads the source-backed Rwanda crop catalogue
  feasibility_engine.py  pure-function per-crop checks -> classification
  rotation_engine.py     orchestrates the above into a RotationRecommendation
scripts/fetch_gaez_pilot.py   one-off: download real GAEZ GeoTIFFs, sample
                               the Kayonza pixel, write data/gaez/kayonza_pilot.json
demo/run_demo.py        Stage G real end-to-end trace + sensitivity reruns
web/app.py + web/static/index.html   FastAPI backend + farmer questionnaire UI
data/gaez/kayonza_pilot.json          real extracted GAEZ v5 values + provenance
data/rwanda_crops/catalogue.json      real, source-cited Rwanda crop data
data/nasa_power_cache/                 cached NASA POWER responses (offline reruns)
docs/gaez_v5_assumptions.md           full GAEZ v5 methodology notes + limitations
```

## What's real vs. derived

- **NASA POWER**: every climate number is a live API call (cached to disk
  for repeat runs), never fabricated. `tests/test_nasa_power_integration.py`
  hits the real API.
- **GAEZ v5**: `data/gaez/kayonza_pilot.json` was produced by actually
  downloading FAO's public GeoTIFFs (`https://storage.googleapis.com/fao-gismgr-gaez-v5-data/...`)
  and sampling the Kayonza pixel with `rasterio` -- see
  `docs/gaez_v5_assumptions.md` for the full scenario definition, unit
  conversions, and the one genuine unresolved ambiguity (the `RES05-SIX`
  raw class-code legend isn't published by FAO, so suitability class is
  derived from the published index thresholds instead; full reasoning in
  that doc).
- **Rwanda crop catalogue**: durations/varieties/planting windows/rotation
  notes are cited to RAB, FAO, NISR, Meteo Rwanda, CGIAR/PABRA and academic
  sources in `data/rwanda_crops/catalogue.json`'s `provenance` fields; every
  figure that could not be independently verified is flagged as such inline
  rather than presented as fact.
- **Feasibility engine**: deterministic, pure functions
  (`feasibility_engine.py`) -- same inputs always produce the same
  classification and the same auditable list of named checks. No GAEZ/NASA
  values are ever summed or blended into one score.

## Proven before/after behavior (Stage G)

`demo/run_demo.py`'s output shows, with real data, that changing a single
farmer input materially changes the recommendation -- not cosmetic text:
- Pulling the harvest deadline in from 2027-01-20 to 2026-12-15 flips beans
  from `FEASIBLE_WITH_CONCERNS` to `INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS`
  (115-120 day variety, only 86 days available), which turns a tied
  "no clear winner" base case into a single preferred crop (maize).
- A tight 70-day window (Case 2) drives both crops to
  `INFEASIBLE_UNDER_VERIFIED_CONSTRAINTS` and the engine correctly reports
  no preferred crop rather than forcing a choice.
- Repeating the same crop as the prior season (Case 3, beans-after-beans)
  surfaces a `crop_history` concern that a different-family rotation
  (maize-after-beans) does not.
- `tests/test_feasibility_engine.py::test_nasa_climate_data_actually_changes_the_classification`
  and `test_irrigation_removes_the_dry_spell_concern` prove NASA climate
  evidence and irrigation status are actually consumed by the comparison
  logic, not merely displayed.

## Known limitations (see docs/gaez_v5_assumptions.md for full detail)

- Pilot evidence covers exactly one point (Kayonza, -1.883, 30.644) and two
  crops (maize, beans); the catalogue and GAEZ adapter are built to extend,
  not to claim national coverage.
- GAEZ's suitability/yield evidence is species-level, not specific to the
  named Rwandan RAB varieties in the catalogue.
- No verified input-price data exists yet, so affordability checks against
  a stated budget are flagged as `MORE_INFORMATION_REQUIRED` rather than
  computed.
- The `RES05-SIX` raw class-code legend is not published by FAO; suitability
  class is derived from the published index-percentage thresholds instead
  (see docs/gaez_v5_assumptions.md for why, including the raw-value
  cross-check that ruled out guessing the legend).
