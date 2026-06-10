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

import json
import math
import os
import time
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
        from_en = route.get("from_E", "").lower()
        to_en = route.get("to_E", "").lower()
        from_tc = route.get("from_C", "")
        to_tc = route.get("to_C", "")

        # Check if route serves airport
        combined = f"{from_en} {to_en} {from_tc} {to_tc}".lower()
        if not any(kw in combined for kw in airport_keywords):
            continue

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
            lat = round(float(s.get("stopLatitude", 0) or 0), 5)
            lng = round(float(s.get("stopLongitude", 0) or 0), 5)
            if lat == 0:
                continue
            stops_list.append({
                "stop_id": str(s.get("stopId", "")),
                "seq": int(s.get("sequence", 0) or 0),
                "name_en": s.get("stopName_E", ""),
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
            "orig_en": route.get("from_E", ""),
            "dest_en": route.get("to_E", ""),
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
    and add congestion color mapping per road segment.
    """
    print("Fetching TD traffic speed map...")
    primary_url = "https://resource.data.one.gov.hk/td/speedmap/speedmap.json"
    timestamp = datetime.now(timezone.utc).isoformat()

    data = fetch_json(primary_url, "TD speed map")

    if data is None:
        return {
            "updated": timestamp,
            "available": False,
            "road_segments": [],
        }

    # Process speed map data and add color mapping
    road_segments = []

    # The speedmap.json contains route segments with speed data
    # Structure varies but typically has link-level speed info
    if isinstance(data, dict):
        # Try different known structures
        links = data.get("LINK", data.get("link", data.get("data", [])))
        if isinstance(links, list):
            for link in links:
                speed = None
                if isinstance(link, dict):
                    # Extract speed - field names vary
                    speed = (link.get("TRAFFIC_SPEED") or
                             link.get("trafficSpeed") or
                             link.get("CurrentSpeed") or
                             link.get("CURRENT_SPEED"))
                    if speed is not None:
                        try:
                            speed = float(speed)
                        except (ValueError, TypeError):
                            speed = None

                    road_name = (link.get("ROAD_EN") or
                                 link.get("road_en") or
                                 link.get("LINK_DESCRIPTION_EN") or
                                 link.get("linkDescriptionEn") or "")

                    region = (link.get("REGION") or
                              link.get("region") or "")

                    link_id = (link.get("LINK_ID") or
                               link.get("linkId") or
                               link.get("link_id") or "")

                    start_lat = link.get("START_LATITUDE") or link.get("startLatitude")
                    start_lng = link.get("START_LONGITUDE") or link.get("startLongitude")
                    end_lat = link.get("END_LATITUDE") or link.get("endLatitude")
                    end_lng = link.get("END_LONGITUDE") or link.get("endLongitude")

                    segment = {
                        "link_id": str(link_id),
                        "road_name": road_name,
                        "region": region,
                        "speed_kmh": speed,
                        "color": speed_to_color(speed),
                    }

                    # Add coordinates if available
                    if start_lat and start_lng:
                        try:
                            segment["start_lat"] = float(start_lat)
                            segment["start_lng"] = float(start_lng)
                        except (ValueError, TypeError):
                            pass
                    if end_lat and end_lng:
                        try:
                            segment["end_lat"] = float(end_lat)
                            segment["end_lng"] = float(end_lng)
                        except (ValueError, TypeError):
                            pass

                    road_segments.append(segment)

    # Also try fetching the link geometry data for road coordinates
    print("Fetching TD speed map link geometry...")
    geo_url = "https://resource.data.one.gov.hk/td/speedmap/speedmap-linksets.json"
    geo_data = fetch_json(geo_url, "TD link geometry")

    link_geometry = {}
    if geo_data and isinstance(geo_data, dict):
        features = geo_data.get("features", [])
        if isinstance(features, list):
            for feature in features:
                props = feature.get("properties", {})
                geom = feature.get("geometry", {})
                lid = str(props.get("LINK_ID", props.get("link_id", "")))
                if lid and geom.get("coordinates"):
                    link_geometry[lid] = {
                        "coordinates": geom["coordinates"],
                        "type": geom.get("type", "LineString"),
                    }

    # Merge geometry with speed data
    for segment in road_segments:
        lid = segment.get("link_id", "")
        if lid in link_geometry:
            segment["geometry"] = link_geometry[lid]

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
