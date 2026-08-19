#!/usr/bin/env bash
# ==============================================================================
# JMA AMV Web GIS Data Sync Daemon
# Runs every 10 minutes (600s) to fetch data, generate JSON, and update Web GIS
# ==============================================================================

set -euo pipefail

# Path where your Web GIS map expects the JSON file
OUTPUT_JSON_PATH="./webgis_data/amv_live.json"
TEMP_JSON_PATH="./webgis_data/amv_live.json.tmp"

# Ensure target directory exists
mkdir -p "$(dirname "${OUTPUT_JSON_PATH}")"

echo "Starting AMV JSON Sync Service (Interval: 10 minutes)..."

while true; do
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "[${TIMESTAMP}] Beginning 10-minute fetch & JSON generation cycle..."

    # 1. DOWNLOAD STEP
    # Execute your JMA downloader or curl command here
    # ./download_jma_amv.sh > /dev/null 2>&1 || echo "Warning: Download step failed or no new file."

    # 2. CONVERSION TO JSON STEP
    # Method A: Execute a Python parser script that reads the downloaded BUFR/NetCDF
    # and outputs a GeoJSON file.
    # python3 decode_amv_to_json.py --output "${TEMP_JSON_PATH}"

    # Method B: Generate JSON directly in Bash (Example: Dummy/Mock JSON structure)
    cat <<EOF > "${TEMP_JSON_PATH}"
{
  "type": "FeatureCollection",
  "updated_at": "${TIMESTAMP}",
  "features": [
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [139.65, 35.67] },
      "properties": { "speed_ms": 18.5, "direction": 240, "pressure_hpa": 250 }
    },
    {
      "type": "Feature",
      "geometry": { "type": "Point", "coordinates": [135.00, 30.00] },
      "properties": { "speed_ms": 12.2, "direction": 180, "pressure_hpa": 500 }
    }
  ]
}
EOF

    # 3. ATOMIC FILE SWAP
    # Atomically replace the target file so Web GIS browsers never read half-written JSON
    mv "${TEMP_JSON_PATH}" "${OUTPUT_JSON_PATH}"
    echo "[${TIMESTAMP}] AMV JSON successfully updated at ${OUTPUT_JSON_PATH}"

    # 4. SLEEP 10 MINUTES
    echo "Sleeping for 10 minutes (600 seconds)..."
    sleep 1800
done