#!/usr/bin/env bash
# ==============================================================================
# All-In-One NOAA AMV Fetcher & GitHub Deployer
# Fetches latest observations from NOAA ERDDAP and pushes to GitHub
# ==============================================================================

INTERVAL=1800  # Run every 30 minutes
BRANCH="main"  # Target Git branch

run_pipeline() {
    set -euo pipefail

    OUTPUT_FILE="data.json"
    PYTHON_SCRIPT=$(mktemp /tmp/fetch_amv.XXXXXX.py)
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    # Cleanup temporary script on exit
    trap 'rm -f "${PYTHON_SCRIPT}"' EXIT

    echo "=================================================="
    echo " Starting NOAA Sync Pipeline"
    echo " Time: ${TIMESTAMP}"
    echo "=================================================="

    # --------------------------------------------------------------------------
    # 1. Embed Python Fetcher
    # --------------------------------------------------------------------------
    cat << 'EOF' > "${PYTHON_SCRIPT}"
import sys
import os
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone

OUTPUT_FILE = "data.json"

def fetch_noaa_amv():
    print("Fetching latest satellite wind vectors from NOAA...")

    # Reliable ERDDAP query URL retrieving the last 3000 rows
    url = 'https://coastwatch.pfeg.noaa.gov/erddap/tabledap/noaa_nesdis_amv.json?latitude,longitude,pressure,wind_speed,wind_direction&last3000'

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }

    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=45) as response:
            if response.status != 200:
                print(f"Error: NOAA API returned HTTP {response.status}")
                return False
            
            raw_data = response.read().decode('utf-8')
            data = json.loads(raw_data)

        rows = data.get('table', {}).get('rows', [])
        print(f"Received {len(rows)} raw data points from NOAA.")

        features = []
        for row in rows:
            lat, lon, pressure, speed, direction = row[0], row[1], row[2], row[3], row[4]

            # Filter missing or corrupt data points
            if None in (lat, lon, pressure, speed) or speed < 0 or speed > 150:
                continue

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [round(float(lon), 4), round(float(lat), 4)]
                },
                "properties": {
                    "speed_ms": round(float(speed), 1),
                    "direction": int(direction) if direction is not None else 0,
                    "pressure_hpa": int(pressure)
                }
            })

        geojson_data = {
            "type": "FeatureCollection",
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "features": features
        }

        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(geojson_data, f, indent=2)

        print(f"Successfully saved {len(features)} vector points into '{OUTPUT_FILE}'.")
        return True

    except urllib.error.HTTPError as e:
        print(f"HTTP Error querying NOAA: {e.code} {e.reason}")
        return False
    except Exception as e:
        print(f"Error fetching NOAA data: {e}")
        return False

if __name__ == "__main__":
    success = fetch_noaa_amv()
    if not success:
        sys.exit(1)
EOF

    # --------------------------------------------------------------------------
    # 2. Sync Local Repository with Remote
    # --------------------------------------------------------------------------
    echo "[1/3] Syncing local branch with GitHub..."
    git pull origin "${BRANCH}" --rebase || echo "Warning: Git pull failed, continuing..."

    # --------------------------------------------------------------------------
    # 3. Execute Embedded Fetcher
    # --------------------------------------------------------------------------
    echo "[2/3] Executing embedded Python fetcher..."
    python3 "${PYTHON_SCRIPT}"

    # --------------------------------------------------------------------------
    # 4. Commit & Push Changes
    # --------------------------------------------------------------------------
    echo "[3/3] Deploying data.json to GitHub..."
    if [ -f "${OUTPUT_FILE}" ]; then
        git add "${OUTPUT_FILE}"

        if git diff --staged --quiet; then
            echo "      No data changes detected. Skipping commit."
        else
            git commit -m "Auto-update NOAA satellite wind vectors [${TIMESTAMP}]"
            git push origin "${BRANCH}"
            echo "      Pushed fresh data.json to GitHub!"
        fi
    else
        echo "Error: ${OUTPUT_FILE} was not generated."
        return 1
    fi

    echo "=================================================="
    echo " Pass Completed Successfully!"
    echo "=================================================="
}

# ------------------------------------------------------------------------------
# Infinite Loop
# ------------------------------------------------------------------------------
while true; do
    run_pipeline || echo "Pipeline pass encountered an error. Waiting for next cycle..."

    echo ""
    echo "Sleeping for 1800 seconds (30 minutes) until next update..."
    sleep ${INTERVAL}
done