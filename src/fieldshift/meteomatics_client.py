"""Meteomatics near-term forecast client (optional, isolated module).

Credentials are read ONLY from environment variables (METEOMATICS_USERNAME /
METEOMATICS_PASSWORD), loaded from a local .env file via python-dotenv if
present. Nothing here hardcodes a credential, and .env is gitignored.

This module answers a different question than nasa_power.py or
gaez_adapter.py: "what does the short-range forecast say for the next few
days," not "what has historically happened" or "what is the land modeled to
support." Its output (NearTermOutlook) is advisory and is never fed into
feasibility_engine.py's classification -- see models.NearTermOutlook.

If credentials are missing or the API call fails, this returns None rather
than fabricating a forecast; callers must treat a missing outlook as
"forecast unavailable," not as a clean bill of health.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import requests
from dotenv import load_dotenv

from .models import NearTermOutlook

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

METEOMATICS_BASE_URL = "https://api.meteomatics.com"
PARAMETERS = "t_2m:C,precip_24h:mm"


def _credentials() -> Optional[tuple[str, str]]:
    username = os.getenv("METEOMATICS_USERNAME")
    password = os.getenv("METEOMATICS_PASSWORD")
    if not username or not password:
        return None
    return username, password


def credentials_available() -> bool:
    return _credentials() is not None


def fetch_near_term_outlook(lat: float, lon: float, days: int = 7) -> Optional[NearTermOutlook]:
    """Fetch a `days`-ahead daily forecast (mean 2m temp, 24h precipitation)
    starting today. Returns None (not a fabricated forecast) if credentials
    are missing or the request fails.
    """
    creds = _credentials()
    if creds is None:
        return None

    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=days)
    time_range = f"{start.isoformat()}Z--{end.isoformat()}Z:PT24H"
    url = f"{METEOMATICS_BASE_URL}/{time_range}/{PARAMETERS}/{lat},{lon}/json"

    try:
        resp = requests.get(url, auth=creds, timeout=20)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:  # noqa: BLE001 - forecast is advisory; fail closed, not loud
        return None

    daily_tmean: dict[str, float] = {}
    daily_precip: dict[str, float] = {}
    for series in payload.get("data", []):
        param = series.get("parameter", "")
        for coord in series.get("coordinates", []):
            for point in coord.get("dates", []):
                day = point["date"][:10]
                if param.startswith("t_2m"):
                    daily_tmean[day] = point["value"]
                elif param.startswith("precip_24h"):
                    daily_precip[day] = point["value"]

    if not daily_tmean and not daily_precip:
        return None

    return NearTermOutlook(
        latitude=lat, longitude=lon,
        daily_tmean_c=daily_tmean, daily_precip_mm=daily_precip,
    )
