import io
import json
import time
from datetime import datetime, timezone
import pandas as pd
import requests

# Bounding Box: East Asia (0-60°N, 80-145°E)
LAT_MIN, LAT_MAX = 0.0, 60.0
LON_MIN, LON_MAX = 80.0, 145.0

# NOAA AWC Official Live Cache File (Updated globally every 60 seconds)
AWC_CACHE_URL = "https://aviationweather.gov/data/cache/metars.cache.csv.gz"
STATION_LIST_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WeatherDataScript/1.0"
    )
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
                }

        print(f"✓ Catalog ready with {len(catalog)} East Asian ICAO records.")
        return catalog
    except Exception as e:
        print(f"⚠️ Catalog build warning: {e}")
        return {}


def fetch_awc_cache_data(catalog):
    print("Downloading global live weather cache from NOAA AWC...")
    try:
        resp = requests.get(AWC_CACHE_URL, headers=HEADERS, timeout=20)

        if resp.status_code != 200:
            print(f"⚠️ NOAA Cache download returned HTTP {resp.status_code}")
            return False

        # Read the gzipped CSV directly into Pandas, skipping the 5-line metadata header
        df = pd.read_csv(
            io.BytesIO(resp.content), compression="gzip", skiprows=5
        )
        df.columns = df.columns.str.lower()

        # Clean coordinates and numeric values
        df = df.dropna(subset=["latitude", "longitude", "temp_c"])

        # Filter strictly for East Asia Bounding Box
        ea_mask = (
            (df["latitude"] >= LAT_MIN)
            & (df["latitude"] <= LAT_MAX)
            & (df["longitude"] >= LON_MIN)
            & (df["longitude"] <= LON_MAX)
        )
        ea_df = df[ea_mask].copy()

        if ea_df.empty:
            print("⚠️ No observations match the East Asia bounding box.")
            return False

        features = []
        for _, row in ea_df.iterrows():
            icao = str(row.get("station_id", "UNK")).strip()
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            temp = float(row["temp_c"])
            dewp = (
                float(row["dewpoint_c"])
                if pd.notna(row.get("dewpoint_c"))
                else round(temp - 2.0, 1)
            )

            meta = catalog.get(icao, {})

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
                "properties": {
                    "station_id": icao,
                    "name": meta.get("name", icao),
                    "country": meta.get("country", ""),
                    "time": str(
                        row.get(
                            "observation_time",
                            datetime.now(timezone.utc).strftime(
                                "%Y-%m-%d %H:%M UTC"
                            ),
                        )
                    ),
                    "temp": round(temp, 1),
                    "dewpoint": round(dewp, 1),
                    "slp": round(
                        float(
                            row.get("sea_level_pressure_mb")
                            if pd.notna(row.get("sea_level_pressure_mb"))
                            else 1013.2
                        ),
                        1,
                    ),
                    "wind_dir": int(
                        row.get("wind_dir_degrees")
                        if pd.notna(row.get("wind_dir_degrees"))
                        else 0
                    ),
                    "wind_spd": int(
                        row.get("wind_speed_kt")
                        if pd.notna(row.get("wind_speed_kt"))
                        else 0
                    ),
                },
            })

        geojson = {"type": "FeatureCollection", "features": features}
        with open("synoptic_data.json", "w") as f:
            json.dump(geojson, f, indent=2)

        print(
            f"✓ Success: Filtered {len(features)} East Asia observations from"
            " global cache -> synoptic_data.json"
        )
        return True

    except Exception as e:
        print(f"❌ Cache processing failed: {e}")
        return False


def main():
    catalog = build_east_asia_wmo_catalog()

    while True:
        print(
            "\n--- Sync Cycle:"
            f" {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')} ---"
        )

        success = fetch_awc_cache_data(catalog)
        if not success:
            print("⚠️ Sync failed. Retrying in 60 seconds...")
            time.sleep(60)
            continue

        print("Sleeping 15 minutes until next cycle...")
        time.sleep(7200)


if __name__ == "__main__":
    main()