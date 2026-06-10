"""
Fetch all bus routes travelling to Hong Kong International Airport (HKIA),
collect real-time traffic speed data with congestion color mapping,
and save bus stop coordinates for each route.

Data sources:
- KMB/Long Win Bus API (A, E, N, NA, S routes operated by LWB)
- CTB (Citybus) API (A, E routes operated by CTB)
- NLB (New Lantao Bus) API (routes serving airport area)
- HK Transport Dept speed map for traffic congestion data
"""

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
TIMEOUT = 15
STOP_SLEEP = 0.25

# ── Airport bus route numbers ────────────────────────────────────────────────
# A-routes (Airbus premium), E-routes (External), S-routes (Shuttle),
# N/NA-routes (Overnight/Night Airport)

# KMB/Long Win Bus airport routes
KMB_AIRPORT_ROUTES = [
    # A-routes (Airbus)
    "A31", "A32", "A33", "A33X", "A34", "A36", "A37", "A38", "A41", "A41P",
    "A43", "A43P", "A47X",
    # E-routes (External)
    "E31", "E32", "E33", "E34", "E41", "E42",
    # N-routes (Night)
    "N30", "N31", "N42",
    # NA-routes (Night Airport)
    "NA33", "NA34", "NA40", "NA41", "NA43", "NA47",
    # S-routes (Shuttle)
    "S64",
]

# CTB (Citybus) airport routes
CTB_AIRPORT_ROUTES = [
    # A-routes (Airbus)
    "A10", "A11", "A12", "A17", "A20", "A21", "A22", "A23", "A26", "A29", "A29P",
    # E-routes
    "E11", "E21", "E22", "E23",
    # N/NA-routes
    "N11", "N21", "N23", "N26", "N29",
    "NA11", "NA12", "NA20", "NA21", "NA29",
    # S-routes
    "S1", "S56",
]

# Traffic speed color thresholds (km/h)
SPEED_THRESHOLDS = {
    "green": 50,       # >= 50 km/h: free flow
    "yellow": 30,      # >= 30 km/h: moderate
    "orange": 15,      # >= 15 km/h: slow
    "red": 0,          # < 15 km/h: congested
}


def fetch_json(url, label=""):
    """Fetch JSON from URL with error handling."""
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"  [WARN] Failed to fetch {label or url}: {exc}")
        return None


def calc_bearing(lat1, lng1, lat2, lng2):
    """Return compass bearing (0-360 deg) from point A to point B."""
    lat1r, lng1r, lat2r, lng2r = (math.radians(v) for v in (lat1, lng1, lat2, lng2))
    dlng = lng2r - lng1r
    x = math.sin(dlng) * math.cos(lat2r)
    y = (math.cos(lat1r) * math.sin(lat2r) -
         math.sin(lat1r) * math.cos(lat2r) * math.cos(dlng))
    return round((math.degrees(math.atan2(x, y)) + 360) % 360, 1)


def add_bearings(stops):
    """Add bearing_to_next field to each stop."""
    for i, stop in enumerate(stops):
        if i + 1 < len(stops):
            stop["bearing_to_next"] = calc_bearing(
                stop["lat"], stop["lng"],
                stops[i + 1]["lat"], stops[i + 1]["lng"],
            )
        elif len(stops) >= 2:
            stop["bearing_to_next"] = calc_bearing(
                stops[i - 1]["lat"], stops[i - 1]["lng"],
                stop["lat"], stop["lng"],
            )
        else:
            stop["bearing_to_next"] = 0


def speed_to_color(speed_kmh):
    """Convert speed in km/h to congestion color."""
    if speed_kmh is None or speed_kmh < 0:
        return "grey"
    if speed_kmh >= SPEED_THRESHOLDS["green"]:
        return "green"
    if speed_kmh >= SPEED_THRESHOLDS["yellow"]:
        return "yellow"
    if speed_kmh >= SPEED_THRESHOLDS["orange"]:
        return "orange"
    return "red"


# ─────────────────────────────────────────────────────────────────────────────
# KMB / Long Win Bus
# ─────────────────────────────────────────────────────────────────────────────

def fetch_kmb_airport_routes():
    """Fetch KMB/LWB airport bus routes with stop coordinates."""
    print("Fetching KMB/LWB all stops (bulk)...")
    stops_data = fetch_json(
        "https://data.etabus.gov.hk/v1/transport/kmb/stop", "KMB all stops"
    )
    stop_cache = {}
    if stops_data:
        for s in stops_data.get("data", []):
            stop_cache[s["stop"]] = {
                "name_en": s.get("name_en", ""),
                "lat": round(float(s.get("lat", 0) or 0), 5),
                "lng": round(float(s.get("long", 0) or 0), 5),
            }
    print(f"  Cached {len(stop_cache)} KMB/LWB stops")

    print("Fetching KMB/LWB route list...")
    routes_data = fetch_json(
        "https://data.etabus.gov.hk/v1/transport/kmb/route", "KMB routes"
    )
    if not routes_data:
        return {}

    route_info_map = {}
    for r in routes_data.get("data", []):
        key = (r.get("route", "").upper(), r.get("bound", "O"),
               r.get("service_type", "1"))
        route_info_map[key] = r

    routes_output = {}
    for route_no in KMB_AIRPORT_ROUTES:
        rn = route_no.upper()
        for bound in ("O", "I"):
            route_info = route_info_map.get((rn, bound, "1"))
            if not route_info:
                continue

            direction = "outbound" if bound == "O" else "inbound"
            service_type = route_info.get("service_type", "1")

            url = (
                f"https://data.etabus.gov.hk/v1/transport/kmb/route-stop"
                f"/{rn}/{direction}/{service_type}"
            )
            print(f"  KMB/LWB {rn} {direction}...")
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
                    "seq": seq,
                    "name_en": cached["name_en"],
                    "lat": cached["lat"],
                    "lng": cached["lng"],
                })

            if not stops_list:
                continue

            add_bearings(stops_list)
            key = f"KMB_{rn}_{bound}"
            routes_output[key] = {
                "company": "KMB/LWB",
                "route": rn,
                "bound": bound,
                "service_type": service_type,
                "orig_en": route_info.get("orig_en", ""),
                "dest_en": route_info.get("dest_en", ""),
                "stops": stops_list,
            }
            print(f"    -> {len(stops_list)} stops")
            time.sleep(0.05)

    return routes_output


# ─────────────────────────────────────────────────────────────────────────────
# CTB (Citybus)
# ─────────────────────────────────────────────────────────────────────────────

def fetch_ctb_airport_routes():
    """Fetch CTB airport bus routes with stop coordinates."""
    print("Fetching CTB route list...")
    routes_data = fetch_json(
        "https://rt.data.gov.hk/v2/transport/citybus/route/ctb", "CTB routes"
    )
    if not routes_data:
        return {}

    route_map = {}
    for r in routes_data.get("data", []):
        route_map[r.get("route", "").upper()] = r

    stop_cache = {}
    routes_output = {}

    for route_no in CTB_AIRPORT_ROUTES:
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
                            "lat": round(float(d.get("lat", 0) or 0), 5),
                            "lng": round(float(d.get("long", 0) or 0), 5),
                        }
                    else:
                        stop_cache[sid] = {"name_en": "", "lat": 0.0, "lng": 0.0}

                cached = stop_cache[sid]
                if cached["lat"] == 0:
                    continue
                stops_list.append({
                    "stop_id": sid,
                    "seq": seq,
                    "name_en": cached["name_en"],
                    "lat": cached["lat"],
                    "lng": cached["lng"],
                })

            if not stops_list:
                continue

            add_bearings(stops_list)
            key = f"CTB_{rn}_{bound}"
            routes_output[key] = {
                "company": "CTB",
                "route": rn,
                "bound": bound,
                "service_type": "1",
                "orig_en": route_info.get("orig_en", ""),
                "dest_en": route_info.get("dest_en", ""),
                "stops": stops_list,
            }
            print(f"  CTB {rn} {direction}: {len(stops_list)} stops")

    return routes_output


# ─────────────────────────────────────────────────────────────────────────────
# NLB (New Lantao Bus) - airport area routes
# ─────────────────────────────────────────────────────────────────────────────

def fetch_nlb_airport_routes():
    """Fetch NLB routes that serve the airport area."""
    print("Fetching NLB route list...")
    routes_data = fetch_json(
        "https://rt.data.gov.hk/v2/transport/nlb/route.php?action=list",
        "NLB routes",
    )
    if not routes_data:
        return {}

    # NLB routes serving airport: filter by destination/origin containing "Airport"
    airport_keywords = ["airport", "機場", "asia world", "亞洲博覽"]
    routes_output = {}

    for route in routes_data.get("routes", []):
        route_id = str(route.get("routeId", ""))
        route_no = route.get("routeNo", "")
        # NLB API uses routeName_e/routeName_c with "from > to" format
        route_name_en = route.get("routeName_e", "") or ""
        route_name_tc = route.get("routeName_c", "") or ""
        # Also try legacy field names
        from_en = route.get("from_E", "") or ""
        to_en = route.get("to_E", "") or ""
        from_tc = route.get("from_C", "") or ""
        to_tc = route.get("to_C", "") or ""

        # Check if route serves airport
        combined = (
            f"{route_name_en} {route_name_tc} "
            f"{from_en} {to_en} {from_tc} {to_tc}"
        ).lower()
        if not any(kw in combined for kw in airport_keywords):
            continue

        # Parse origin/destination from route name "A > B"
        if " > " in route_name_en:
            parts = route_name_en.split(" > ", 1)
            orig_en = parts[0].strip()
            dest_en = parts[1].strip()
        else:
            orig_en = from_en or route_name_en
            dest_en = to_en or ""

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
            lat_val = (s.get("stopLatitude") or s.get("latitude") or 0)
            lng_val = (s.get("stopLongitude") or s.get("longitude") or 0)
            lat = round(float(lat_val or 0), 5)
            lng = round(float(lng_val or 0), 5)
            if lat == 0:
                continue
            stop_name = (s.get("stopName_E") or s.get("stopName_e") or
                         s.get("stopLocation_e") or "")
            stops_list.append({
                "stop_id": str(s.get("stopId", "")),
                "seq": int(s.get("sequence", 0) or len(stops_list) + 1),
                "name_en": stop_name,
                "lat": lat,
                "lng": lng,
            })

        if not stops_list:
            continue

        add_bearings(stops_list)
        key = f"NLB_{route_id}"
        routes_output[key] = {
            "company": "NLB",
            "route": route_no,
            "route_id": route_id,
            "bound": "O",
            "service_type": "1",
            "orig_en": orig_en,
            "dest_en": dest_en,
            "stops": stops_list,
        }
        print(f"  NLB {route_no}: {len(stops_list)} stops")

    return routes_output


# ─────────────────────────────────────────────────────────────────────────────
# Traffic Speed Data with Congestion Color Mapping
# ─────────────────────────────────────────────────────────────────────────────

def fetch_traffic_data():
    """
    Fetch real-time traffic speed data from HK Transport Department
    using the raw detector speed XML and detector locations CSV.

    Data sources:
    - Detector locations: static CSV with lat/lng per detector
    - Raw speed data: real-time XML with speed per detector per lane
    """
    print("Fetching TD detector locations...")
    timestamp = datetime.now(timezone.utc).isoformat()

    # 1. Fetch detector locations (static CSV)
    locations_url = (
        "https://static.data.gov.hk/td/traffic-data-strategic-major-roads"
        "/info/traffic_speed_volume_occ_info.csv"
    )
    locations_data = fetch_json_or_text(locations_url, "TD detector locations")
    if locations_data is None:
        return {
            "updated": timestamp,
            "available": False,
            "road_segments": [],
        }

    # Parse CSV (has BOM)
    text = locations_data.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text))
    detector_info = {}
    id_field = None
    for row in reader:
        if id_field is None:
            # First field might have BOM prefix
            id_field = [k for k in row.keys() if "AID_ID_Number" in k][0]
        det_id = row.get(id_field, "").strip()
        if not det_id:
            continue
        try:
            lat = float(row.get("Latitude", 0) or 0)
            lng = float(row.get("Longitude", 0) or 0)
        except (ValueError, TypeError):
            continue
        if lat == 0 or lng == 0:
            continue
        detector_info[det_id] = {
            "road_name": row.get("Road_EN", "").strip(),
            "district": row.get("District", "").strip(),
            "direction": row.get("Direction", "").strip(),
            "lat": lat,
            "lng": lng,
            "rotation": float(row.get("Rotation", 0) or 0),
        }
    print(f"  Loaded {len(detector_info)} detector locations")

    # 2. Fetch real-time speed data (XML)
    print("Fetching TD raw speed data...")
    speed_url = (
        "https://resource.data.one.gov.hk/td/traffic-detectors/rawSpeedVol-all.xml"
    )
    speed_resp = fetch_json_or_text(speed_url, "TD raw speed XML")
    if speed_resp is None:
        return {
            "updated": timestamp,
            "available": False,
            "road_segments": [],
        }

    # Parse XML
    try:
        root = ET.fromstring(speed_resp)
    except ET.ParseError as exc:
        print(f"  [WARN] Failed to parse speed XML: {exc}")
        return {
            "updated": timestamp,
            "available": False,
            "road_segments": [],
        }

    # Use the latest period
    periods = root.find("periods")
    if periods is None or len(list(periods)) == 0:
        return {
            "updated": timestamp,
            "available": False,
            "road_segments": [],
        }

    latest_period = list(periods)[-1]
    detectors_elem = latest_period.find("detectors")
    if detectors_elem is None:
        return {
            "updated": timestamp,
            "available": False,
            "road_segments": [],
        }

    # 3. Extract average speed per detector
    detector_speeds = {}
    for det in detectors_elem:
        det_id = det.find("detector_id")
        if det_id is None:
            continue
        det_id = det_id.text

        lanes = det.find("lanes")
        if lanes is None:
            continue

        speeds = []
        for lane in lanes:
            speed_el = lane.find("speed")
            valid_el = lane.find("valid")
            if (speed_el is not None and speed_el.text and
                    valid_el is not None and valid_el.text == "Y"):
                try:
                    speeds.append(float(speed_el.text))
                except (ValueError, TypeError):
                    pass

        if speeds:
            detector_speeds[det_id] = round(sum(speeds) / len(speeds), 1)

    print(f"  Got speed data for {len(detector_speeds)} detectors")

    # 4. Group detectors by road and create segments
    # Group detectors by road name to create road segments
    road_groups = {}
    for det_id, speed in detector_speeds.items():
        info = detector_info.get(det_id)
        if info is None:
            continue
        road = info["road_name"]
        # Simplify road name (remove "near XXX" part for grouping)
        base_road = road.split(" near ")[0].split(" - ")[0].strip()
        if base_road not in road_groups:
            road_groups[base_road] = []
        road_groups[base_road].append({
            "det_id": det_id,
            "lat": info["lat"],
            "lng": info["lng"],
            "speed": speed,
            "direction": info["direction"],
            "rotation": info["rotation"],
            "full_name": road,
        })

    # 5. Build road segments by connecting adjacent detectors on the same road
    road_segments = []
    for road_name, detectors in road_groups.items():
        if len(detectors) < 2:
            # Single detector: create a small segment using rotation/direction
            det = detectors[0]
            rotation_rad = math.radians(det["rotation"])
            # Create a ~200m line segment in the detector's direction
            delta = 0.001  # ~100m
            end_lat = det["lat"] + delta * math.cos(rotation_rad)
            end_lng = det["lng"] + delta * math.sin(rotation_rad)
            road_segments.append({
                "link_id": det["det_id"],
                "road_name": det["full_name"],
                "speed_kmh": det["speed"],
                "color": speed_to_color(det["speed"]),
                "start_lat": det["lat"],
                "start_lng": det["lng"],
                "end_lat": round(end_lat, 6),
                "end_lng": round(end_lng, 6),
            })
        else:
            # Multiple detectors: sort by latitude/longitude and connect
            # Sort by a combination that follows road direction
            detectors.sort(key=lambda d: (d["lat"], d["lng"]))
            for i in range(len(detectors) - 1):
                d1 = detectors[i]
                d2 = detectors[i + 1]
                avg_speed = round((d1["speed"] + d2["speed"]) / 2, 1)
                road_segments.append({
                    "link_id": f"{d1['det_id']}_{d2['det_id']}",
                    "road_name": road_name,
                    "speed_kmh": avg_speed,
                    "color": speed_to_color(avg_speed),
                    "start_lat": d1["lat"],
                    "start_lng": d1["lng"],
                    "end_lat": d2["lat"],
                    "end_lng": d2["lng"],
                })

    print(f"  Created {len(road_segments)} road segments")

    return {
        "updated": timestamp,
        "available": True,
        "total_segments": len(road_segments),
        "road_segments": road_segments,
        "color_legend": {
            "green": "Free flow (>= 50 km/h)",
            "yellow": "Moderate (30-49 km/h)",
            "orange": "Slow (15-29 km/h)",
            "red": "Congested (< 15 km/h)",
            "grey": "No data",
        },
    }


def fetch_json_or_text(url, label=""):
    """Fetch URL content as text (for CSV/XML) with error handling."""
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.text
    except Exception as exc:
        print(f"  [WARN] Failed to fetch {label or url}: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    os.makedirs(DATA_DIR, exist_ok=True)

    # 1. Fetch airport bus routes
    print("=" * 60)
    print("Collecting Airport Bus Routes")
    print("=" * 60)

    routes_output = {}

    kmb = fetch_kmb_airport_routes()
    routes_output.update(kmb)
    print(f"KMB/LWB airport routes: {len(kmb)} direction-routes")

    ctb = fetch_ctb_airport_routes()
    routes_output.update(ctb)
    print(f"CTB airport routes: {len(ctb)} direction-routes")

    nlb = fetch_nlb_airport_routes()
    routes_output.update(nlb)
    print(f"NLB airport routes: {len(nlb)} routes")

    # Save airport bus routes
    routes_path = os.path.join(DATA_DIR, "airport_bus_routes.json")
    with open(routes_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "updated": datetime.now(timezone.utc).isoformat(),
                "description": "Bus routes to/from Hong Kong International Airport",
                "total_routes": len(routes_output),
                "routes": routes_output,
            },
            f,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    print(f"\nSaved {len(routes_output)} airport routes -> {routes_path}")

    # 2. Fetch traffic speed data with congestion colors
    print("\n" + "=" * 60)
    print("Collecting Traffic Speed Data")
    print("=" * 60)

    traffic_data = fetch_traffic_data()
    traffic_path = os.path.join(DATA_DIR, "airport_traffic_speeds.json")
    with open(traffic_path, "w", encoding="utf-8") as f:
        json.dump(traffic_data, f, ensure_ascii=False, indent=2)
    print(f"Saved traffic data ({traffic_data['total_segments'] if traffic_data.get('available') else 0} segments) -> {traffic_path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
