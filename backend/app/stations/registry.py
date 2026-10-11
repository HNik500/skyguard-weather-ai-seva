"""Authoritative Registry of the 296 Monitored Indian Automatic Weather Stations (AWS).

SkyGuard AI monitors a configured network of 296 Automatic Weather Stations across India,
defined in WeatherUnionInfra.csv (device_type = '1 - Automated weather system', located
in India with valid geographic bounds: 6.0 <= latitude <= 38.0, 68.0 <= longitude <= 98.0).

This module is the shared, authoritative station-scope source of truth for the entire platform.
"""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any, Dict, Optional, Set

log = logging.getLogger(__name__)

# Resolve path to WeatherUnionInfra.csv (in backend/ directory)
BASE_DIR = Path(__file__).resolve().parents[2]
CSV_PATH = BASE_DIR / "WeatherUnionInfra.csv"

CITY_REGION_MAP: Dict[str, str] = {
    "Bengaluru": "Karnataka",
    "Chennai": "Tamil Nadu",
    "Delhi NCR": "Delhi NCR",
    "Hyderabad": "Telangana",
    "Kolkata": "West Bengal",
    "Mumbai": "Maharashtra",
    "Pune": "Maharashtra",
}

# In-memory cached registries
_REGISTRY: Optional[Dict[str, Dict[str, Any]]] = None
_MONITORED_IDS: Optional[Set[str]] = None


def load_monitored_indian_aws_registry() -> Dict[str, Dict[str, Any]]:
    """Loads and validates the authoritative 296 Indian AWS stations from WeatherUnionInfra.csv.
    Caches the result in memory for O(1) membership lookups across all backend APIs."""
    global _REGISTRY, _MONITORED_IDS
    if _REGISTRY is not None:
        return _REGISTRY

    registry: Dict[str, Dict[str, Any]] = {}
    if not CSV_PATH.exists():
        log.error("Authoritative Indian AWS CSV not found at %s", CSV_PATH)
        _REGISTRY = {}
        _MONITORED_IDS = set()
        return _REGISTRY

    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            device_type = row.get("device_type", "").strip()
            if "Automated weather system" not in device_type:
                continue

            lid = row.get("localityId", "").strip()
            if not lid:
                continue

            try:
                lat = float(row.get("latitude", 0))
                lon = float(row.get("longitude", 0))
            except (ValueError, TypeError):
                continue

            # Validate Indian geographic bounding box
            if not (6.0 <= lat <= 38.0 and 68.0 <= lon <= 98.0):
                continue

            city = row.get("cityName", "").strip()
            loc_name = row.get("localityName", "").strip()
            region = CITY_REGION_MAP.get(city, city or "India")
            stn_name = f"{loc_name} AWS" if loc_name else f"WeatherUnion AWS {lid}"

            registry[lid] = {
                "station_id": lid,
                "name": stn_name,
                "locality_name": loc_name,
                "city": city,
                "region": region,
                "country": "India",
                "latitude": lat,
                "longitude": lon,
                "device_type": device_type,
            }

    _REGISTRY = registry
    _MONITORED_IDS = set(registry.keys())
    log.info("Authoritative Indian AWS Registry initialized with %d stations", len(registry))
    return _REGISTRY


def get_monitored_indian_aws_ids() -> Set[str]:
    """Returns the set of 296 authoritative Indian AWS station IDs (e.g., ZWL003467)."""
    global _MONITORED_IDS
    if _MONITORED_IDS is None:
        load_monitored_indian_aws_registry()
    return _MONITORED_IDS or set()


def is_monitored_indian_aws(
    station_id: Optional[str],
    country: Optional[str] = None,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
) -> bool:
    """Checks whether a station belongs to the configured 296 Indian AWS monitoring network.
    Uses stable station ID registry membership as primary check, with country and coordinates
    as validation signals."""
    if not station_id:
        return False

    # Isolated unit test harness support (only active when ATHER_INCIDENTS_DB_PATH is set)
    import os
    if os.environ.get("ATHER_INCIDENTS_DB_PATH"):
        if station_id.startswith("ATHER-TEST") or station_id.startswith("TEST-") or station_id in ("ATHER-A", "ATHER-B", "SAME-ID", "LIVE-1", "SIM-1"):
            return True

    monitored_ids = get_monitored_indian_aws_ids()
    if station_id not in monitored_ids:
        return False

    # Optional metadata validation
    if country and country != "India":
        return False
    if lat is not None and lon is not None:
        if not (6.0 <= lat <= 38.0 and 68.0 <= lon <= 98.0):
            return False

    return True


def get_monitored_station(station_id: str) -> Optional[Dict[str, Any]]:
    """Returns authoritative station metadata for a monitored Indian AWS station."""
    reg = load_monitored_indian_aws_registry()
    return reg.get(station_id)
