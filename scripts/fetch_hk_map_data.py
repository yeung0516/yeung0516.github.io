import json
import os
import time
from datetime import datetime, timezone

import requests

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
TIMEOUT = 15
STOP_SLEEP = 0.5

BUSY_ROUTES = [
    "1", "2", "3", "5", "6", "11", "12", "13", "21", "22",
    "27", "36", "40", "42", "43", "60X", "61X", "67X", "68X", "72",
    "74X", "80X", "85", "91", "95", "96R", "98", "101", "102", "260",
]


def fetch_json(url, label=""):
    try:
        resp = requests.get(url, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"  [WARN] Failed to fetch {label or url}: {exc}")
        return None


def fetch_bus_data():
    print("Fetching KMB all routes...")
    data = fetch_json("https://data.etabus.gov.hk/v1/transport/kmb/route", "KMB routes")
    if not data:
        print("  [ERROR] Could not fetch KMB route list, skipping bus data.")
        return

    all_routes = data.get("data", [])
    route_map = {}
    for r in all_routes:
        route_map[r.get("route", "").upper()] = r

    routes_output = {}
    stop_cache = {}

    for route_no in BUSY_ROUTES:
        route_info = route_map.get(route_no.upper())
        if not route_info:
            print(f"  [SKIP] Route {route_no} not found in KMB route list.")
            continue

        # KMB API: bound "O" = outbound, "I" = inbound; legacy single-direction routes use "1"
        bound = route_info.get("bound", "O")
        direction = "outbound" if bound in ("O", "1") else "inbound"
        service_type = route_info.get("service_type", "1")

        stops_url = (
            f"https://data.etabus.gov.hk/v1/transport/kmb/route-stop"
            f"/{route_no}/{direction}/{service_type}"
        )
        print(f"  Fetching stops for route {route_no} ({direction}, svc {service_type})...")
        stops_data = fetch_json(stops_url, f"route-stop {route_no}")
        if not stops_data:
            continue

        raw_stops = stops_data.get("data", [])
        stops_list = []

        for stop_entry in raw_stops:
            stop_id = stop_entry.get("stop")
            seq = stop_entry.get("seq")

            if stop_id not in stop_cache:
                stop_detail_url = f"https://data.etabus.gov.hk/v1/transport/kmb/stop/{stop_id}"
                detail = fetch_json(stop_detail_url, f"stop {stop_id}")
                time.sleep(STOP_SLEEP)
                if detail and detail.get("data"):
                    d = detail["data"]
                    stop_cache[stop_id] = {
                        "name_en": d.get("name_en", ""),
                        "lat": float(d.get("lat", 0)),
                        "lng": float(d.get("long", 0)),
                    }
                else:
                    stop_cache[stop_id] = {"name_en": "", "lat": 0.0, "lng": 0.0}

            cached = stop_cache[stop_id]
            stops_list.append({
                "stop_id": stop_id,
                "seq": seq,
                "name_en": cached["name_en"],
                "lat": cached["lat"],
                "lng": cached["lng"],
            })

        routes_output[route_no] = {
            "route": route_no,
            "orig_en": route_info.get("orig_en", ""),
            "dest_en": route_info.get("dest_en", ""),
            "stops": stops_list,
        }
        print(f"  Route {route_no}: {len(stops_list)} stops collected.")

    out_path = os.path.join(DATA_DIR, "hk_bus_routes.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {"updated": datetime.now(timezone.utc).isoformat(), "routes": routes_output},
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"Saved {len(routes_output)} routes to {out_path}")


def fetch_traffic_speeds():
    print("Fetching TD traffic speed map...")
    primary_url = "https://resource.data.one.gov.hk/td/speedmap/speedmap.json"
    out_path = os.path.join(DATA_DIR, "hk_traffic_speeds.json")
    timestamp = datetime.now(timezone.utc).isoformat()

    data = fetch_json(primary_url, "TD speed map")
    if data is not None:
        if isinstance(data, dict):
            data["updated"] = timestamp
            data["available"] = True
        else:
            data = {"updated": timestamp, "available": True, "data": data}
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"Saved traffic speed data to {out_path}")
        return

    fallback = {"updated": timestamp, "available": False}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(fallback, f, ensure_ascii=False, indent=2)
    print(f"Traffic speed data unavailable; saved placeholder to {out_path}")


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    fetch_bus_data()
    fetch_traffic_speeds()
    print("Done.")


if __name__ == "__main__":
    main()
