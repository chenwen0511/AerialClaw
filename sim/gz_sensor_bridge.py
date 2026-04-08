"""
sim/gz_sensor_bridge.py
聚合 Gazebo Transport：多路相机 + 2D 激光雷达，供 server 与技能使用。
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

from perception.gz_camera import GzCamera

logger = logging.getLogger(__name__)


class GzSensorBridge:
    """
    封装 GzCamera（图像）与 LaserScan 订阅（雷达）。
    与 PX4 + Gazebo SITL 及环境变量 PX4_GZ_WORLD / PX4_SIM_MODEL 对齐。
    """

    def __init__(self, model_name: str, world_name: str):
        self._model = model_name
        self._world = world_name
        self._running = False
        self._camera: Optional[GzCamera] = None
        self._lidar_topic: Optional[str] = None
        self._last_lidar_msg = None
        self._lidar_node = None
        self._lidar_fps_t0 = 0.0
        self._lidar_fps_count = 0
        self._lidar_fps = 10.0

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """初始化 Gazebo Transport；若相机节点不可用则返回 False。"""
        try:
            timeout_ms = int(os.environ.get("GZ_CAMERA_TIMEOUT_MS", "8000"))
            self._camera = GzCamera(
                world=self._world,
                model=self._model,
                timeout_ms=timeout_ms,
                persistent=True,
            )
            self._camera._ensure_node()
        except Exception as e:
            logger.error("GzSensorBridge: 相机无法启动: %s", e, exc_info=True)
            self._camera = None
            return False

        self._lidar_topic = os.environ.get("GZ_LIDAR_TOPIC") or (
            f"/world/{self._world}/model/{self._model}/link/link/sensor/lidar/scan"
        )
        try:
            self._setup_lidar_subscriber()
        except Exception as e:
            logger.warning("GzSensorBridge: 激光雷达订阅失败（可忽略，仅无雷达数据）: %s", e)

        self._running = True
        logger.info(
            "GzSensorBridge 已启动 world=%s model=%s lidar_topic=%s",
            self._world,
            self._model,
            self._lidar_topic,
        )
        return True

    def _setup_lidar_subscriber(self) -> None:
        """订阅 LaserScan；依赖 python3-gz-msgs10 与 protobuf 与系统兼容。"""
        from gz.transport13 import Node
        from gz.msgs10.laserscan_pb2 import LaserScan

        self._lidar_node = Node()

        def _cb(msg) -> None:
            self._last_lidar_msg = msg
            now = time.time()
            if self._lidar_fps_t0 <= 0:
                self._lidar_fps_t0 = now
            self._lidar_fps_count += 1
            dt = now - self._lidar_fps_t0
            if dt >= 1.0 and self._lidar_fps_count > 0:
                self._lidar_fps = 0.99 * self._lidar_fps + 0.01 * (self._lidar_fps_count / dt)
                self._lidar_fps_t0 = now
                self._lidar_fps_count = 0

        if not self._lidar_node.subscribe(LaserScan, self._lidar_topic, _cb):
            logger.warning("GzSensorBridge: 订阅 LaserScan 失败: %s", self._lidar_topic)

    def get_camera_image(self, direction: str = "front"):
        if not self._camera:
            return None
        return self._camera.capture(direction)

    def get_camera_info(self, direction: str = "front") -> Dict[str, Any]:
        # 与 model.sdf 中相机一致（若抓图成功可再细化）
        return {"width": 640, "height": 480, "fps": 5.0}

    def get_lidar_scan(self) -> Optional[Dict[str, Any]]:
        msg = self._last_lidar_msg
        if msg is None:
            return None
        try:
            ranges = list(msg.ranges) if msg.ranges else []
            return {
                "ranges": ranges,
                "angle_min": float(msg.angle_min),
                "angle_max": float(msg.angle_max),
                "angle_increment": float(msg.angle_increment),
                "range_min": float(msg.range_min),
                "range_max": float(msg.range_max),
                "count": len(ranges),
                "is_3d": False,
            }
        except Exception as e:
            logger.debug("get_lidar_scan 解析失败: %s", e)
            return None

    def get_lidar_info(self) -> Dict[str, Any]:
        return {"fps": round(self._lidar_fps, 1)}

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "world": self._world,
            "model": self._model,
            "lidar_topic": self._lidar_topic,
        }
