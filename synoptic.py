import gzip
import io
import json
import re
import time
from datetime import datetime
import pandas as pd
import requests

# Bounding Box: East Asia (0-60°N, 80-145°E)
LAT_MIN, LAT_MAX = 0.0, 60.0
LON_MIN, LON_MAX = 80.0, 145.0

# NOAA Feeds
GTS_URL = "https://tgftp.nws.noaa.gov/data/observations/synoptic/gts/data.txt.gz"
STATION_LIST_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"


def build_east_asia_wmo_catalog():
    """Download NOAA history catalog and map 5-digit WMO station IDs to coordinates."""
    print("Building East Asia WMO Station Catalog...")
    df = pd.read_csv(STATION_LIST_URL)
    df.columns = df.columns.str.lower()

    df = df.dropna(subset=['lat', 'lon', 'usaf'])

    # Filter spatially
    ea_mask = (
        (df['lat'] >= LAT_MIN)
        & (df['lat'] <= LAT_MAX)
        & (df['lon'] >= LON_MIN)
        & (df['lon'] <= LON_MAX)
    )
    ea_stations = df[ea_mask].copy()

    # USAF 6-digit codes map directly to WMO IDs for standard weather stations
    ea_stations['wmo_id'] = (
        ea_stations['usaf'].astype(str).str.split('.').str[0].str.zfill(6)
    )
    # Strip leading zeros if 5-digit WMO format
    ea_stations['wmo_5digit'] = ea_stations['wmo_id'].str.strip().str[-5:]

    # Build lookup dictionary: { '54511': {'lat': 39.93, 'lon': 116.28, 'name': 'BEIJING'} }
    catalog = {}
    for _, row in ea_stations.iterrows():
        wmo = str(row['wmo_5digit'])
        catalog[wmo] = {
            'lat': float(row['lat']),
            'lon': float(row['lon']),
            'name': str(row.get('station name', wmo)),
            'country': str(row.get('ctry', '')),
        }

    print(
        f"Catalog built with {len(catalog)} East Asian WMO station coordinates."
    )
    return catalog


def parse_fm12_synop(tokens):
    """Extract meteorological variables from FM-12 SYNOP tokens using standard WMO regex pattern matching."""
    obs = {}

    for t in tokens:
        # 1. Temperature Group: 1sTTT (10 = positive, 11 = negative)
        if re.match(r"^1[01]\d{3}$", t):
            sign = -1.0 if t[1] == "1" else 1.0
            obs['temp'] = round(sign * int(t[2:]) / 10.0, 1)

        # 2. Dew Point Group: 2sTdTdTd (20 = positive, 21 = negative)
        elif re.match(r"^2[01]\d{3}$", t):
            sign = -1.0 if t[1] == "1" else 1.0
            obs['dewpoint'] = round(sign * int(t[2:]) / 10.0, 1)

        # 3. Sea Level Pressure Group: 4PPPP (in tenths of hPa)
        elif re.match(r"^4\d{4}$", t):
            val = int(t[1:])
            slp = (val / 10.0) + (1000.0 if val < 5000 else 900.0)
            obs['slp'] = round(slp, 1)

        # 4. Wind Group: Nddff (dd = tens of degrees, ff = knots/m/s)
        elif re.match(r"^\d{5}$", t) and t.startswith(
            ("0", "1", "2", "3", "4", "5", "6", "7", "8", "9")
        ):
            # Check if previous token was wind indicator
            dd = int(t[2:4]) * 10
            ff = int(t[4:])
            obs['wind_dir'] = dd
            obs['wind_spd'] = ff

    return obs


def fetch_gts_realtime(catalog):
    """Download live NOAA GTS file, parse East Asia SYNOP observations, and export GeoJSON."""
    print(
        f"[{datetime.utcnow().strftime('%H:%M:%S UTC')}] Fetching GTS real-time"
        " stream from NOAA..."
    )

    try:
        resp = requests.get(GTS_URL, timeout=15)
        if resp.status_code != 200:
            print("Failed to reach NOAA GTS server.")
            return

        with gzip.open(io.BytesIO(resp.content), "rt", errors="ignore") as f:
            raw_text = f.read()

        # Reports start with AAXX header indicator
        reports = raw_text.split("AAXX")
        features = []
        parsed_wmo = set()

        for report in reports[1:]:
            tokens = report.replace("\n", " ").split()
            if len(tokens) < 4:
                continue

            # Second token after AAXX is YYGGii (Date/Time), third is 5-digit WMO station ID
            wmo_id = tokens[1] if len(tokens[1]) == 5 else tokens[2]

            # Fast match against East Asia catalog
            if wmo_id in catalog and wmo_id not in parsed_wmo:
                meta = catalog[wmo_id]
                obs = parse_fm12_synop(tokens)

                if "temp" in obs:
                    parsed_wmo.add(wmo_id)

                    # Compute Fallback Dewpoint if not explicitly reported
                    dp = (
                        obs["dewpoint"]
                        if "dewpoint" in obs
                        else round(obs["temp"] - 2.0, 1)
                    )

                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [meta["lon"], meta["lat"]],
                        },
                        "properties": {
                            "station_id": wmo_id,
                            "name": meta["name"],
                            "country": meta["country"],
                            "time": datetime.utcnow().strftime(
                                "%Y-%m-%d %H:00 UTC"
                            ),
                            "temp": obs["temp"],
                            "dewpoint": dp,
                            "slp": obs.get("slp", 1013.2),
                            "wind_dir": obs.get("wind_dir", 0),
                            "wind_spd": obs.get("wind_spd", 0),
                        },
                    })

        geojson = {"type": "FeatureCollection", "features": features}

        with open("synoptic_data.json", "w") as f:
            json.dump(geojson, f)

        print(
            f"✓ Wrote {len(features)} live East Asia GTS station plots to"
            " synoptic_data.json."
        )

    except Exception as e:
        print(f"Error executing GTS parsing loop: {e}")


if __name__ == "__main__":
    wmo_catalog = build_east_asia_wmo_catalog()

    # Refresh GTS data every 30 minutes
    while True:
        fetch_gts_realtime(wmo_catalog)
        print("Sleeping 30 minutes until next GTS sync...\n")
        time.sleep(1800)