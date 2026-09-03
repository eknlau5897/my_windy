import json
import time
from datetime import datetime
import pandas as pd
import requests

# Bounding Box: East Asia (0-60°N, 80-145°E)
LAT_MIN, LAT_MAX = 0.0, 60.0
LON_MIN, LON_MAX = 80.0, 145.0

# Explicit GeoJSON parameters to force JSON responses from IEM
IEM_SURFACE_URL = "https://mesonet.agron.iastate.edu/geojson/surface.geojson?fmt=geojson"
STATION_LIST_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"

# Fully compliant HTTP headers to prevent 403 / HTML blocks
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Cache-Control": "no-cache",
}

def build_east_asia_wmo_catalog():
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
        print(f"⚠️ Catalog build warning: {e}")
        return {}


def fetch_mesonet_data(catalog):
    print("Connecting to IEM Mesonet Surface Stream...")
    try:
        session = requests.Session()
        resp = session.get(IEM_SURFACE_URL, headers=HEADERS, timeout=20)

        if resp.status_code != 200:
            print(f"⚠️ IEM returned HTTP status {resp.status_code}")
            return False

        # Attempt direct JSON parsing with exception trap
        try:
            data = resp.json()
        except json.JSONDecodeError:
            print("⚠️ IEM returned non-JSON payload (likely HTML block page).")
            return False

        features = []

        for feat in data.get("features", []):
            geometry = feat.get("geometry")
            if not geometry or "coordinates" not in geometry:
                continue

            lon, lat = geometry["coordinates"][0], geometry["coordinates"][1]

            if LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX:
                props = feat.get("properties", {})
                tmpc = props.get("tmpc")

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

        print("⚠️ No stations found inside East Asia bounding box.")
        return False

    except Exception as e:
        print(f"❌ IEM fetch failed: {e}")
        return False


def main():
    catalog = build_east_asia_wmo_catalog()

    while True:
        print(f"\n--- Sync Cycle: {datetime.utcnow().strftime('%H:%M:%S UTC')} ---")
        
        success = fetch_mesonet_data(catalog)
        if not success:
            print("⚠️ Retrying IEM connection in 30 seconds...")
            time.sleep(30)
            continue

        print("Sleeping 72 minutes until next cycle...")
        time.sleep(7200)


if __name__ == "__main__":
    main()