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


def get_active_stations_in_bounds(isd_client):
    """Retrieves metadata using pyisd's built-in metadata table."""
    print("Filtering station metadata...")

    # Access pyisd's pre-loaded metadata DataFrame
    df_meta = isd_client.raw_metadata.copy()

    # Normalize coordinate column names (pyisd uses lowercase 'lat' and 'lon')
    lat_col = 'lat' if 'lat' in df_meta.columns else 'LAT'
    lon_col = 'lon' if 'lon' in df_meta.columns else 'LON'

    # 1. Filter spatially
    in_bounds = df_meta[
        (df_meta[lat_col] >= LAT_MIN)
        & (df_meta[lat_col] <= LAT_MAX)
        & (df_meta[lon_col] >= LON_MIN)
        & (df_meta[lon_col] <= LON_MAX)
    ]

    # 2. Extract USAF identifiers as list
    usaf_ids = in_bounds['usaf'].astype(str).str.zfill(6).tolist()
    print(f"Found {len(usaf_ids)} candidate stations within spatial bounds.")
    return usaf_ids


def update_data(isd_client, station_ids, limit=100):
    """Fetch recent observations for target stations and write GeoJSON."""
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Querying station"
        " observations..."
    )

    # Query short timeframe (last 3 days) to speed up download drastically
    now = datetime.utcnow()
    start_date = (now - timedelta(days=3)).strftime('%Y-%m-%d')
    end_date = now.strftime('%Y-%m-%d')

    features = []
    target_stations = station_ids[:limit]

    for st_id in target_stations:
        try:
            # Query pyisd using standard USAF code
            data_dict = isd_client.get_data(
                start=start_date, end=end_date, station_id=st_id
            )

            if not data_dict or st_id not in data_dict:
                continue

            df = data_dict[st_id]
            if df.empty:
                continue

            # Drop missing values
            df_valid = df.dropna(subset=['temp', 'windspeed'])
            if df_valid.empty:
                continue

            # Get latest observation row
            latest = df_valid.iloc[-1]

            temp = float(latest['temp'])
            rh = float(latest['rh'])

            # Compute Dew Point using MetPy
            dp = round(
                dewpoint_from_relative_humidity(
                    temp * units.degC, rh * units.percent
                ).magnitude,
                1,
            )

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [
                        float(latest['longitude']),
                        float(latest['latitude']),
                    ],
                },
                "properties": {
                    "station_id": st_id,
                    "time": latest.name.strftime('%Y-%m-%d %H:%M UTC'),
                    "temp": round(temp, 1),
                    "dewpoint": dp,
                    "slp": round(float(latest.get('slp', 1013.2)), 1),
                    "wind_dir": int(latest['winddir']),
                    "wind_spd": int(latest['windspeed']),
                },
            })

        except Exception as e:
            # Skip unreachable or inactive stations silently
            continue

    geojson = {"type": "FeatureCollection", "features": features}

    with open("synoptic_data.json", "w") as f:
        json.dump(geojson, f)

    print(
        f"Successfully generated synoptic_data.json with {len(features)}"
        " active station plots."
    )


if __name__ == "__main__":
    isd = IsdLite(crs=4326)
    station_list = get_active_stations_in_bounds(isd)

    while True:
        update_data(isd, station_list, limit=100)
        print("Sleeping for 2 hours...")
        time.sleep(7200)