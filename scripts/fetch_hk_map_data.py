import csv
import io
import json
import math
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")

# Per-request timeouts: (connect_timeout_s, read_timeout_s)
CONNECT_TIMEOUT = 10
READ_TIMEOUT    = 30

# Retry settings for transient network errors
MAX_RETRIES  = 3
RETRY_BACKOFF = [1, 2]   # seconds to sleep before retry 2, 3

STOP_SLEEP = 0.25   # seconds between per-stop API calls (CTB)

# ── KMB: major/busy routes, both directions will be fetched ──────────────────
KMB_BUSY_ROUTES = [
    "1", "2", "3", "5", "6", "11", "12", "13", "21", "22",
    "27", "36", "40", "42", "43", "60X", "61X", "67X", "68X", "72",
    "74X", "80X", "85", "91", "95", "96R", "98", "101", "102", "260",
]

# ── CTB/NWFB: busy routes across the harbour and main corridors ──────────────
CTB_BUSY_ROUTES = [
    "1", "5A", "6", "7", "10", "11", "15", "23", "26",
    "40", "41A", "42", "43X", "70", "104", "109", "170", "701",
]

# ── TD traffic speed: detector locations (static CSV) ────────────────────────
TD_DETECTOR_LOCATIONS_URL = (
    "https://static.data.gov.hk/td/traffic-data-strategic-major-roads"
    "/info/traffic_speed_volume_occ_info.csv"
)
# TD traffic speed: raw speed/volume XML (updated ~every 1 minute)
TD_RAW_SPEED_XML_URL = (
    "https://resource.data.one.gov.hk/td/traffic-detectors/rawSpeedVol-all.xml"
)

# Map HK district names (as found in the TD detector CSV) to region codes
# used by HKMap.html: HK (Hong Kong Island), K (Kowloon),
# NTE (New Territories East), NTW (New Territories West).
DISTRICT_TO_REGION = {
    "Central and Western": "HK",
    "Eastern":             "HK",
    "Southern":            "HK",
    "Wan Chai":            "HK",
    "Islands":             "NTW",
    "Kwai Tsing":          "NTW",
    "Kowloon City":        "K",
    "Kwun Tong":           "K",
    "Sham Shui Po":        "K",
    "Wong Tai Sin":        "K",
    "Yau Tsim Mong":       "K",
    "North":               "NTE",
    "Sai Kung":            "NTE",
    "Sha Tin":             "NTE",
    "Tai Po":              "NTE",
    "Tsuen Wan":           "NTW",
    "Tuen Mun":            "NTW",
    "Yuen Long":           "NTW",
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_retryable(exc):
    """Return True if the exception represents a transient network condition."""
    retryable_types = (
        requests.exceptions.Timeout,
        requests.exceptions.ConnectionError,
    )
    return isinstance(exc, retryable_types)


def _is_retryable_http_error(exc):
    """Return True if an HTTPError represents a transient server condition (5xx)."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return False
    return resp.status_code >= 500


def fetch_json(url, label=""):
    """Fetch JSON from *url* with connect/read timeouts and bounded retries.

    Returns the parsed JSON object on success, or None on permanent failure.
    4xx client errors (e.g. 404) are permanent and are not retried.
    5xx server errors and network timeouts/connection errors are retried.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            if _is_retryable_http_error(exc):
                exc_to_retry = exc   # 5xx: may succeed on a different attempt
            else:
                print(f"  [WARN] Failed to fetch {label or url}: {exc}")
                return None          # 4xx: permanent, no retry
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as exc:
            exc_to_retry = exc
        except Exception as exc:
            print(f"  [WARN] Failed to fetch {label or url}: {exc}")
            return None

        # Reached here means a retryable error occurred
        if attempt < MAX_RETRIES:
            delay = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
            print(
                f"  [WARN] {label or url}: {exc_to_retry} "
                f"(attempt {attempt}/{MAX_RETRIES}, retrying in {delay}s)"
            )
            time.sleep(delay)
        else:
            print(f"  [WARN] Failed to fetch {label or url}: {exc_to_retry}")
            return None
    return None


def fetch_text(url, label=""):
    """Fetch raw text (CSV / XML) with connect/read timeouts and bounded retries.

    Returns the response body as a string on success, or None on failure.
    4xx client errors are permanent; 5xx and network errors are retried.
    """
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                timeout=(CONNECT_TIMEOUT, READ_TIMEOUT),
            )
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.HTTPError as exc:
            if _is_retryable_http_error(exc):
                exc_to_retry = exc
            else:
                print(f"  [WARN] Failed to fetch {label or url}: {exc}")
                return None
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError) as exc:
            exc_to_retry = exc
        except Exception as exc:
            print(f"  [WARN] Failed to fetch {label or url}: {exc}")
            return None

        if attempt < MAX_RETRIES:
            delay = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
            print(
                f"  [WARN] {label or url}: {exc_to_retry} "
                f"(attempt {attempt}/{MAX_RETRIES}, retrying in {delay}s)"
            )
            time.sleep(delay)
        else:
            print(f"  [WARN] Failed to fetch {label or url}: {exc_to_retry}")
            return None
    return None


def load_existing_json(path):
    """Load and return the JSON from *path*, or None if missing / unreadable."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


def calc_bearing(lat1, lng1, lat2, lng2):
    """Return compass bearing (0-360 deg) from point A to point B."""
    lat1r, lng1r, lat2r, lng2r = (math.radians(v) for v in (lat1, lng1, lat2, lng2))
    dlng = lng2r - lng1r
    x = math.sin(dlng) * math.cos(lat2r)
    y = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlng)
    return round((math.degrees(math.atan2(x, y)) + 360) % 360, 1)


def add_bearings(stops):
    """Add bearing_to_next field to each stop (pre-computed server-side)."""
    for i, stop in enumerate(stops):
        if i + 1 < len(stops):
            stop["bearing_to_next"] = calc_bearing(
                stop["lat"], stop["lng"],
                stops[i + 1]["lat"], stops[i + 1]["lng"],
            )
        else:
            # Last stop: use the approach bearing (second-to-last -> last)
            if len(stops) >= 2:
                stop["bearing_to_next"] = calc_bearing(
                    stops[i - 1]["lat"], stops[i - 1]["lng"],
                    stop["lat"], stop["lng"],
                )
            else:
                stop["bearing_to_next"] = 0


# ─────────────────────────────────────────────────────────────────────────────
# KMB
# ─────────────────────────────────────────────────────────────────────────────

def fetch_kmb_routes():
    # 1. Bulk-fetch all KMB stops in a single call
    print("Fetching KMB all stops (bulk)...")
    stops_data = fetch_json("https://data.etabus.gov.hk/v1/transport/kmb/stop", "KMB all stops")
    stop_cache = {}
    if stops_data:
        for s in stops_data.get("data", []):
            stop_cache[s["stop"]] = {
                "name_en": s.get("name_en", ""),
                "lat":     round(float(s.get("lat",  0) or 0), 5),
                "lng":     round(float(s.get("long", 0) or 0), 5),
            }
    print(f"  Cached {len(stop_cache)} KMB stops")

    # 2. Fetch full route list
    print("Fetching KMB route list...")
    routes_data = fetch_json("https://data.etabus.gov.hk/v1/transport/kmb/route", "KMB routes")
    if not routes_data:
        return {}

    route_info_map = {}
    for r in routes_data.get("data", []):
        key = (r.get("route", "").upper(), r.get("bound", "O"), r.get("service_type", "1"))
        route_info_map[key] = r

    # 3. Fetch route-stop sequences for busy routes (both directions)
    routes_output = {}
    for route_no in KMB_BUSY_ROUTES:
        rn = route_no.upper()
        for bound in ("O", "I"):
            route_info = route_info_map.get((rn, bound, "1"))
            if not route_info:
                continue

            direction    = "outbound" if bound == "O" else "inbound"
            service_type = route_info.get("service_type", "1")

            url = (
                f"https://data.etabus.gov.hk/v1/transport/kmb/route-stop"
                f"/{rn}/{direction}/{service_type}"
            )
            print(f"  KMB {rn} {direction}...")
            stops_resp = fetch_json(url, f"KMB route-stop {rn} {direction}")
            if not stops_resp:
                continue

            stops_list = []
            for entry in stops_resp.get("data", []):
                sid = entry.get("stop")
                seq = int(entry.get("seq", 0))
                cached = stop_cache.get(sid, {"name_en": "", "lat": 0.0, "lng": 0.0})
                if cached["lat"] == 0:
                    continue
                stops_list.append({
                    "stop_id": sid,
                    "seq":     seq,
                    "name_en": cached["name_en"],
                    "lat":     cached["lat"],
                    "lng":     cached["lng"],
                })

            if not stops_list:
                continue

            add_bearings(stops_list)
            key = f"KMB_{rn}_{bound}"
            routes_output[key] = {
                "company":      "KMB",
                "route":        rn,
                "bound":        bound,
                "service_type": service_type,
                "orig_en":      route_info.get("orig_en", ""),
                "dest_en":      route_info.get("dest_en", ""),
                "stops":        stops_list,
            }
            print(f"    -> {len(stops_list)} stops")
            time.sleep(0.05)

    return routes_output


# ─────────────────────────────────────────────────────────────────────────────
# CTB / NWFB  (Citybus; per-stop lookups with cache)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ctb_routes():
    print("Fetching CTB route list...")
    routes_data = fetch_json("https://rt.data.gov.hk/v2/transport/citybus/route/ctb", "CTB routes")
    if not routes_data:
        return {}

    route_map = {}
    for r in routes_data.get("data", []):
        route_map[r.get("route", "").upper()] = r

    stop_cache = {}
    routes_output = {}

    for route_no in CTB_BUSY_ROUTES:
        rn = route_no.upper()
        if rn not in route_map:
            print(f"  [SKIP] CTB route {rn} not found")
            continue

        route_info = route_map[rn]

        for direction in ("outbound", "inbound"):
            bound = "O" if direction == "outbound" else "I"
            url = (
                f"https://rt.data.gov.hk/v2/transport/citybus"
                f"/route-stop/CTB/{rn}/{direction}"
            )
            stops_resp = fetch_json(url, f"CTB route-stop {rn} {direction}")
            if not stops_resp or not stops_resp.get("data"):
                continue

            stops_list = []
            for entry in stops_resp["data"]:
                sid = entry.get("stop")
                seq = int(entry.get("seq", 0))

                if sid not in stop_cache:
                    detail = fetch_json(
                        f"https://rt.data.gov.hk/v2/transport/citybus/stop/{sid}",
                        f"CTB stop {sid}",
                    )
                    time.sleep(STOP_SLEEP)
                    if detail and detail.get("data"):
                        d = detail["data"]
                        stop_cache[sid] = {
                            "name_en": d.get("name_en", ""),
                            "lat":     round(float(d.get("lat",  0) or 0), 5),
                            "lng":     round(float(d.get("long", 0) or 0), 5),
                        }
                    else:
                        stop_cache[sid] = {"name_en": "", "lat": 0.0, "lng": 0.0}

                cached = stop_cache[sid]
                if cached["lat"] == 0:
                    continue
                stops_list.append({
                    "stop_id": sid,
                    "seq":     seq,
                    "name_en": cached["name_en"],
                    "lat":     cached["lat"],
                    "lng":     cached["lng"],
                })

            if not stops_list:
                continue

            add_bearings(stops_list)
            key = f"CTB_{rn}_{bound}"
            routes_output[key] = {
                "company":      "CTB",
                "route":        rn,
                "bound":        bound,
                "service_type": "1",
                "orig_en":      route_info.get("orig_en", ""),
                "dest_en":      route_info.get("dest_en", ""),
                "stops":        stops_list,
            }
            print(f"  CTB {rn} {direction}: {len(stops_list)} stops")

    return routes_output


# ─────────────────────────────────────────────────────────────────────────────
# NLB  (New Lantao Bus -- route-stop API includes coordinates directly)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_nlb_routes():
    print("Fetching NLB route list...")
    routes_data = fetch_json(
        "https://rt.data.gov.hk/v2/transport/nlb/route.php?action=list",
        "NLB routes",
    )
    if not routes_data:
        print("  [WARN] NLB route list fetch failed; skipping NLB")
        return {}

    all_routes = routes_data.get("routes", [])
    if not all_routes:
        print("  [WARN] NLB route list returned 0 routes")
        return {}

    routes_output = {}

    for route in all_routes:
        route_id = str(route.get("routeId", ""))
        route_no = route.get("routeNo", "")

        url = (
            f"https://rt.data.gov.hk/v2/transport/nlb/stop.php"
            f"?action=list&routeId={route_id}"
        )
        stops_resp = fetch_json(url, f"NLB route {route_no}")
        if not stops_resp:
            continue
        time.sleep(0.2)

        stops_list = []
        for s in stops_resp.get("stops", []):
            lat = round(float(s.get("stopLatitude",  0) or 0), 5)
            lng = round(float(s.get("stopLongitude", 0) or 0), 5)
            if lat == 0:
                continue
            stops_list.append({
                "stop_id": str(s.get("stopId", "")),
                "seq":     int(s.get("sequence", 0) or 0),
                "name_en": s.get("stopName_E", ""),
                "lat":     lat,
                "lng":     lng,
            })

        if not stops_list:
            continue

        add_bearings(stops_list)
        key = f"NLB_{route_id}"
        routes_output[key] = {
            "company":      "NLB",
            "route":        route_no,
            "route_id":     route_id,
            "bound":        "O",
            "service_type": "1",
            "orig_en":      route.get("from_E", ""),
            "dest_en":      route.get("to_E", ""),
            "stops":        stops_list,
        }
        print(f"  NLB {route_no}: {len(stops_list)} stops")

    return routes_output


# ─────────────────────────────────────────────────────────────────────────────
# Combined bus data entry point
# ─────────────────────────────────────────────────────────────────────────────

def fetch_bus_data():
    out_path     = os.path.join(DATA_DIR, "hk_bus_routes.json")
    existing     = load_existing_json(out_path)
    existing_routes = existing.get("routes", {}) if existing else {}

    routes_output = {}

    kmb = fetch_kmb_routes()
    routes_output.update(kmb)
    print(f"KMB total: {len(kmb)} direction-routes")

    ctb = fetch_ctb_routes()
    routes_output.update(ctb)
    print(f"CTB total: {len(ctb)} direction-routes")

    nlb = fetch_nlb_routes()
    routes_output.update(nlb)
    print(f"NLB total: {len(nlb)} routes")

    # Preserve existing routes for any provider that returned nothing this run,
    # so a transient outage doesn't erase previously good data.
    if not kmb:
        preserved = {k: v for k, v in existing_routes.items() if k.startswith("KMB_")}
        routes_output.update(preserved)
        print(f"  [INFO] KMB fetch empty; kept {len(preserved)} existing KMB routes")
    if not ctb:
        preserved = {k: v for k, v in existing_routes.items() if k.startswith("CTB_")}
        routes_output.update(preserved)
        print(f"  [INFO] CTB fetch empty; kept {len(preserved)} existing CTB routes")
    if not nlb:
        preserved = {k: v for k, v in existing_routes.items() if k.startswith("NLB_")}
        routes_output.update(preserved)
        print(f"  [INFO] NLB fetch empty; kept {len(preserved)} existing NLB routes")

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(
            {
                "updated": datetime.now(timezone.utc).isoformat(),
                "routes":  routes_output,
            },
            fh,
            ensure_ascii=False,
            separators=(",", ":"),   # compact JSON -- no extra whitespace
        )
    print(f"Saved {len(routes_output)} total routes -> {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Traffic speeds  (TD detector XML + static CSV)
# ─────────────────────────────────────────────────────────────────────────────

def _speed_to_saturation(speed_kmh):
    """Map speed (km/h) to TD road saturation level string."""
    if speed_kmh >= 50:
        return "GOOD"
    elif speed_kmh >= 30:
        return "MODERATE"
    elif speed_kmh >= 15:
        return "BAD"
    else:
        return "VERY BAD"


def _district_to_region(district):
    """Map a district name from the TD CSV to HKMap.html region code."""
    return DISTRICT_TO_REGION.get(district, "K")  # default to Kowloon


def fetch_traffic_speeds():
    """Fetch real-time traffic speed data from the TD detector feeds.

    Uses two sources published by the HK Transport Department:
      1. A static CSV with per-detector location, road name, and district.
      2. A real-time XML with per-detector, per-lane speed readings.

    Outputs hk_traffic_speeds.json with a ``SpeedMapPanel`` array that the
    HKMap.html client recognises directly (no client-side changes needed).
    If either source is unavailable the existing file is kept unchanged
    (last-known-good behaviour); only the ``updated`` and ``available``
    fields are refreshed.
    """
    print("Fetching TD traffic speed data...")
    out_path  = os.path.join(DATA_DIR, "hk_traffic_speeds.json")
    timestamp = datetime.now(timezone.utc).isoformat()

    # ── Step 1: detector locations (static CSV) ───────────────────────────────
    print("  Fetching TD detector locations CSV...")
    csv_text = fetch_text(TD_DETECTOR_LOCATIONS_URL, "TD detector locations")
    if csv_text is None:
        print("  [WARN] TD detector locations unavailable; keeping existing traffic data")
        _preserve_or_write_unavailable(out_path, timestamp)
        return

    # Strip optional BOM and parse
    csv_text = csv_text.lstrip("\ufeff")
    reader   = csv.DictReader(io.StringIO(csv_text))
    detector_info = {}
    id_field_name = None

    for row in reader:
        if id_field_name is None:
            # Locate the AID_ID_Number column (may carry a BOM prefix)
            candidates = [k for k in row.keys() if "AID_ID_Number" in k]
            if not candidates:
                print("  [WARN] AID_ID_Number column not found in CSV; keeping existing data")
                _preserve_or_write_unavailable(out_path, timestamp)
                return
            id_field_name = candidates[0]

        det_id = row.get(id_field_name, "").strip()
        if not det_id:
            continue
        try:
            lat = float(row.get("Latitude",  0) or 0)
            lng = float(row.get("Longitude", 0) or 0)
        except (ValueError, TypeError):
            continue
        if lat == 0 or lng == 0:
            continue
        detector_info[det_id] = {
            "road_name": row.get("Road_EN",   "").strip(),
            "district":  row.get("District",  "").strip(),
            "direction": row.get("Direction", "").strip(),
            "lat":       lat,
            "lng":       lng,
            "rotation":  float(row.get("Rotation", 0) or 0),
        }

    print(f"  Loaded {len(detector_info)} detector locations")

    # ── Step 2: real-time speed XML ───────────────────────────────────────────
    print("  Fetching TD raw speed XML...")
    xml_text = fetch_text(TD_RAW_SPEED_XML_URL, "TD raw speed XML")
    if xml_text is None:
        print("  [WARN] TD speed XML unavailable; keeping existing traffic data")
        _preserve_or_write_unavailable(out_path, timestamp)
        return

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as exc:
        print(f"  [WARN] Failed to parse speed XML: {exc}; keeping existing traffic data")
        _preserve_or_write_unavailable(out_path, timestamp)
        return

    # Use the latest measurement period
    periods = root.find("periods")
    if periods is None or len(list(periods)) == 0:
        print("  [WARN] No periods in speed XML; keeping existing traffic data")
        _preserve_or_write_unavailable(out_path, timestamp)
        return

    latest_period  = list(periods)[-1]
    detectors_elem = latest_period.find("detectors")
    if detectors_elem is None:
        print("  [WARN] No detectors element in latest period; keeping existing traffic data")
        _preserve_or_write_unavailable(out_path, timestamp)
        return

    # ── Step 3: compute average speed per detector ────────────────────────────
    detector_speeds = {}
    for det_elem in detectors_elem:
        det_id_elem = det_elem.find("detector_id")
        if det_id_elem is None:
            continue
        det_id = det_id_elem.text

        lanes_elem = det_elem.find("lanes")
        if lanes_elem is None:
            continue

        valid_speeds = []
        for lane in lanes_elem:
            speed_el = lane.find("speed")
            valid_el = lane.find("valid")
            if (speed_el is not None and speed_el.text
                    and valid_el is not None and valid_el.text == "Y"):
                try:
                    valid_speeds.append(float(speed_el.text))
                except (ValueError, TypeError):
                    pass

        if valid_speeds:
            detector_speeds[det_id] = round(sum(valid_speeds) / len(valid_speeds), 1)

    print(f"  Got speed readings for {len(detector_speeds)} detectors")

    # ── Step 4: group detectors by road and build SpeedMapPanel segments ───────
    # Group detectors on the same base road name together.
    road_groups = {}
    for det_id, speed in detector_speeds.items():
        info = detector_info.get(det_id)
        if info is None:
            continue
        # Strip "near XXX" / "- XXX" suffixes so adjacent detectors cluster
        base_road = info["road_name"].split(" near ")[0].split(" - ")[0].strip()
        if base_road not in road_groups:
            road_groups[base_road] = []
        road_groups[base_road].append({
            "det_id":    det_id,
            "full_name": info["road_name"],
            "district":  info["district"],
            "lat":       info["lat"],
            "lng":       info["lng"],
            "rotation":  info["rotation"],
            "speed":     speed,
        })

    # Build SpeedMapPanel records compatible with HKMap.html normalizeSpeedRecord.
    # Fields used by HKMap.html: REGION, ROAD, TRAFFIC_SPEED,
    # ROAD_SATURATION_LEVEL, start_lat, start_lng, end_lat, end_lng.
    speed_map_panel = []

    for road_name, detectors in road_groups.items():
        if len(detectors) == 1:
            # Single detector: synthesise a short segment using the rotation angle
            det = detectors[0]
            rotation_rad = math.radians(det["rotation"])
            delta        = 0.001  # ~100 m in lat/lng degrees
            speed_map_panel.append({
                "ROAD":                  det["full_name"],
                "TRAFFIC_SPEED":         det["speed"],
                "ROAD_SATURATION_LEVEL": _speed_to_saturation(det["speed"]),
                "REGION":                _district_to_region(det["district"]),
                "start_lat":             det["lat"],
                "start_lng":             det["lng"],
                "end_lat":               round(det["lat"] + delta * math.cos(rotation_rad), 6),
                "end_lng":               round(det["lng"] + delta * math.sin(rotation_rad), 6),
            })
        else:
            # Multiple detectors: sort by position and connect pairs as segments
            detectors.sort(key=lambda d: (d["lat"], d["lng"]))
            for i in range(len(detectors) - 1):
                d1       = detectors[i]
                d2       = detectors[i + 1]
                avg_speed = round((d1["speed"] + d2["speed"]) / 2, 1)
                speed_map_panel.append({
                    "ROAD":                  road_name,
                    "TRAFFIC_SPEED":         avg_speed,
                    "ROAD_SATURATION_LEVEL": _speed_to_saturation(avg_speed),
                    "REGION":                _district_to_region(d1["district"]),
                    "start_lat":             d1["lat"],
                    "start_lng":             d1["lng"],
                    "end_lat":               d2["lat"],
                    "end_lng":               d2["lng"],
                })

    print(f"  Built {len(speed_map_panel)} SpeedMapPanel segments")

    payload = {
        "updated":        timestamp,
        "available":      True,
        "SpeedMapPanel":  speed_map_panel,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    print(f"Saved traffic speed data -> {out_path}")


def _preserve_or_write_unavailable(out_path, timestamp):
    """Keep the existing traffic data file if it contains valid data; otherwise
    write a minimal unavailable placeholder.  This prevents a transient
    provider outage from erasing previously healthy data.
    """
    existing = load_existing_json(out_path)
    if existing and existing.get("available"):
        # Refresh the timestamp so the client knows we attempted an update
        existing["last_attempted"] = timestamp
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(existing, fh, ensure_ascii=False, indent=2)
        print(f"  Kept existing traffic data (last good: {existing.get('updated', 'unknown')})")
    else:
        fallback = {"updated": timestamp, "available": False}
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(fallback, fh, ensure_ascii=False, indent=2)
        print(f"Traffic speed data unavailable; saved placeholder -> {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    fetch_bus_data()
    fetch_traffic_speeds()
    print("Done.")


if __name__ == "__main__":
    main()
