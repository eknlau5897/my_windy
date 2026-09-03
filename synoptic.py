from datetime import datetime
import json
import time
from metpy.calc import dewpoint_from_relative_humidity
from metpy.units import units
import pandas as pd
from pyisd import IsdLite

NOAA_STATION_LIST_URL = (
    "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
)

# Spatial Bounds
LAT_MIN, LAT_MAX = 0.0, 60.0
LON_MIN, LON_MAX = 80.0, 145.0


def get_active_stations_in_bounds():
    """Download NOAA station inventory and filter stations inside bounding box."""
    print("Fetching master station list from NOAA...")
    df_stations = pd.read_csv(NOAA_STATION_LIST_URL)

    # Clean coordinate and ID columns
    df_stations = df_stations.dropna(subset=['LAT', 'LON'])
    df_stations['USAF'] = df_stations['USAF'].astype(str).str.zfill(6)
    df_stations['WBAN'] = df_stations['WBAN'].astype(str).str.zfill(5)

    # Filter spatial bounding box
    in_bounds = df_stations[
        (df_stations['LAT'] >= LAT_MIN)
        & (df_stations['LAT'] <= LAT_MAX)
        & (df_stations['LON'] >= LON_MIN)
        & (df_stations['LON'] <= LON_MAX)
    ]

    # Filter for stations active in the current year
    current_year = str(datetime.utcnow().year)
    active_in_bounds = in_bounds[
        in_bounds['END'].astype(str).str.startswith(current_year)
    ]

    # Combine USAF and WBAN identifiers into ISD format: 'USAF-WBAN'
    station_ids = (
        active_in_bounds['USAF'] + '-' + active_in_bounds['WBAN']
    ).tolist()
    print(f"Found {len(station_ids)} active stations in bounding box.")

    return station_ids, active_in_bounds


def update_data(station_ids, limit=100):
    """Fetch observation data for target stations and generate multi-point GeoJSON.

    'limit' controls maximum stations fetched per iteration to stay within rate
    limits.
    """
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Querying station"
        " observations..."
    )
    isd = IsdLite()
    now = datetime.utcnow()
    features = []

    # Process batch of stations
    target_stations = station_ids[:limit]

    for st_id in target_stations:
        try:
            data_dict = isd.get_data(
                start=now.strftime('%Y-01-01'),
                end=now.strftime('%Y-%m-%d'),
                station_id=st_id,
            )
            df = data_dict[st_id]

            # Get latest valid row
            latest = df.dropna(subset=['temp', 'windspeed']).iloc[-1]

            temp = float(latest['temp'])
            rh = float(latest['rh'])
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
        except Exception:
            # Skip stations without recent observations or offline status
            continue

    geojson = {"type": "FeatureCollection", "features": features}

    with open("synoptic_data.json", "w") as f:
        json.dump(geojson, f)

    print(
        f"Successfully written {len(features)} live station plots to"
        " synoptic_data.json."
    )


if __name__ == "__main__":
    # Get all matching active station IDs
    station_list, metadata = get_active_stations_in_bounds()

    # Continuously refresh observations every 10 minutes
    while True:
        update_data(station_list, limit=150)  # Adjust limit as needed
        time.sleep(7200)