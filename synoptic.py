from datetime import datetime, timedelta
import json
import time
from metpy.calc import dewpoint_from_relative_humidity
from metpy.units import units
import pandas as pd
from pyisd import IsdLite

# Spatial Bounds: East Asia / Western Pacific (0-60N, 80-145E)
LAT_MIN, LAT_MAX = 0.0, 60.0
LON_MIN, LON_MAX = 80.0, 145.0


def fetch_synoptic_geojson(isd_client, limit=100):
    """Query station observations natively using pyisd's raw metadata frame."""
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Querying station"
        " observations..."
    )

    # 1. Access internal metadata table directly & normalize columns to lowercase
    meta = isd_client.raw_metadata.copy()
    meta.columns = meta.columns.str.lower()

    # 2. Filter spatial bounding box safely
    in_bounds = meta[
        (meta["lat"] >= LAT_MIN)
        & (meta["lat"] <= LAT_MAX)
        & (meta["lon"] >= LON_MIN)
        & (meta["lon"] <= LON_MAX)
    ].copy()

    # 3. Filter for active stations (BEGIN / END date checks)
    in_bounds["end_num"] = pd.to_numeric(in_bounds["end"], errors="coerce")
    active = in_bounds[in_bounds["end_num"] >= 20250101]

    print(f"Found {len(active)} candidate stations within bounding box.")

    # Limit station count to prevent initial rate throttling
    target_stations = active.head(limit)

    now = datetime.utcnow()
    start_dt = (now - timedelta(days=5)).strftime("%Y-%m-%d")
    end_dt = now.strftime("%Y-%m-%d")

    features = []

    for idx, row in target_stations.iterrows():
        try:
            # Safely extract integer USAF ID
            usaf_val = int(row["usaf"])

            # Query pyisd passing integer USAF ID
            data_dict = isd_client.get_data(
                start=start_dt, end=end_dt, station_id=usaf_val
            )

            if not data_dict:
                continue

            # Extract DataFrame from dictionary
            df = list(data_dict.values())[0]

            if df is None or df.empty:
                continue

            # Clean temperature values
            df["temp"] = pd.to_numeric(df["temp"], errors="coerce")
            df_valid = df.dropna(subset=["temp"])

            if df_valid.empty:
                continue

            # Get latest observation row
            latest = df_valid.iloc[-1]
            temp = float(latest["temp"])

            # Relative humidity fallback
            rh_val = latest.get("rh", 50.0)
            rh = (
                50.0
                if (pd.isna(rh_val) or rh_val is None)
                else float(rh_val)
            )

            # Dew Point calculation with MetPy
            dp = round(
                dewpoint_from_relative_humidity(
                    temp * units.degC, rh * units.percent
                ).magnitude,
                1,
            )

            # Extract coordinates (fallback to metadata row if absent in row index)
            lat_coord = float(
                latest.get("latitude", latest.get("lat", row.get("lat", 0.0)))
            )
            lon_coord = float(
                latest.get("longitude", latest.get("lon", row.get("lon", 0.0)))
            )

            st_id_str = (
                f"{str(row['usaf']).zfill(6)}-{str(row['wban']).zfill(5)}"
            )

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon_coord, lat_coord],
                },
                "properties": {
                    "station_id": st_id_str,
                    "time": latest.name.strftime("%Y-%m-%d %H:%M UTC"),
                    "temp": round(temp, 1),
                    "dewpoint": dp,
                    "slp": round(
                        float(latest.get("slp", 1013.2) or 1013.2), 1
                    ),
                    "wind_dir": int(latest.get("winddir", 0) or 0),
                    "wind_spd": int(latest.get("windspeed", 0) or 0),
                },
            })

        except Exception:
            continue

    geojson = {"type": "FeatureCollection", "features": features}

    with open("synoptic_data.json", "w") as f:
        json.dump(geojson, f)

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Successfully generated"
        f" synoptic_data.json with {len(features)} live station plots."
    )


if __name__ == "__main__":
    isd = IsdLite(crs=4326)

    while True:
        fetch_synoptic_geojson(isd, limit=100)
        print("Sleeping 2 hours until next fetch...")
        time.sleep(7200)