#!/usr/bin/env bash
# ==============================================================================
# Himawari AMV All-In-One Pipeline
# 1. Self-extracts embedded Python BUFR parser
# 2. Syncs local Git repository
# 3. Downloads latest real JMA BUFR file from GISC
# 4. Decodes BUFR to GeoJSON via Python
# 5. Commits and Pushes updated data.json to GitHub
# ==============================================================================

set -euo pipefail

# Configuration
OUTPUT_FILE="data.json"
TEMP_BUFR="latest_amv.bin"
PYTHON_SCRIPT=$(mktemp /tmp/parse_bufr.XXXXXX.py)
BRANCH="main"                             # Change to 'master' if needed
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

YEAR=$(date -u +"%Y")
MONTH=$(date -u +"%m")
DAY=$(date -u +"%d")

GISC_BASE_URL="http://www.wis-jma.go.jp/cms/data/${YEAR}/${MONTH}/${DAY}"
BUFR_HEADER="IUXA01"

# Cleanup temporary python script on exit
trap 'rm -f "${PYTHON_SCRIPT}" "${TEMP_BUFR}"' EXIT

echo "=================================================="
echo " Starting JMA AMV Fetch & Deploy Pipeline"
echo " Time: ${TIMESTAMP}"
echo "=================================================="

# ------------------------------------------------------------------------------
# STEP 1: Self-Extract Embedded Python Parser
# ------------------------------------------------------------------------------
echo "[1/5] Extracting embedded Python BUFR decoder..."

cat << 'EOF' > "${PYTHON_SCRIPT}"
import sys
import os
import json
from datetime import datetime, timezone
from eccodes import *

def parse_bufr_to_geojson(bufr_file_path, output_json_path):
    if not os.path.exists(bufr_file_path) or os.path.getsize(bufr_file_path) == 0:
        print(f"Error: BUFR file '{bufr_file_path}' is missing or empty.")
        sys.exit(1)

    features = []

    with open(bufr_file_path, 'rb') as f:
        while True:
            bufr_id = codes_bufr_new_from_file(f)
            if bufr_id is None:
                break

            try:
                codes_set(bufr_id, 'unpack', 1)

                lats = codes_get_array(bufr_id, 'latitude')
                lons = codes_get_array(bufr_id, 'longitude')
                pressures = codes_get_array(bufr_id, 'pressure')
                speeds = codes_get_array(bufr_id, 'windSpeed')
                directions = codes_get_array(bufr_id, 'windDirection')

                for lat, lon, p, spd, direct in zip(lats, lons, pressures, speeds, directions):
                    p_hpa = int(p / 100) if p > 2000 else int(p)

                    # Filter out missing/invalid observation data
                    if spd < 0 or spd > 150 or p_hpa < 50 or p_hpa > 1050:
                        continue

                    features.append({
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [round(float(lon), 4), round(float(lat), 4)]
                        },
                        "properties": {
                            "speed_ms": round(float(spd), 1),
                            "direction": int(direct),
                            "pressure_hpa": p_hpa
                        }
                    })

            except CodesInternalError as err:
                pass
            finally:
                codes_release(bufr_id)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    geojson_data = {
        "type": "FeatureCollection",
        "updated_at": timestamp,
        "features": features
    }

    with open(output_json_path, 'w', encoding='utf-8') as out_f:
        json.dump(geojson_data, out_f)

    print(f" Successfully processed {len(features)} AMV vectors into '{output_json_path}'.")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
    parse_bufr_to_geojson(sys.argv[1], sys.argv[2])
EOF

# ------------------------------------------------------------------------------
# STEP 2: Git Sync
# ------------------------------------------------------------------------------
echo "[2/5] Syncing latest Git branch..."
git pull origin "${BRANCH}" --rebase || echo "Warning: Git pull failed, continuing locally..."

# ------------------------------------------------------------------------------
# STEP 3: Download Real Data from JMA GISC
# ------------------------------------------------------------------------------
echo "[3/5] Fetching latest BUFR dataset from JMA GISC..."

LATEST_FILE_NAME=$(curl -s "${GISC_BASE_URL}/" | grep -oE "href=\"[^\"]*${BUFR_HEADER}[^\"]*\"" | cut -d'"' -f2 | tail -n 1 || true)

if [ -n "${LATEST_FILE_NAME}" ]; then
    echo "      Targeting file: ${LATEST_FILE_NAME}"
    curl -s -o "${TEMP_BUFR}" "${GISC_BASE_URL}/${LATEST_FILE_NAME}"
else
    echo "      Directory listing unavailable. Downloading fallback endpoint..."
    curl -s -o "${TEMP_BUFR}" "http://www.wis-jma.go.jp/cms/data/latest_amv.bin" || true
fi

# ------------------------------------------------------------------------------
# STEP 4: Parse BUFR to GeoJSON using Embedded Python
# ------------------------------------------------------------------------------
echo "[4/5] Running embedded Python parser..."

if [ -f "${TEMP_BUFR}" ] && [ -s "${TEMP_BUFR}" ]; then
    python3 "${PYTHON_SCRIPT}" "${TEMP_BUFR}" "${OUTPUT_FILE}"
else
    echo "Error: BUFR download failed or file is empty."
    exit 1
fi

# ------------------------------------------------------------------------------
# STEP 5: Git Stage, Commit, and Deploy
# ------------------------------------------------------------------------------
echo "[5/5] Deploying updates to GitHub Pages..."

git add "${OUTPUT_FILE}"

if git diff --staged --quiet; then
    echo "      No change in dataset. Skipping commit."
else
    git commit -m "Auto-deploy real JMA AMV data [${TIMESTAMP}]"
    git push origin "${BRANCH}"
    echo "      Successfully pushed to GitHub."
fi

echo "=================================================="
echo " Pipeline Complete!"
echo "=================================================="