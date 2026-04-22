import json
import math
import os
import time
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TIMEOUT = 15
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


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def fetch_json(url, label=""):
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
            stop["bearing_to_next"] = stops[i - 1]["bearing_to_next"] if i > 0 else 0


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
        return {}

    routes_output = {}

    for route in routes_data.get("routes", []):
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

    out_path = os.path.join(DATA_DIR, "hk_bus_routes.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "updated": datetime.now(timezone.utc).isoformat(),
                "routes":  routes_output,
            },
            f,
            ensure_ascii=False,
            separators=(",", ":"),   # compact JSON -- no extra whitespace
        )
    print(f"Saved {len(routes_output)} total routes -> {out_path}")


# ─────────────────────────────────────────────────────────────────────────────
# Traffic speeds
# ─────────────────────────────────────────────────────────────────────────────

def fetch_traffic_speeds():
    print("Fetching TD traffic speed map...")
    primary_url = "https://resource.data.one.gov.hk/td/speedmap/speedmap.json"
    out_path    = os.path.join(DATA_DIR, "hk_traffic_speeds.json")
    timestamp   = datetime.now(timezone.utc).isoformat()

    data = fetch_json(primary_url, "TD speed map")
    if data is not None:
        if isinstance(data, dict):
            data["updated"]   = timestamp
            data["available"] = True
        else:
            data = {"updated": timestamp, "available": True, "data": data}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Saved traffic speed data -> {out_path}")
        return

    fallback = {"updated": timestamp, "available": False}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fallback, f, ensure_ascii=False, indent=2)
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
