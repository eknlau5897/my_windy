#!/usr/bin/env bash
# ==============================================================================
# Himawari AMV Continuous Auto-Pipeline (Runs every 1800s / 30m)
# Fixes CloudFront 301 Redirects & Validates Binary BUFR Download
# ==============================================================================

INTERVAL=1800  # Execution frequency in seconds (30 minutes)

run_pipeline() {
    set -euo pipefail

    OUTPUT_FILE="data.json"
    TEMP_BUFR="latest_amv.bin"
    PYTHON_SCRIPT=$(mktemp /tmp/parse_bufr.XXXXXX.py)
    BRANCH="main"
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

    YEAR=$(date -u +"%Y")
    MONTH=$(date -u +"%m")
    DAY=$(date -u +"%d")

    # Fixed: Using HTTPS to prevent CloudFront redirects
    GISC_BASE_URL="https://www.wis-jma.go.jp/cms/data/${YEAR}/${MONTH}/${DAY}"
    BUFR_HEADER="IUXA01"

    # Clean temporary files on exit
    trap 'rm -f "${PYTHON_SCRIPT}" "${TEMP_BUFR}"' EXIT

    echo "=================================================="
    echo " Starting JMA AMV Fetch & Deploy Pipeline"
    echo " Time: ${TIMESTAMP}"
    echo "=================================================="

    # --------------------------------------------------------------------------
    # 1. Self-Extract Embedded Python Parser
    # --------------------------------------------------------------------------
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

            except CodesInternalError:
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

    # --------------------------------------------------------------------------
    # 2. Sync Git Repository
    # --------------------------------------------------------------------------
    echo "[1/4] Syncing latest Git branch..."
    git pull origin "${BRANCH}" --rebase || echo "Warning: Git pull failed, continuing..."

    # --------------------------------------------------------------------------
    # 3. Download JMA GISC BUFR Data (Following Redirects via -sL)
    # --------------------------------------------------------------------------
    echo "[2/4] Fetching latest BUFR dataset from JMA GISC..."
    
    # -sL follows CloudFront location redirects
    LATEST_FILE_NAME=$(curl -sL "${GISC_BASE_URL}/" | grep -oE "href=\"[^\"]*${BUFR_HEADER}[^\"]*\"" | cut -d'"' -f2 | tail -n 1 || true)

    if [ -n "${LATEST_FILE_NAME}" ]; then
        echo "      Targeting: ${LATEST_FILE_NAME}"
        curl -sL -o "${TEMP_BUFR}" "${GISC_BASE_URL}/${LATEST_FILE_NAME}"
    else
        echo "      Fallback download target..."
        curl -sL -o "${TEMP_BUFR}" "https://www.wis-jma.go.jp/cms/data/latest_amv.bin" || true
    fi

    # Check if download is HTML instead of Binary
    if grep -q -i "<html" "${TEMP_BUFR}"; then
        echo "Error: Downloaded file is HTML (likely a 301/404 error page). Aborting parse step."
        return 1
    fi

    # --------------------------------------------------------------------------
    # 4. Parse BUFR to GeoJSON
    # --------------------------------------------------------------------------
    echo "[3/4] Parsing BUFR to GeoJSON via embedded Python..."
    if [ -f "${TEMP_BUFR}" ] && [ -s "${TEMP_BUFR}" ]; then
        python3 "${PYTHON_SCRIPT}" "${TEMP_BUFR}" "${OUTPUT_FILE}"
    else
        echo "Error: BUFR download failed or file is zero bytes."
        return 1
    fi

    # --------------------------------------------------------------------------
    # 5. Commit and Push to GitHub
    # --------------------------------------------------------------------------
    echo "[4/4] Deploying to GitHub..."
    git add "${OUTPUT_FILE}"

    if git diff --staged --quiet; then
        echo "      No changes detected in data.json."
    else
        git commit -m "Auto-deploy real JMA AMV data [${TIMESTAMP}]"
        git push origin "${BRANCH}"
        echo "      Pushed updates to remote repository."
    fi

    echo "=================================================="
    echo " Execution Pass Finished Successfully!"
    echo "=================================================="
}

# ------------------------------------------------------------------------------
# Continuous Execution Loop (Runs every 1800 seconds)
# ------------------------------------------------------------------------------
while true; do
    run_pipeline || echo "Pipeline pass encountered an error, waiting for next run..."

    echo ""
    echo "Sleeping for 1800 seconds (30 minutes) until next update..."
    sleep ${INTERVAL}
done