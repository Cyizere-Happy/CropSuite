"""Integration test against the real NASA POWER API (no mocking) for the
Kayonza pilot point. Network-dependent; skipped automatically if NASA POWER
is unreachable rather than failing the whole suite on a transient outage.
"""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fieldshift.nasa_power import compute_climate_evidence

KAYONZA_LAT, KAYONZA_LON = -1.883, 30.644


def test_real_nasa_power_data_for_kayonza_season_a_window():
    try:
        evidence = compute_climate_evidence(
            "maize", KAYONZA_LAT, KAYONZA_LON,
            date(2025, 9, 15), date(2026, 1, 15), years_back=5,
        )
    except RuntimeError as exc:
        pytest.skip(f"NASA POWER unreachable: {exc}")

    assert evidence.years_analyzed, "expected at least one completed historical year"
    assert 0 < evidence.mean_total_rainfall_mm < 3000, "sanity bound on seasonal rainfall for this region"
    assert 0 <= evidence.mean_longest_dry_spell_days <= 123
    assert 15 < evidence.mean_tmax_c < 40
    assert evidence.source.startswith("NASA POWER")


def test_different_windows_produce_different_evidence():
    """Window actually matters: a dry-season window and a wet-season window
    at the same point must not collapse to the same rainfall figure.
    """
    try:
        wet = compute_climate_evidence("maize", KAYONZA_LAT, KAYONZA_LON,
                                        date(2025, 3, 1), date(2025, 5, 31), years_back=5)
        dry = compute_climate_evidence("maize", KAYONZA_LAT, KAYONZA_LON,
                                        date(2025, 6, 15), date(2025, 8, 31), years_back=5)
    except RuntimeError as exc:
        pytest.skip(f"NASA POWER unreachable: {exc}")

    assert wet.mean_total_rainfall_mm != dry.mean_total_rainfall_mm
