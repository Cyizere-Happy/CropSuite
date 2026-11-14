"""NASA POWER climate evidence pipeline.

Pulls real daily point data from the NASA POWER Daily Point API
(https://power.larc.nasa.gov/docs/services/api/temporal/daily/) for a
candidate planting->harvest window, repeated across several past years
using the same month/day window, and reduces it to distributional
statistics (total rainfall, longest dry spell, temperature exposure).

This module produces historical evidence only. It never computes a yield
number and must not be combined arithmetically with GAEZ suitability.
"""
from __future__ import annotations

import json
import ssl
import time
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

try:
    # Use the OS-native certificate trust store instead of certifi's bundled
    # Mozilla list. On this machine curl trusts power.larc.nasa.gov via the
    # Windows cert store but plain `requests`+certifi does not; truststore
    # closes that gap without disabling verification.
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests

from .models import ClimateEvidence

POWER_API_URL = "https://power.larc.nasa.gov/api/temporal/daily/point"
PARAMETERS = "PRECTOTCORR,T2M_MAX,T2M_MIN"
DRY_SPELL_THRESHOLD_MM = 1.0   # a day with < 1mm rain counts as "dry" for dry-spell runs
HOT_DAY_THRESHOLD_C = 35.0     # maize/bean heat-stress reference threshold

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "nasa_power_cache"


def _cache_path(lat: float, lon: float, start: date, end: date) -> Path:
    key = f"{lat:.3f}_{lon:.3f}_{start.isoformat()}_{end.isoformat()}.json"
    return CACHE_DIR / key


def fetch_daily_point(lat: float, lon: float, start: date, end: date,
                       max_retries: int = 3) -> dict:
    """Fetch raw daily PRECTOTCORR/T2M_MAX/T2M_MIN for one point and date range.

    Caches to disk (data/nasa_power_cache/) since the Kayonza pilot and demo
    reruns hit the same historical windows repeatedly and this must stay out
    of the live per-request path in production.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = _cache_path(lat, lon, start, end)
    if cache_file.exists():
        return json.loads(cache_file.read_text())

    params = {
        "parameters": PARAMETERS,
        "community": "AG",
        "longitude": lon,
        "latitude": lat,
        "start": start.strftime("%Y%m%d"),
        "end": end.strftime("%Y%m%d"),
        "format": "JSON",
    }
    last_exc: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            resp = requests.get(POWER_API_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            props = data.get("properties", {}).get("parameter", {})
            if not props:
                raise ValueError(f"NASA POWER returned no parameter data: {data.get('messages')}")
            cache_file.write_text(json.dumps(data))
            return data
        except Exception as exc:  # noqa: BLE001 - we want to retry any transient failure
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"NASA POWER fetch failed after {max_retries} attempts for "
                        f"({lat},{lon}) {start}..{end}: {last_exc}")


def _year_shifted_window(window_start: date, window_end: date, year_offset: int) -> tuple[date, date]:
    """Shift a planting->harvest window to a different year, preserving month/day
    and the across-year-boundary span (e.g. Sept->Feb seasons)."""
    span_days = (window_end - window_start).days
    new_start = date(window_start.year + year_offset, window_start.month, window_start.day)
    new_end = new_start + timedelta(days=span_days)
    return new_start, new_end


def _longest_dry_spell(daily_rain_mm: list[float]) -> int:
    longest = 0
    current = 0
    for v in daily_rain_mm:
        if v < DRY_SPELL_THRESHOLD_MM:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def compute_climate_evidence(crop_id: str, lat: float, lon: float,
                              window_start: date, window_end: date,
                              years_back: int = 10,
                              reference_year: Optional[int] = None) -> ClimateEvidence:
    """Compute historical climate evidence for a planting->harvest window.

    Re-queries the same calendar window across `years_back` prior years
    (ending at `reference_year`, default: the window_start's own year minus 1,
    so we always use *completed* historical seasons, not an in-progress one).
    """
    if reference_year is None:
        reference_year = window_start.year - 1

    rainfall_by_year: dict[int, float] = {}
    dry_spell_by_year: dict[int, int] = {}
    tmax_values: list[float] = []
    tmin_values: list[float] = []
    hot_day_counts: list[int] = []
    years_analyzed: list[int] = []

    today = date.today()
    for offset in range(years_back, 0, -1):
        year = reference_year - years_back + offset
        y_start, y_end = _year_shifted_window(window_start, window_end, year - window_start.year)
        if y_end >= today:
            continue  # skip incomplete/future windows
        try:
            raw = fetch_daily_point(lat, lon, y_start, y_end)
        except RuntimeError:
            continue  # skip years NASA POWER can't serve rather than fabricate data
        params = raw["properties"]["parameter"]
        rain_series = [v for v in params["PRECTOTCORR"].values() if v != -999.0]
        tmax_series = [v for v in params["T2M_MAX"].values() if v != -999.0]
        tmin_series = [v for v in params["T2M_MIN"].values() if v != -999.0]
        if not rain_series:
            continue

        rainfall_by_year[year] = round(sum(rain_series), 1)
        dry_spell_by_year[year] = _longest_dry_spell(rain_series)
        tmax_values.extend(tmax_series)
        tmin_values.extend(tmin_series)
        hot_day_counts.append(sum(1 for t in tmax_series if t >= HOT_DAY_THRESHOLD_C))
        years_analyzed.append(year)

    if not years_analyzed:
        raise RuntimeError(f"No completed historical years available for window "
                            f"{window_start}..{window_end} at ({lat},{lon})")

    return ClimateEvidence(
        crop_id=crop_id,
        window_start=window_start,
        window_end=window_end,
        years_analyzed=years_analyzed,
        mean_total_rainfall_mm=round(sum(rainfall_by_year.values()) / len(rainfall_by_year), 1),
        rainfall_by_year_mm=rainfall_by_year,
        mean_longest_dry_spell_days=round(sum(dry_spell_by_year.values()) / len(dry_spell_by_year), 1),
        longest_dry_spell_by_year_days=dry_spell_by_year,
        mean_tmax_c=round(sum(tmax_values) / len(tmax_values), 1),
        mean_tmin_c=round(sum(tmin_values) / len(tmin_values), 1),
        days_tmax_above_35c_mean=round(sum(hot_day_counts) / len(hot_day_counts), 1),
    )
