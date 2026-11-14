# GAEZ v5 data assumptions, scenario choice, and known limitations

This records exactly what FieldShift pulls from FAO GAEZ v5, how, and what is
and isn't verified -- so nothing here is taken as more certain than it is.

## What was retrieved

Real GeoTIFF rasters, downloaded directly (no auth) from FAO's public Google
Cloud Storage bucket, confirmed live and correct via GDAL/rasterio reads in
this session (see `scripts/fetch_gaez_pilot.py`, output in
`data/gaez/kayonza_pilot.json`):

| Crop | Code | SXX (suitability index) | SIX (suitability class, raw) | YXX (attainable yield) |
|---|---|---|---|---|
| Maize | `MZE` | 2389 / 100 = **23.9** | 6 (legend not decoded, not used -- see below) | **3170 kg/ha** |
| Common bean | `PHB` | 2093 / 100 = **20.9** | 6 (legend not decoded, not used -- see below) | **925 kg/ha** |

Pilot point: Kayonza, Eastern Province, Rwanda (-1.883, 30.644). Both crops
land in the same GAEZ-published suitability class at this point:
**"mS -- marginally suitable"** (20-40% of max attainable yield), not
"suitable" and not "not suitable" -- consistent with Eastern Province's
documented drier, more erratic savanna rainfall relative to the rest of
Rwanda (see `data/rwanda_crops/catalogue.json` provenance).

## Scenario definition (verified against FAO's own RES05 README catalog)

- `SSP=HIST` -- historical climate (as opposed to a future SSP126/370/585
  projection raster). **This matters**: GAEZ v5 also publishes future-climate
  rasters under the same mapset family, and it is easy to accidentally fetch
  one if the SSP code is wrong -- FieldShift's downloader hardcodes `HIST`
  and never accepts a caller-supplied SSP code.
- `INPUT=LRLM` -- rainfed, low-input level of management (matches the
  farmer's no-irrigation, smallholder-input Kayonza pilot profile).
- `CLIMATE_DATA_SOURCE=AGERA5` -- AgERA5 climate reanalysis (GAEZ's
  historical climate driver).
- `PERIOD=HP0120` -- 2001-2020, the most recent published 20-year historical
  window (an older `HP8100` 1981-2000 window also exists but was not used).

## What each layer means (source: GAEZ v5 wiki, Module V page)

- **RES05-SXX (suitability index)**: 0-10000 raw scale (divide by 100 for
  the conceptual 0-100 index). A continuous measure, not a yield number.
- **RES05-SIX (suitability class)**: categorical. FAO's published class
  definitions are stated as *percent of maximum attainable yield*: VS
  80-100%, S 60-80%, MS 40-60%, mS 20-40%, vmS <20%, NS not suitable.
- **RES05-YXX (attainable yield)**: kg/ha, dry matter, under the scenario
  above. This is GAEZ's modeled **ceiling** -- "the attainable average
  annual production achievable on a sustainable basis" assuming farmers use
  the better part of the suitability distribution in the grid cell -- **not**
  an observed farm yield, and not specific to any one seed variety (GAEZ
  models the species `MZE`/`PHB`, not a named Rwandan RAB variety).

## Why suitability *class* is derived from the index, not from the SIX raster

FAO's wiki publishes the VS/S/MS/mS/vmS/NS percentage thresholds, but does
**not** publish which raw integer in the `RES05-SIX` GeoTIFF corresponds to
which class. At the Kayonza pixel both maize and beans read `SIX=6`, which
cannot consistently mean "not suitable" under any ordinal 1-6 or 6-1 legend,
because both crops' own `SXX` index and `YXX` yield at the same pixel are
clearly nonzero and mid-range -- self-contradictory with an NS reading.
Rather than guess the legend, `scripts/fetch_gaez_pilot.py` derives the
suitability class **from the index**, using FAO's own published percentage
boundaries directly. The raw `SIX` pixel value is still recorded in
`kayonza_pilot.json` for transparency, but is explicitly flagged as unused
in `retrieval_note` and never fed into the feasibility engine.

## Theme 3 (crop calendar) vs local planting advice

GAEZ Theme 3 (`RES02-CBD`, "beginning of crop growth cycle") is a
**model-optimized** construct: GAEZ's agro-climatic model tests several
possible start dates per grid cell and records whichever one its own yield
simulation preferred (`RES02-IDX` records which tested Land Utilization Type
"won"). This is not farmer-facing planting advice, and FAO's own wiki does
not claim it is -- FieldShift does not use `RES02-CBD` as a planting-date
recommendation. Rwanda-specific planting windows instead come from
`data/rwanda_crops/catalogue.json`'s NISR Season A/B sources and Meteo
Rwanda Kayonza-specific bulletins.

## Explicit unresolved limitations

1. `RES05-SIX`'s raw integer-to-class legend is not published by FAO and was
   not decoded here (see above) -- class is derived from `SXX` instead.
2. The asterisk footnote on `kg/ha*` yield units in FAO's own Module V output
   table was never resolved (possibly a dry-matter-vs-fresh-weight or
   crop-product-basis caveat); Module II's general "kilograms of dry matter
   per hectare" statement is used as the best available corroboration.
3. Native non-"30AS" grid resolution is inferred as ~5 arc-minutes from the
   actual GeoTIFF header (`0.0833 deg ~= 5 arc-min`, confirmed directly by
   `rasterio` in this session), not from an explicit FAO statement of
   arc-minutes.
4. GAEZ's suitability/yield evidence is **species-level** (`MZE`, `PHB`),
   independent of which Rwandan RAB variety a farmer actually plants. It is
   never presented as a prediction for the specific variety in
   `data/rwanda_crops/catalogue.json`.
5. GAEZ's suitability index and NASA POWER's historical rainfall/dry-spell
   statistics are two independent lines of evidence (`fieldshift.models`).
   They are never summed, multiplied, or blended into one score anywhere in
   this codebase -- see `feasibility_engine.py`'s per-check structure.
