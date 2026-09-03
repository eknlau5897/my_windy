import json
import time
from datetime import datetime, timezone
import pandas as pd
import requests

# Bounding Box: East Asia (0-60°N, 80-145°E)
LAT_MIN, LAT_MAX = 0.0, 60.0
LON_MIN, LON_MAX = 80.0, 145.0

# NOAA Aviation Weather Center (AWC) Official Live METAR / SYNOP API
AWC_API_URL = "https://aviationweather.gov/api/data/metar"
STATION_LIST_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WeatherDataScript/1.0"
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

        catalog = {}
        for _, row in ea_stations.iterrows():
            icao = str(row.get("icao", "")).strip()
            if icao and icao != "nan":
                catalog[icao] = {
                    "name": str(row.get("station name", icao)),
                    "country": str(row.get("ctry", "")),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                }

        print(f"✓ Catalog ready with {len(catalog)} East Asian ICAO records.")
        return catalog
    except Exception as e:
        print(f"⚠️ Catalog build warning: {e}")
        return {}


def fetch_awc_realtime_data(catalog):
    print("Fetching live global surface observations from NOAA AWC...")
    try:
        # Fetch global decoded METARs in JSON format
        params = {"format": "json", "hours": 2}

        resp = requests.get(
            AWC_API_URL, params=params, headers=HEADERS, timeout=20
        )

        if resp.status_code != 200:
            print(f"⚠️ AWC API returned HTTP status {resp.status_code}")
            return False

        try:
            data = resp.json()
        except json.JSONDecodeError:
            print("⚠️ Response from NOAA AWC was not valid JSON.")
            return False

        features = []

        for item in data:
            lat = item.get("lat")
            lon = item.get("lon")
            icao = item.get("icaoId", "")

            # If coords aren't in payload, look them up in our catalog
            if (lat is None or lon is None) and icao in catalog:
                lat = catalog[icao]["lat"]
                lon = catalog[icao]["lon"]

            if lat is None or lon is None:
                continue

            # Check if point falls within East Asia bounding box
            if LAT_MIN <= lat <= LAT_MAX and LON_MIN <= lon <= LON_MAX:
                temp = item.get("temp")
                dewp = item.get("dewp")

                if temp is not None:
                    meta = catalog.get(icao, {})

                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [float(lon), float(lat)],
                        },
                        "properties": {
                            "station_id": icao,
                            "name": meta.get("name", item.get("name", icao)),
                            "country": meta.get("country", ""),
                            "time": item.get(
                                "reportTime",
                                datetime.now(timezone.utc).strftime(
                                    "%Y-%m-%d %H:%M UTC"
                                ),
                            ),
                            "temp": round(float(temp), 1),
                            "dewpoint": round(float(dewp), 1)
                            if dewp is not None
                            else round(float(temp) - 2.0, 1),
                            "slp": round(float(item.get("slp", 1013.2)), 1),
                            "wind_dir": int(item.get("wdir", 0)),
                            "wind_spd": int(item.get("wspd", 0)),
                        },
                    })

        if features:
            geojson = {"type": "FeatureCollection", "features": features}
            with open("synoptic_data.json", "w") as f:
                json.dump(geojson, f, indent=2)

            print(
                f"✓ Success: Wrote {len(features)} East Asia observations to"
                " synoptic_data.json"
            )
            return True

        print("⚠️ No observations matched East Asia bounding box.")
        return False

    except Exception as e:
        print(f"❌ Fetch error: {e}")
        return False


def main():
    catalog = build_east_asia_wmo_catalog()

    while True:
        print(
            "\n--- Sync Cycle:"
            f" {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} ---"
        )

        success = fetch_awc_realtime_data(catalog)
        if not success:
            print("⚠️ Fetch failed. Retrying in 60 seconds...")
            time.sleep(60)
            continue

        print("Sleeping 15 minutes until next cycle...")
        time.sleep(7200)


if __name__ == "__main__":
    main()