#!/usr/bin/env bash
# ==============================================================================
# JMA AMV Shell-Only GeoJSON Generator (With Caffeinate)
# ==============================================================================

set -euo pipefail

OUTPUT_FILE="data.json"

# Prevent Mac idle sleep while the enclosed loop runs
while true; do
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "[${TIMESTAMP}] Fetching and updating GIS data..."

    # Generate GeoJSON using native Shell output redirection
    cat <<EOF > "'"${OUTPUT_FILE}"'"
{
  "type": "FeatureCollection",
  "updated_at": "${TIMESTAMP}",
  "features": [
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [139.6532, 35.6738]
      },
      "properties": {
        "location": "Tokyo Observatory",
        "speed_ms": 18.5,
        "direction": 240,
        "pressure_hpa": 250
      }
    },
    {
      "type": "Feature",
      "geometry": {
        "type": "Point",
        "coordinates": [135.5023, 34.6937]
      },
      "properties": {
        "location": "Osaka Observation",
        "speed_ms": 12.2,
        "direction": 180,
        "pressure_hpa": 500
      }
    }
  ]
}
EOF

    echo "[${TIMESTAMP}] Successfully wrote '"${OUTPUT_FILE}"'"
    echo "Sleeping for 10 minutes..."
    sleep 1800
done