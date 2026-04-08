#!/usr/bin/env bash
# example.sh — Demonstrates a stateful workload migration using RSTS.
#
# Scenario:
#   1. Start RSTS on "location A" (/tmp/rsts/location-a)
#   2. Write some state to it
#   3. Stop the container (simulating decommission)
#   4. Start RSTS on "location B" (/tmp/rsts/location-b) with the SAME data volume
#   5. Verify state survived and instance changed (proving relocation, not restart)

set -euo pipefail

IMAGE="ghcr.io/fdcastel/rsts"
PORT=8080
DATA_SRC="/tmp/rsts/location-a"
DATA_DST="/tmp/rsts/location-b"
STATE_VALUE="migrated-$(date +%s)"

echo "=== RSTS Migration Demo ==="
echo ""

# --- Prepare storage locations ---
echo "[1/7] Preparing storage locations..."
mkdir -p "$DATA_SRC" "$DATA_DST"

# --- Start on Location A ---
echo "[2/7] Starting RSTS on Location A ($DATA_SRC)..."
docker run -d --rm \
  --name rsts-location-a \
  -p ${PORT}:80 \
  -v "${DATA_SRC}:/data" \
  -e RSTS_SERVER_NAME=location-a \
  "$IMAGE"

echo "      Waiting for service to be ready..."
until curl -sf "http://localhost:${PORT}/health" > /dev/null; do sleep 1; done

# --- Inspect initial state ---
echo "[3/7] Initial state on Location A:"
curl -s "http://localhost:${PORT}/" | python3 -m json.tool
echo ""

INSTANCE_A=$(curl -s "http://localhost:${PORT}/" | python3 -c "import sys,json; print(json.load(sys.stdin)['instance_id'])")

# --- Write meaningful state ---
echo "[4/7] Writing state '$STATE_VALUE' to Location A..."
curl -s -X POST "http://localhost:${PORT}/state/${STATE_VALUE}" | python3 -m json.tool
echo ""

# --- Copy data volume to destination ---
echo "[5/7] Migrating data volume: $DATA_SRC -> $DATA_DST..."
cp -a "${DATA_SRC}/." "${DATA_DST}/"
echo "      Done. Contents: $(ls $DATA_DST)"

# --- Stop Location A ---
echo "[6/7] Stopping Location A..."
docker stop rsts-location-a

# --- Start on Location B with migrated data ---
echo "      Starting RSTS on Location B ($DATA_DST)..."
docker run -d --rm \
  --name rsts-location-b \
  -p ${PORT}:80 \
  -v "${DATA_DST}:/data" \
  -e RSTS_SERVER_NAME=location-b \
  "$IMAGE"

echo "      Waiting for service to be ready..."
until curl -sf "http://localhost:${PORT}/health" > /dev/null; do sleep 1; done

# --- Verify migration ---
echo "[7/7] State on Location B after migration:"
curl -s "http://localhost:${PORT}/" | python3 -m json.tool
echo ""

INSTANCE_B=$(curl -s "http://localhost:${PORT}/" | python3 -c "import sys,json; print(json.load(sys.stdin)['instance_id'])")
STATE_B=$(curl -s "http://localhost:${PORT}/" | python3 -c "import sys,json; print(json.load(sys.stdin)['data'])")

echo "=== Migration Verification ==="
echo "  State value    : $STATE_B  (expected: $STATE_VALUE)"
echo "  Instance A ID  : $INSTANCE_A"
echo "  Instance B ID  : $INSTANCE_B"
echo ""

if [ "$STATE_B" = "$STATE_VALUE" ]; then
  echo "  [PASS] State survived the migration."
else
  echo "  [FAIL] State was lost!"
fi

if [ "$INSTANCE_A" != "$INSTANCE_B" ]; then
  echo "  [PASS] Instance ID changed — this is a relocation, not a mere restart."
else
  echo "  [FAIL] Instance ID is the same — something is wrong."
fi

echo ""
echo "=== Cleanup ==="
docker stop rsts-location-b
rm -rf /tmp/rsts
echo "Done."
