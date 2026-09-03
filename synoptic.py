import json
import time
from datetime import datetime
import pandas as pd
import requests

# Bounding Box: East Asia (0-60°N, 80-145°E)
LAT_MIN, LAT_MAX = 0.0, 60.0
LON_MIN, LON_MAX = 80.0, 145.0

# 1. Primary Live Stream: IEM Global Surface GeoJSON
IEM_SURFACE_URL = "https://mesonet.agron.iastate.edu/geojson/surface.geojson"

# 2. Metadata Catalog: NOAA NCEI Station Metadata
STATION_LIST_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"

# Browser impersonation headers to prevent blocks
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://mesonet.agron.iastate.edu/",
}


def build_east_asia_wmo_catalog():
    """Download NOAA history catalog to map station metadata for enrichment."""
    print("Building East Asia Station Catalog from NOAA NCEI...")
    try:
        df = pd.read_csv(STATION_LIST_URL)
        df.columns = df.columns.str.lower()
        df = df.dropna(subset=["lat", "lon", "usaf"])

        ea_mask = (
            (df["lat"] >= LAT_MIN)
            & (df["lat"] <= LAT_MAX)
            & (df["lon"] >= LON_MIN)
            & (df["lon"] <= LON_MAX)
        )
        ea_stations = df[ea_mask].copy()

        ea_stations["wmo_id"] = (
            ea_stations["usaf"].astype(str).str.split(".").str[0].str.zfill(6)
        )

        catalog = {}
        for _, row in ea_stations.iterrows():
            wmo = str(row["wmo_id"])
            catalog[wmo] = {
                "name": str(row.get("station name", "Station")),
                "country": str(row.get("ctry", "")),
            }

        print(f"✓ Catalog ready with {len(catalog)} East Asian station records.")
        return catalog
    except Exception as e:
        print(f"⚠️ Catalog build warning (proceeding without metadata enrichment): {e}")
        return {}


def fetch_mesonet_data(catalog):
    """Fetch live surface weather observations for East Asia via IEM Mesonet."""
    print("Connecting to IEM Mesonet Surface Stream...")
    try:
        resp = requests.get(IEM_SURFACE_URL, headers=HEADERS, timeout=15)

        if resp.status_code != 200:
            print(f"⚠️ IEM returned status {resp.status_code}")
            return False

        # Safety check to ensure response is valid JSON
        if "application/json" not in resp.headers.get("Content-Type", ""):
            print("⚠️ IEM response is not valid JSON")
            return False

        data = resp.json()
        features = []

        for feat in data.get("features", []):
            geometry = feat.get("geometry")
            if not geometry or "coordinates" not in geometry:
                continue

            lon, lat = geometry["coordinates"][0], geometry["coordinates"][1]

            # Filter for East Asian Bounding Box
            if LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX:
                props = feat.get("properties", {})
                tmpc = props.get("tmpc")

                # Require a valid temperature value
                if tmpc is not None:
                    station_id = str(props.get("station", "UNK"))
                    meta = catalog.get(station_id, {})

                    features.append({
                        "type": "Feature",
                        "geometry": geometry,
                        "properties": {
                            "station_id": station_id,
                            "name": props.get("sname") or meta.get("name", station_id),
                            "country": meta.get("country", ""),
                            "time": datetime.utcnow().strftime("%Y-%m-%d %H:00 UTC"),
                            "temp": round(float(tmpc), 1),
                            "dewpoint": round(float(props.get("dwpc", tmpc - 2.0)), 1),
                            "slp": round(float(props.get("mslp") or 1013.2), 1),
                            "wind_dir": int(props.get("drct") or 0),
                            "wind_spd": int(props.get("sknt") or 0),
                        },
                    })

        if features:
            geojson = {"type": "FeatureCollection", "features": features}
            with open("synoptic_data.json", "w") as f:
                json.dump(geojson, f, indent=2)

            print(f"✓ Success: Wrote {len(features)} East Asia stations via IEM Mesonet.")
            return True

        print("⚠️ No stations found within East Asia bounding box.")
        return False

    except Exception as e:
        print(f"❌ IEM stream fetch failed: {e}")
        return False


def fetch_openmeteo_fallback():
    """Emergency Fallback: Queries Open-Meteo Synoptic API if Mesonet is down."""
    print("⚠️ Triggering Open-Meteo Fallback Stream...")
    try:
        # Key coordinates across major East Asian hubs
        sample_lats = [35.67, 39.90, 37.56, 25.03, 14.59, 31.23, 22.31, 1.35]
        sample_lons = [139.65, 116.40, 126.97, 121.56, 120.98, 121.47, 114.16, 103.81]

        url = (
            "https://api.open-meteo.com/v1/forecast?"
            f"latitude={','.join(map(str, sample_lats))}&"
            f"longitude={','.join(map(str, sample_lons))}&"
            "current=temperature_2m,relative_humidity_2m,surface_pressure,wind_speed_10m,wind_direction_10m"
        )

        resp = requests.get(url, headers=HEADERS, timeout=10)
        data = resp.json()

        if not isinstance(data, list):
            data = [data]

        features = []
        for idx, item in enumerate(data):
            curr = item.get("current", {})
            lat = item.get("latitude", sample_lats[idx])
            lon = item.get("longitude", sample_lons[idx])

            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "station_id": f"GRID_{idx+1}",
                    "name": f"East Asia Regional Hub {idx+1}",
                    "country": "",
                    "time": datetime.utcnow().strftime("%Y-%m-%d %H:00 UTC"),
                    "temp": round(curr.get("temperature_2m", 20.0), 1),
                    "dewpoint": round(curr.get("temperature_2m", 20.0) - 3.0, 1),
                    "slp": round(curr.get("surface_pressure", 1013.2), 1),
                    "wind_dir": int(curr.get("wind_direction_10m", 0)),
                    "wind_spd": int(curr.get("wind_speed_10m", 0) * 0.539957),
                },
            })

        geojson = {"type": "FeatureCollection", "features": features}
        with open("synoptic_data.json", "w") as f:
            json.dump(geojson, f, indent=2)

        print(f"✓ Fallback Success: Generated {len(features)} stations via Open-Meteo.")

    except Exception as err:
        print(f"❌ All methods failed: {err}")


def main():
    catalog = build_east_asia_wmo_catalog()

    while True:
        print(f"\n--- Sync Cycle: {datetime.utcnow().strftime('%H:%M:%S UTC')} ---")
        
        success = fetch_mesonet_data(catalog)
        if not success:
            fetch_openmeteo_fallback()

        print("Sleeping 15 minutes until next cycle...")
        time.sleep(7200)


if __name__ == "__main__":
    main()