"""One-off Stage B extraction: download real GAEZ v5 GeoTIFFs for maize (MZE)
and common bean (PHB), rainfed/low-input/historical scenario, and sample the
Kayonza pilot pixel. Writes data/gaez/kayonza_pilot.json with full provenance.

This is NOT run in the per-request path -- run it once, offline:
    .venv/Scripts/python.exe scripts/fetch_gaez_pilot.py

Scenario (verified live against FAO's own RES05 README catalog, see
docs/gaez_v5_assumptions.md): SSP=HIST, INPUT=LRLM (rainfed, low-input),
CLIMATE_DATA_SOURCE=AGERA5, PERIOD=HP0120 (2001-2020, most recent 20yr
historical window).

Suitability-class label is derived from the suitability INDEX (RES05-SXX)
using GAEZ's own published class-boundary percentages (Module V wiki:
VS=80-100% of max attainable yield, S=60-80%, MS=40-60%, mS=20-40%,
vmS=<20%, NS=not suitable) rather than by decoding the RES05-SIX raster's
raw integer legend, which FAO's docs do not publish and which this
pipeline could not independently verify (see docs/gaez_v5_assumptions.md
"Unresolved blockers"). The RES05-SIX pixel is still downloaded and its
raw value recorded for transparency/cross-check.
"""
from __future__ import annotations

import json
from pathlib import Path

import requests

BASE_URL = "https://storage.googleapis.com/fao-gismgr-gaez-v5-data/DATA/GAEZ-V5/MAPSET"
PERIOD = "HP0120"
CLIMATE_SOURCE = "AGERA5"
SSP = "HIST"
INPUT_LEVEL = "LRLM"

CROPS = {
    "maize": "MZE",
    "beans": "PHB",
}
LAYERS = ["SXX", "SIX", "YXX"]  # suitability index, suitability class, attainable yield

KAYONZA_LAT, KAYONZA_LON = -1.883, 30.644

RAW_DIR = Path(__file__).resolve().parents[1] / "data" / "gaez" / "raw"
OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "gaez" / "kayonza_pilot.json"


def tif_url(mapset_code: str, crop_code: str) -> str:
    filename = f"GAEZ-V5.RES05-{mapset_code}.{PERIOD}.{CLIMATE_SOURCE}.{SSP}.{crop_code}.{INPUT_LEVEL}.tif"
    return f"{BASE_URL}/RES05-{mapset_code}/{filename}"


def download(url: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        return dest
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    dest.write_bytes(resp.content)
    return dest


def suitability_class_from_index(index_0_100: float) -> str:
    """GAEZ v5 Module V published class boundaries, expressed as % of max
    attainable yield (wiki page 07): VS 80-100, S 60-80, MS 40-60, mS 20-40,
    vmS <20 (and NS for non-suitable land, index ~0)."""
    if index_0_100 >= 80:
        return "VS - very suitable"
    if index_0_100 >= 60:
        return "S - suitable"
    if index_0_100 >= 40:
        return "MS - moderately suitable"
    if index_0_100 >= 20:
        return "mS - marginally suitable"
    if index_0_100 > 0:
        return "vmS - very marginally suitable"
    return "NS - not suitable"


def sample_pixel(tif_path: Path, lon: float, lat: float):
    import rasterio

    with rasterio.open(tif_path) as src:
        nodata = src.nodata
        band1 = src.read(1)
        row, col = src.index(lon, lat)
        value = band1[row, col]
        is_nodata = (nodata is not None and value == nodata)
        return {
            "raw_value": float(value),
            "nodata_value": nodata,
            "is_nodata": bool(is_nodata),
            "crs": str(src.crs),
            "resolution_deg": src.res,
            "band_count": src.count,
            "dtype": str(src.dtypes[0]),
        }


def main():
    result = {"pilot_point": {"lat": KAYONZA_LAT, "lon": KAYONZA_LON, "name": "Kayonza, Eastern Province, Rwanda"},
               "scenario": f"SSP={SSP}, INPUT={INPUT_LEVEL} (rainfed, low-input), "
                           f"CLIMATE_DATA_SOURCE={CLIMATE_SOURCE}, PERIOD={PERIOD} (2001-2020)",
               "crops": {}}

    for crop_id, crop_code in CROPS.items():
        layer_samples = {}
        for layer in LAYERS:
            url = tif_url(layer, crop_code)
            dest = RAW_DIR / f"RES05-{layer}" / f"{crop_code}.tif"
            print(f"[{crop_id}/{layer}] downloading {url}")
            download(url, dest)
            sample = sample_pixel(dest, KAYONZA_LON, KAYONZA_LAT)
            sample["source_url"] = url
            layer_samples[layer] = sample
            print(f"[{crop_id}/{layer}] raw pixel value = {sample['raw_value']} (nodata={sample['is_nodata']})")

        sxx = layer_samples["SXX"]
        six = layer_samples["SIX"]
        yxx = layer_samples["YXX"]

        suitability_index = None if sxx["is_nodata"] else round(sxx["raw_value"] / 100.0, 1)
        suitability_class = None if suitability_index is None else suitability_class_from_index(suitability_index)
        attainable_yield = None if yxx["is_nodata"] else round(yxx["raw_value"], 1)

        result["crops"][crop_id] = {
            "crop_code": crop_code,
            "suitability_index": suitability_index,
            "suitability_class": suitability_class,
            "attainable_yield_kg_ha": attainable_yield,
            "scenario": result["scenario"],
            "source": (
                f"FAO GAEZ v5, RES05-SXX/SIX/YXX mapsets, crop code {crop_code}, "
                f"scenario HIST/AGERA5/LRLM/{PERIOD}. Files: "
                f"{sxx['source_url']} | {six['source_url']} | {yxx['source_url']}"
            ),
            "retrieval_note": (
                f"suitability_class derived from suitability_index using GAEZ v5 Module V's published "
                f"class-boundary percentages (VS>=80, S>=60, MS>=40, mS>=20, vmS>0, NS=0), NOT by decoding "
                f"the RES05-SIX raster's raw integer legend (FAO does not publish that legend; raw RES05-SIX "
                f"pixel value recorded here for cross-check only: {six['raw_value']}). "
                f"SXX raster units are suitability index x100 (0-10000 scale); divided by 100 here. "
                f"YXX units are kg/ha dry matter, rainfed low-input historical (2001-2020) scenario -- "
                f"this is GAEZ's modeled attainable-yield CEILING, not an observed or variety-specific yield."
            ),
            "raw_samples": layer_samples,
        }

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(result, indent=2))
    print(f"\nWrote {OUT_PATH}")


if __name__ == "__main__":
    main()
