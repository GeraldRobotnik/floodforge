import requests
from typing import Any, Dict, Optional

BASE_URL = "https://api.waterdata.usgs.gov/ogcapi/v0"

# Expand anytime
TEXAS_SITES = [
    "08166200",  # Guadalupe River at Kerrville, TX
    "08168500",  # Guadalupe River at Comfort, TX
    "08171000",  # Guadalupe River at Spring Branch, TX
    "08176500",  # Guadalupe River at New Braunfels, TX
]

_session = requests.Session()
_session.headers.update({"User-Agent": "FloodForge/0.1 (+local dev)"})

def get_monitoring_location(monitoring_location_number: str) -> Optional[Dict[str, Any]]:
    """
    Look up metadata (name + coords) for a single monitoring location.

    NOTE:
    monitoring-locations collection filters by `monitoring_location_number`.
    """
    url = f"{BASE_URL}/collections/monitoring-locations/items"

    params = {
        "f": "json",
        "monitoring_location_number": monitoring_location_number,  # <-- FIX
        "limit": 1,
    }

    try:
        resp = _session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None

    features = data.get("features", []) or []
    if not features:
        return None

    feature = features[0] or {}
    props = feature.get("properties", {}) or {}
    geom = feature.get("geometry", {}) or {}
    coords = geom.get("coordinates") or [None, None]

    # GeoJSON order is [lon, lat]
    lon = coords[0] if len(coords) > 0 else None
    lat = coords[1] if len(coords) > 1 else None

    return {
        "id": props.get("monitoring_location_number") or props.get("id"),
        "name": props.get("monitoring_location_name") or props.get("name"),
        "lat": lat,
        "lon": lon,
    }


def get_latest_gage_height(monitoring_location_id: str) -> Optional[Dict[str, Any]]:
    """
    Get the most recent gage-height (parameter 00065) for a single site.
    latest-continuous supports `monitoring_location_id`.
    """
    url = f"{BASE_URL}/collections/latest-continuous/items"
    params = {
        "f": "json",
        "monitoring_location_id": monitoring_location_id,
        "parameter_code": "00065",  # gage height
        "limit": 1,
        "skipGeometry": "true",
    }

    try:
        resp = _session.get(url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None

    features = data.get("features", []) or []
    if not features:
        return None

    props = features[0].get("properties", {}) or {}
    return {
        "monitoring_location_id": props.get("monitoring_location_id"),
        "time": props.get("time"),
        "value": props.get("value"),
        "unit": props.get("unit_of_measure"),
        "parameter_code": props.get("parameter_code"),
    }