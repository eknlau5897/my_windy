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

NOAA_STATION_LIST_URL = (
    "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"
)


def get_active_stations_in_bounds():
    """Download NOAA station inventory, normalize column names, and filter spatially."""
    print("Fetching master station list from NOAA...")
    try:
        df_stations = pd.read_csv(NOAA_STATION_LIST_URL)

        # Normalize column names to lowercase to avoid KeyError: 'LAT'
        df_stations.columns = df_stations.columns.str.lower()

        # Clean coordinates and IDs
        df_stations = df_stations.dropna(subset=['lat', 'lon'])
        df_stations['usaf'] = df_stations['usaf'].astype(str).str.zfill(6)
        df_stations['wban'] = df_stations['wban'].astype(str).str.zfill(5)

        # Filter spatial bounding box (0-60N, 80-145E)
        in_bounds = df_stations[
            (df_stations['lat'] >= LAT_MIN)
            & (df_stations['lat'] <= LAT_MAX)
            & (df_stations['lon'] >= LON_MIN)
            & (df_stations['lon'] <= LON_MAX)
        ].copy()

        # Filter for stations active in the current year
        current_year = str(datetime.utcnow().year)
        active_in_bounds = in_bounds[
            in_bounds['end'].astype(str).str.startswith(current_year)
        ]

        # Use USAF string codes for pyisd station lookup
        station_ids = active_in_bounds['usaf'].tolist()
        print(f"Found {len(station_ids)} active candidate stations in bounds.")
        return station_ids

    except Exception as e:
        print(f"Error fetching NOAA station list: {e}")
        return []


def update_data(isd_client, station_ids, limit=100):
    """Fetch observation data for target stations and write multi-point GeoJSON."""
    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Fetching observations..."
    )

    # Fetch only recent data (last 3 days) to optimize speed and avoid timeouts
    now = datetime.utcnow()
    start_date = (now - timedelta(days=3)).strftime('%Y-%m-%d')
    end_date = now.strftime('%Y-%m-%d')

    features = []
    target_stations = station_ids[:limit]

    for st_id in target_stations:
        try:
            # Query pyisd using standard station ID
            data_dict = isd_client.get_data(
                start=start_date, end=end_date, station_id=st_id
            )

            if not data_dict or st_id not in data_dict:
                continue

            df = data_dict[st_id]
            if df.empty:
                continue

            # Drop missing essential values
            df_valid = df.dropna(subset=['temp', 'windspeed'])
            if df_valid.empty:
                continue

            # Extract the most recent valid observation
            latest = df_valid.iloc[-1]

            temp = float(latest['temp'])
            rh = float(latest['rh'])

            # Calculate Dew Point using MetPy
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
            # Skip unreachable or inactive stations gracefully
            continue

    geojson = {"type": "FeatureCollection", "features": features}

    with open("synoptic_data.json", "w") as f:
        json.dump(geojson, f)

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Wrote {len(features)}"
        " stations to synoptic_data.json."
    )


if __name__ == "__main__":
    # Initialize pyisd client with WGS84 CRS
    isd = IsdLite(crs=4326)

    # Fetch initial target list
    station_list = get_active_stations_in_bounds()

    if not station_list:
        print("No stations found. Exiting.")
    else:
        # Loop endlessly every 10 minutes to auto-refresh data
        while True:
            update_data(isd, station_list, limit=120)
            print("Waiting 2 hours for next update loop...")
            time.sleep(7200)