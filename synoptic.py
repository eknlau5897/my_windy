import io
import json
import time
from datetime import datetime, timezone
import pandas as pd
import requests

# Bounding Box: East Asia (0-60°N, 80-145°E)
LAT_MIN, LAT_MAX = 0.0, 60.0
LON_MIN, LON_MAX = 80.0, 145.0

# Official Live Global METAR Cache File from NOAA AWC
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
        resp = requests.get(AWC_CACHE_URL, headers=HEADERS, timeout=25)

        if resp.status_code != 200:
            print(f"⚠️ NOAA Cache download returned HTTP {resp.status_code}")
            return False

        # Load CSV into memory
        raw_bytes = io.BytesIO(resp.content)

        # Dynamic Header Locator: Scan raw bytes to find where the actual header starts
        # This prevents breaking if NOAA changes the number of comment/metadata lines at top
        header_row_idx = 0
        raw_lines = io.TextIOWrapper(
            io.BytesIO(resp.content), encoding="utf-8", errors="ignore"
        )
        for idx, line in enumerate(raw_lines):
            line_lower = line.lower()
            if "raw_text" in line_lower or "station" in line_lower:
                header_row_idx = idx
                break

        # Re-read CSV starting directly from the detected header line
        raw_bytes.seek(0)
        df = pd.read_csv(
            raw_bytes, compression="gzip", skiprows=header_row_idx
        )
        df.columns = df.columns.str.lower().str.strip()

        # Handle column naming variations (New AWC schema vs Legacy schema)
        lat_col = "lat" if "lat" in df.columns else "latitude"
        lon_col = "lon" if "lon" in df.columns else "longitude"
        temp_col = "temp" if "temp" in df.columns else "temp_c"
        dewp_col = "dewp" if "dewp" in df.columns else "dewpoint_c"
        id_col = "station_id" if "station_id" in df.columns else "icao_id"
        time_col = (
            "observation_time"
            if "observation_time" in df.columns
            else "report_time"
        )

        # Ensure required columns were identified
        missing_cols = [
            c
            for c in [lat_col, lon_col, temp_col]
            if c not in df.columns
        ]
        if missing_cols:
            print(f"⚠️ Missing columns in dataset: {missing_cols}")
            print(f"Available columns: {list(df.columns)}")
            return False

        # Clean numerical types
        df[lat_col] = pd.to_numeric(df[lat_col], errors="coerce")
        df[lon_col] = pd.to_numeric(df[lon_col], errors="coerce")
        df[temp_col] = pd.to_numeric(df[temp_col], errors="coerce")

        df = df.dropna(subset=[lat_col, lon_col, temp_col])

        # Spatial Filter: East Asia Bounding Box
        ea_mask = (
            (df[lat_col] >= LAT_MIN)
            & (df[lat_col] <= LAT_MAX)
            & (df[lon_col] >= LON_MIN)
            & (df[lon_col] <= LON_MAX)
        )
        ea_df = df[ea_mask].copy()

        if ea_df.empty:
            print("⚠️ No observations match the East Asia bounding box.")
            return False

        features = []
        for _, row in ea_df.iterrows():
            icao = (
                str(row.get(id_col, "UNK")).strip()
                if id_col in row
                else "UNK"
            )
            lat = float(row[lat_col])
            lon = float(row[lon_col])
            temp = float(row[temp_col])

            dewp = (
                float(row[dewp_col])
                if dewp_col in row and pd.notna(row[dewp_col])
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
                            time_col,
                            datetime.now(timezone.utc).strftime(
                                "%Y-%m-%d %H:%M UTC"
                            ),
                        )
                    ),
                    "temp": round(temp, 1),
                    "dewpoint": round(dewp, 1),
                    "slp": round(
                        float(
                            row.get("slp", 1013.2)
                            if "slp" in row and pd.notna(row["slp"])
                            else 1013.2
                        ),
                        1,
                    ),
                    "wind_dir": int(
                        row.get("wdir", 0)
                        if "wdir" in row and pd.notna(row["wdir"])
                        else 0
                    ),
                    "wind_spd": int(
                        row.get("wspd", 0)
                        if "wspd" in row and pd.notna(row["wspd"])
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
            print("⚠️ Sync failed. Retrying in 2 hours...")
            time.sleep(7200)
            continue

        print("Sleeping 2 hours until next cycle...")
        time.sleep(7200)


if __name__ == "__main__":
    main()