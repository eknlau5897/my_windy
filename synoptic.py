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
    """Download NOAA station inventory and filter active stations inside bounding box."""
    print("Fetching master station list from NOAA...")
    try:
        df_stations = pd.read_csv(NOAA_STATION_LIST_URL)

        # 1. Normalize column headers to lowercase
        df_stations.columns = df_stations.columns.str.lower()

        # 2. Drop missing coordinate rows
        df_stations = df_stations.dropna(subset=['lat', 'lon'])

        # 3. Format USAF (6 digits) and WBAN (5 digits) with leading zeroes
        df_stations['usaf'] = df_stations['usaf'].astype(str).str.split('.').str[0].str.zfill(6)
        df_stations['wban'] = df_stations['wban'].astype(str).str.split('.').str[0].str.zfill(5)

        # 4. Filter spatial bounding box
        in_bounds = df_stations[
            (df_stations['lat'] >= LAT_MIN)
            & (df_stations['lat'] <= LAT_MAX)
            & (df_stations['lon'] >= LON_MIN)
            & (df_stations['lon'] <= LON_MAX)
        ].copy()

        # 5. Filter for stations active recently (END date >= 20250101)
        in_bounds['end_num'] = pd.to_numeric(in_bounds['end'], errors='coerce')
        active_in_bounds = in_bounds[in_bounds['end_num'] >= 20250101]

        # 6. Combine USAF-WBAN into the exact string key pyisd requires
        station_ids = (
            active_in_bounds['usaf'] + '-' + active_in_bounds['wban']
        ).tolist()

        print(f"Successfully identified {len(station_ids)} active stations in bounds.")
        return station_ids

    except Exception as e:
        print(f"Error fetching NOAA station list: {e}")
        return []


def update_data(isd_client, station_ids, limit=100):
    """Fetch observation data for target stations and generate synoptic GeoJSON."""
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Querying station observations...")

    now = datetime.utcnow()
    # Fetch recent days (or fallback year if current year processing has delay)
    start_date = (now - timedelta(days=5)).strftime('%Y-%m-%d')
    end_date = now.strftime('%Y-%m-%d')

    features = []
    target_stations = station_ids[:limit]

    for st_id in target_stations:
        try:
            # Query pyisd using full USAF-WBAN format
            data_dict = isd_client.get_data(
                start=start_date, end=end_date, station_id=st_id
            )

            if not data_dict or st_id not in data_dict:
                continue

            df = data_dict[st_id]
            if df.empty:
                continue

            # Drop missing essential observations
            df_valid = df.dropna(subset=['temp', 'windspeed'])
            if df_valid.empty:
                continue

            # Extract latest observation row
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

        except Exception:
            continue

    geojson = {"type": "FeatureCollection", "features": features}

    with open("synoptic_data.json", "w") as f:
        json.dump(geojson, f)

    print(
        f"[{datetime.now().strftime('%H:%M:%S')}] Wrote {len(features)} live station plots to synoptic_data.json."
    )


if __name__ == "__main__":
    isd = IsdLite(crs=4326)
    station_list = get_active_stations_in_bounds()

    if not station_list:
        print("No stations found in target area. Check coordinate boundaries.")
    else:
        while True:
            update_data(isd, station_list, limit=100)
            print("Sleeping 10 minutes...")
            time.sleep(7200)