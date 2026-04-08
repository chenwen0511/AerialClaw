#!/usr/bin/env bash
# ============================================================
# AerialClaw — 使用系统 Python 启动 Web 控制台（PX4 + Gazebo 场景）
# ============================================================
#
# 为何必须用 /usr/bin/python3？
#   apt 安装的 python3-gz-transport13 / python3-gz-msgs10 仅针对 Ubuntu 自带
#   Python（如 3.10）编译。Miniconda 的 Python 3.11+ / 3.13 无法加载其 C 扩展，
#   会导致「传感器桥接未启动」、网页相机一直 NO SIGNAL。
#
# 依赖:
#   sudo apt install python3-pip python3-gz-transport13 python3-gz-msgs10
#   /usr/bin/python3 -m pip install --user -r requirements.txt
#
# 用法（与 start_sim.sh 使用同一套环境变量）:
#   export GZ_PARTITION=aerialclaw
#   export PX4_GZ_WORLD=default
#   export PX4_SIM_MODEL=x500_lidar_2d_cam
#   ./scripts/run_server_px4.sh
#
# 可选: 指定解释器
#   SYS_PYTHON=/usr/bin/python3 ./scripts/run_server_px4.sh
# ============================================================

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

SYS_PY="${SYS_PYTHON:-/usr/bin/python3}"
if [ ! -x "$SYS_PY" ]; then
  echo "ERROR: 未找到可执行 Python: $SYS_PY"
  exit 1
fi

if ! "$SYS_PY" -m pip --version >/dev/null 2>&1; then
  echo "ERROR: 系统 Python 没有 pip（No module named pip）。请先执行:"
  echo "  sudo apt update && sudo apt install -y python3-pip"
  echo "然后再:"
  echo "  $SYS_PY -m pip install --user -r $PROJECT_DIR/requirements.txt"
  exit 1
fi

if ! "$SYS_PY" -c "import flask" 2>/dev/null; then
  echo "ERROR: 系统 Python 未安装 Flask。请先执行:"
  echo "  $SYS_PY -m pip install --user -r $PROJECT_DIR/requirements.txt"
  exit 1
fi

if ! "$SYS_PY" -c "import cv2" 2>/dev/null; then
  echo "ERROR: 未安装 OpenCV（/api/sensor/camera 等需要 cv2）。请先执行:"
  echo "  $SYS_PY -m pip install --user opencv-python-headless"
  echo "或安装完整依赖:"
  echo "  $SYS_PY -m pip install --user -r $PROJECT_DIR/requirements.txt"
  exit 1
fi

if ! "$SYS_PY" -c "import gz.transport13" 2>/dev/null; then
  echo "WARN: 无法 import gz.transport13，传感器桥接可能失败。请安装:"
  echo "  sudo apt install python3-gz-transport13 python3-gz-msgs10"
fi

export GZ_PARTITION="${GZ_PARTITION:-aerialclaw}"
export PX4_GZ_WORLD="${PX4_GZ_WORLD:-default}"
export PX4_SIM_MODEL="${PX4_SIM_MODEL:-x500_lidar_2d_cam}"
# pip 的 protobuf 与 apt 的 gz.msgs10 并存时可能触发 Descriptor 错误；纯 Python 解析可避免
export PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION="${PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION:-python}"

echo "[run_server_px4] Python: $SYS_PY ($("$SYS_PY" --version 2>&1))"
echo "[run_server_px4] GZ_PARTITION=$GZ_PARTITION PX4_GZ_WORLD=$PX4_GZ_WORLD PX4_SIM_MODEL=$PX4_SIM_MODEL"
exec "$SYS_PY" "$PROJECT_DIR/server.py" "$@"
