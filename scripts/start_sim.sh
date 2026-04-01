#!/usr/bin/env bash
# ============================================================
# AerialClaw — Start PX4 + Gazebo Simulation
# ============================================================
#
# Usage:
#   ./scripts/start_sim.sh                  # default world
#   ./scripts/start_sim.sh urban_rescue     # urban rescue world
#   ./scripts/start_sim.sh default x500     # specify model
#
# This starts: DDS Agent + Gazebo + PX4 SITL
# Then run: python server.py (in another terminal)
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Defaults
WORLD="${1:-default}"
MODEL="${2:-x500}"

# Find PX4
if [ -d "${PROJECT_DIR}/PX4-Autopilot" ]; then
    PX4_DIR="${PROJECT_DIR}/PX4-Autopilot"
elif [ -n "$PX4_DIR" ]; then
    true  # use env var
else
    echo "ERROR: PX4-Autopilot not found. Run ./scripts/setup_px4.sh first."
    exit 1
fi

PX4_BIN="${PX4_DIR}/build/px4_sitl_default/bin/px4"
PX4_BUILD="${PX4_DIR}/build/px4_sitl_default"

if [ ! -f "$PX4_BIN" ]; then
    echo "ERROR: PX4 binary not found at $PX4_BIN"
    echo "Run ./scripts/setup_px4.sh first."
    exit 1
fi

# Environment
export PX4_GZ_MODELS="${PX4_DIR}/Tools/simulation/gz/models"
export PX4_GZ_WORLDS="${PX4_DIR}/Tools/simulation/gz/worlds"
export GZ_SIM_RESOURCE_PATH="${HOME}/.simulation-gazebo/models:${PX4_GZ_MODELS}:${PX4_GZ_WORLDS}"
export PX4_SYS_AUTOSTART=4001
export PX4_SIMULATOR=gz
export PX4_GZ_WORLD="$WORLD"
export PX4_SIM_MODEL="$MODEL"
export PX4_GZ_STANDALONE=1

WORLD_SDF="${PX4_GZ_WORLDS}/${WORLD}.sdf"
if [ ! -f "$WORLD_SDF" ]; then
    echo "WARNING: World file not found: $WORLD_SDF"
    echo "Available worlds:"
    ls "${PX4_GZ_WORLDS}"/*.sdf 2>/dev/null | xargs -I{} basename {} .sdf
    echo "Falling back to 'default'"
    WORLD="default"
    WORLD_SDF="${PX4_GZ_WORLDS}/default.sdf"
    export PX4_GZ_WORLD="default"
fi

cleanup() {
    echo ""
    echo "Shutting down simulation..."
    pkill -f "bin/px4" 2>/dev/null || true
    pkill -f "gz sim" 2>/dev/null || true
    pkill -f MicroXRCEAgent 2>/dev/null || true
    sleep 1
    echo "Done."
}
trap cleanup EXIT INT TERM

echo "============================================================"
echo " AerialClaw Simulation Launcher"
echo " World: $WORLD | Model: $MODEL"
echo "============================================================"
echo ""

# 1. DDS Agent
echo "[1/3] Starting Micro XRCE-DDS Agent..."
MicroXRCEAgent udp4 -p 8888 > /tmp/aerialclaw_dds.log 2>&1 &
DDS_PID=$!
sleep 1
if kill -0 $DDS_PID 2>/dev/null; then
    echo "  DDS Agent running (PID: $DDS_PID)"
else
    echo "ERROR: DDS Agent failed to start. Is MicroXRCEAgent installed?"
    exit 1
fi

# 2. Gazebo
echo "[2/3] Starting Gazebo ($WORLD)..."
gz sim --verbose=1 -r -s "$WORLD_SDF" > /tmp/aerialclaw_gz.log 2>&1 &
GZ_PID=$!
echo "  Waiting for Gazebo to load (10s)..."
sleep 10
if kill -0 $GZ_PID 2>/dev/null; then
    echo "  Gazebo running (PID: $GZ_PID)"
else
    echo "ERROR: Gazebo failed to start. Check /tmp/aerialclaw_gz.log"
    exit 1
fi

# 3. PX4 SITL
echo "[3/3] Starting PX4 SITL..."
cd "$PX4_BUILD"
"$PX4_BIN" "$PX4_BUILD" -s "${PX4_BUILD}/etc/init.d-posix/rcS" > /tmp/aerialclaw_px4.log 2>&1 < /dev/null &
PX4_PID=$!
sleep 5
if kill -0 $PX4_PID 2>/dev/null; then
    echo "  PX4 SITL running (PID: $PX4_PID)"
else
    echo "ERROR: PX4 SITL failed to start. Check /tmp/aerialclaw_px4.log"
    exit 1
fi

echo ""
echo "============================================================"
echo " Simulation is running!"
echo ""
echo " MAVLink:  udp://:14540 (MAVSDK/Offboard)"
echo "           udp://:14550 (QGroundControl)"
echo ""
echo " Next: In another terminal, run:"
echo "   cd $(dirname "$SCRIPT_DIR")"
echo "   source venv/bin/activate"
echo "   python server.py"
echo "   # Then open http://localhost:5001"
echo ""
echo " Gazebo GUI (optional):"
echo "   gz sim -g"
echo ""
echo " Logs:"
echo "   DDS:     /tmp/aerialclaw_dds.log"
echo "   Gazebo:  /tmp/aerialclaw_gz.log"
echo "   PX4:     /tmp/aerialclaw_px4.log"
echo ""
echo " Press Ctrl+C to stop all."
echo "============================================================"

# Wait for any child to exit
wait
