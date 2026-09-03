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

# Fixed URLs: Updated NOAA TGFTP structure + Working IEM Real-Time Surface Service
GTS_URLS = [
    "https://weather.noaa.gov/pub/data/observations/synoptic/gts/data.txt.gz",
    "https://tgftp.nws.noaa.gov/data/observations/synoptic/gts/data.txt.gz",
]

# IEM global real-time surface observations GeoJSON endpoint
IEM_SURFACE_URL = "https://mesonet.agron.iastate.edu/geojson/surface.geojson"
STATION_LIST_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,"
        " like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def build_east_asia_wmo_catalog():
    """Download NOAA history catalog and map 5-digit WMO station IDs to coordinates."""
    print("Building East Asia WMO Station Catalog from NOAA NCEI...")
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

        ea_stations["wmo_id"] = (
            ea_stations["usaf"].astype(str).str.split(".").str[0].str.zfill(6)
        )
        ea_stations["wmo_5digit"] = ea_stations["wmo_id"].str.strip().str[-5:]

        catalog = {}
        for _, row in ea_stations.iterrows():
            wmo = str(row["wmo_5digit"])
            catalog[wmo] = {
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "name": str(row.get("station name", wmo)),
                "country": str(row.get("ctry", "")),
            }

        print(f"✓ Catalog ready with {len(catalog)} East Asian WMO stations.")
        return catalog
    except Exception as e:
        print(f"⚠️ Catalog build warning: {e}")
        return {}


def parse_fm12_synop(tokens):
    """Decode standard WMO FM-12 SYNOP message tokens."""
    obs = {}
    for t in tokens:
        if re.match(r"^1[01]\d{3}$", t):
            sign = -1.0 if t[1] == "1" else 1.0
            obs["temp"] = round(sign * int(t[2:]) / 10.0, 1)
        elif re.match(r"^2[01]\d{3}$", t):
            sign = -1.0 if t[1] == "1" else 1.0
            obs["dewpoint"] = round(sign * int(t[2:]) / 10.0, 1)
        elif re.match(r"^4\d{4}$", t):
            val = int(t[1:])
            slp = (val / 10.0) + (1000.0 if val < 5000 else 900.0)
            obs["slp"] = round(slp, 1)
        elif re.match(r"^\d{5}$", t) and t[0] in "0123456789":
            obs["wind_dir"] = int(t[2:4]) * 10
            obs["wind_spd"] = int(t[4:])
    return obs


def fetch_noaa_gts_stream(catalog):
    """Try pulling NOAA GTS file stream."""
    raw_text = None
    for url in GTS_URLS:
        try:
            print(f"Connecting to NOAA GTS endpoint: {url}...")
            resp = requests.get(url, headers=HEADERS, timeout=12)
            if resp.status_code == 200:
                print(f"✓ Connected to {url}")
                with gzip.open(
                    io.BytesIO(resp.content), "rt", errors="ignore"
                ) as f:
                    raw_text = f.read()
                break
            else:
                print(f"⚠️ Endpoint returned HTTP {resp.status_code}")
        except Exception as err:
            print(f"❌ Failed connecting to {url}: {err}")

    if not raw_text:
        return False

    reports = raw_text.split("AAXX")
    features = []
    parsed_wmo = set()

    for report in reports[1:]:
        tokens = report.replace("\n", " ").split()
        if len(tokens) < 4:
            continue

        wmo_id = tokens[1] if len(tokens[1]) == 5 else tokens[2]

        if wmo_id in catalog and wmo_id not in parsed_wmo:
            meta = catalog[wmo_id]
            obs = parse_fm12_synop(tokens)

            if "temp" in obs:
                parsed_wmo.add(wmo_id)
                dp = obs.get("dewpoint", round(obs["temp"] - 2.0, 1))

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

    if features:
        geojson = {"type": "FeatureCollection", "features": features}
        with open("synoptic_data.json", "w") as f:
            json.dump(geojson, f)
        print(f"✓ Success: Wrote {len(features)} NOAA GTS station records.")
        return True

    return False


def fetch_iem_fallback():
    """WORKING FALLBACK: Fetches real-time global surface observations from IEM."""
    print("⚠️ Switching to IEM Global Real-Time Surface Service...")
    try:
        resp = requests.get(IEM_SURFACE_URL, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            print(f"❌ IEM returned status {resp.status_code}")
            return

        data = resp.json()
        features = []

        for feat in data.get("features", []):
            geometry = feat.get("geometry")
            if not geometry or "coordinates" not in geometry:
                continue

            coords = geometry["coordinates"]
            lon, lat = coords[0], coords[1]

            # Bounding box filter for East Asia
            if LON_MIN <= lon <= LON_MAX and LAT_MIN <= lat <= LAT_MAX:
                props = feat.get("properties", {})
                tmpc = props.get("tmpc")

                # Only include valid temperature readings
                if tmpc is not None:
                    features.append({
                        "type": "Feature",
                        "geometry": geometry,
                        "properties": {
                            "station_id": props.get("station", "UNK"),
                            "name": props.get("sname", props.get("station", "Station")),
                            "country": "",
                            "time": datetime.utcnow().strftime(
                                "%Y-%m-%d %H:00 UTC"
                            ),
                            "temp": round(float(tmpc), 1),
                            "dewpoint": round(
                                float(props.get("dwpc", tmpc - 2.0)), 1
                            ),
                            "slp": round(
                                float(props.get("mslp", 1013.2) or 1013.2), 1
                            ),
                            "wind_dir": int(props.get("drct", 0) or 0),
                            "wind_spd": int(props.get("sknt", 0) or 0),
                        },
                    })

        geojson = {"type": "FeatureCollection", "features": features}
        with open("synoptic_data.json", "w") as f:
            json.dump(geojson, f)

        print(
            f"✓ Fallback Success: Wrote {len(features)} East Asia surface"
            " stations via IEM."
        )

    except Exception as e:
        print(f"❌ Fallback error: {e}")


def main():
    catalog = build_east_asia_wmo_catalog()

    while True:
        print(
            f"\n--- Sync Cycle: {datetime.utcnow().strftime('%H:%M:%S UTC')} ---"
        )
        success = fetch_noaa_gts_stream(catalog)

        if not success:
            fetch_iem_fallback()

        print("Sleeping 15 minutes until next update cycle...")
        time.sleep(900)


if __name__ == "__main__":
    main()