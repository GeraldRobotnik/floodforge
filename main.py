import time
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, Optional, Tuple, List

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from usgs_hello import TEXAS_SITES, get_latest_gage_height, get_monitoring_location

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------------
# Caching + helpers
# ---------------------------

CACHE_TTL_SECONDS = 120  # 60–300 is typical; bumping reduces USGS calls

_loc_cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}
_latest_cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}


def _site_key(site: Any) -> str:
    return str(site)


def _cache_get(cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]], key: str) -> Optional[Dict[str, Any]]:
    hit = cache.get(key)
    if not hit:
        return None
    ts, val = hit
    if time.time() - ts > CACHE_TTL_SECONDS:
        cache.pop(key, None)
        return None
    return val


def _cache_set(cache: Dict[str, Tuple[float, Optional[Dict[str, Any]]]], key: str, val: Optional[Dict[str, Any]]) -> None:
    cache[key] = (time.time(), val)


def cached_loc(site_id: str) -> Optional[Dict[str, Any]]:
    k = _site_key(site_id)
    v = _cache_get(_loc_cache, k)
    if v is not None:
        return v
    v = get_monitoring_location(site_id)
    _cache_set(_loc_cache, k, v)
    return v


def cached_latest(site_id: str) -> Optional[Dict[str, Any]]:
    k = _site_key(site_id)
    v = _cache_get(_latest_cache, k)
    if v is not None:
        return v
    v = get_latest_gage_height(site_id)
    _cache_set(_latest_cache, k, v)
    return v


def _derive_status(low_triggered: bool, high_triggered: bool) -> str:
    if high_triggered:
        return "CRITICAL"
    if low_triggered:
        return "RISING"
    return "NORMAL"


def _pick_name(site_id: str, loc: Optional[Dict[str, Any]]) -> str:
    if loc and loc.get("name"):
        return str(loc["name"])
    return f"USGS Site {site_id}"


def _pick_latlon(loc: Optional[Dict[str, Any]]) -> Tuple[Optional[float], Optional[float]]:
    if not loc:
        return (None, None)
    lat = loc.get("lat")
    lon = loc.get("lon")
    try:
        return (float(lat) if lat is not None else None, float(lon) if lon is not None else None)
    except Exception:
        return (None, None)


def _pick_updated_at(latest: Optional[Dict[str, Any]]) -> str:
    if latest and latest.get("time"):
        return str(latest["time"])
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# ---------------------------
# Routes
# ---------------------------

@app.get("/")
def root_page():
    return FileResponse("static/index.html")


@app.get("/api/health")
def health_check():
    return {"status": "ok"}


@app.get("/api/gauges/texas/latest")
def texas_latest_single():
    site_id = TEXAS_SITES[0]
    latest = cached_latest(site_id)
    loc = cached_loc(site_id)

    if latest is None:
        return {"status": "no_data"}

    data = dict(latest)
    if loc:
        data.update(loc)

    return {"status": "ok", "data": data}


@app.get("/api/gauges/all")
def all_gauges():
    results: List[Dict[str, Any]] = []

    for site_id in TEXAS_SITES:
        latest = cached_latest(site_id)
        loc = cached_loc(site_id)

        if latest:
            entry = dict(latest)
            if loc:
                entry.update(loc)
            results.append(entry)

    return {"status": "ok", "count": len(results), "data": results}


@app.get("/api/sites")
def api_sites():
    """
    iOS contract:
      { "status": "ok", "data": [ {id,name,latitude,longitude,lowTriggered,highTriggered,status,updatedAt}, ... ] }
    """

    def build_one(site_id: str) -> Dict[str, Any]:
        latest = cached_latest(site_id)
        loc = cached_loc(site_id)

        # Placeholder until your physical triggers are integrated
        low_triggered = False
        high_triggered = False

        name = _pick_name(site_id, loc)
        lat, lon = _pick_latlon(loc)
        updated_at = _pick_updated_at(latest)

        return {
            "id": site_id,
            "name": name,
            "latitude": lat,
            "longitude": lon,
            "lowTriggered": low_triggered,
            "highTriggered": high_triggered,
            "status": _derive_status(low_triggered, high_triggered),
            "updatedAt": updated_at,
        }

    sites_out: List[Dict[str, Any]] = []
    max_workers = min(12, max(1, len(TEXAS_SITES)))

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(build_one, s) for s in TEXAS_SITES]
        for f in as_completed(futures):
            sites_out.append(f.result())

    sites_out.sort(key=lambda x: x["name"])
    return {"status": "ok", "data": sites_out}