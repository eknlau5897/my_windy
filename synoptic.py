from datetime import datetime, timedelta
import json
import time
from metpy.calc import dewpoint_from_relative_humidity
from metpy.units import units
import pandas as pd
from pyisd import IsdLite

# Spatial Bounds: East Asia / Western Pacific
LAT_MIN, LAT_MAX = 0.0, 60.0
LON_MIN, LON_MAX = 80.0, 145.0


def fetch_synoptic_geojson(isd_client, limit=100):
    """Query station observations natively using pyisd's raw metadata frame."""
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Querying station"
        " observations..."
    )

    # Access internal metadata table directly
    meta = isd_client.raw_metadata.copy()

    # Filter spatial bounding box
    in_bounds = meta[
        (meta["lat"] >= LAT_MIN)
        & (meta["lat"] <= LAT_MAX)
        & (meta["lon"] >= LON_MIN)
        & (meta["lon"] <= LON_MAX)
    ]

    # Filter for active stations (BEGIN <= current year, END >= recent year)
    active = in_bounds[in_bounds["end"].astype(str).str.startswith("202")]

    print(f"Found {len(active)} active station candidate records.")

    # Limit station count to prevent long initial wait times
    target_stations = active.head(limit)

    now = datetime.utcnow()
    # Query short recent date range
    start_dt = now - timedelta(days=3)
    end_dt = now

    features = []

    for idx, row in target_stations.iterrows():
        try:
            # Query pyisd passing the metadata row directly or usaf integer
            usaf_val = int(row["usaf"])

            # pyisd get_data call using integer USAF
            data_dict = isd_client.get_data(
                start=start_dt.strftime("%Y-%m-%d"),
                end=end_dt.strftime("%Y-%m-%d"),
                station_id=usaf_val,
            )

            if not data_dict:
                continue

            # Extract DataFrame from returned dictionary
            df = list(data_dict.values())[0]

            if df is None or df.empty:
                continue

            # Clean temperature and wind speed values
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

            # Dew Point calculation
            dp = round(
                dewpoint_from_relative_humidity(
                    temp * units.degC, rh * units.percent
                ).magnitude,
                1,
            )

            # Extract spatial coordinates (fallback to metadata if missing in obs)
            lat_coord = float(
                latest.get("latitude", row.get("lat", 0.0))
            )
            lon_coord = float(
                latest.get("longitude", row.get("lon", 0.0))
            )

            st_id_str = f"{str(row['usaf']).zfill(6)}-{str(row['wban']).zfill(5)}"

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
        f"[{datetime.now().strftime('%H:%M:%S')}] Successfully wrote"
        f" {len(features)} live station plots to synoptic_data.json."
    )


if __name__ == "__main__":
    isd = IsdLite(crs=4326)

    while True:
        fetch_synoptic_geojson(isd, limit=80)
        print("Sleeping for 10 minutes...")
        time.sleep(7200)