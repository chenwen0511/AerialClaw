"""
airsim_adapter.py
AirSim SimpleFlight 仿真适配器（纯 socket 版，无 tornado/asyncio 依赖）。
"""

import math
import logging
import base64
from typing import Optional

from adapters.sim_adapter import (
    SimAdapter, Position, GPSPosition, VehicleState, ActionResult,
)

logger = logging.getLogger(__name__)


class AirSimAdapter(SimAdapter):
    """AirSim SimpleFlight 适配器，纯 socket RPC，兼容任意 event loop。"""

    name = "airsim_simpleflight"
    description = "AirSim SimpleFlight via pure-socket msgpack-rpc (no tornado dependency)"
    supported_vehicles = ["multirotor"]

    def __init__(self, vehicle_name: str = ""):
        self._vehicle_name = vehicle_name
        self._client = None
        self._connected = False
        self._home_position: Optional[Position] = None

    # ── 连接 ──────────────────────────────────────────────────────────

    def connect(self, connection_str: str = "", timeout: float = 15.0) -> bool:
        ip, port = "127.0.0.1", 41451
        if connection_str:
            parts = connection_str.split(":")
            ip = parts[0]
            if len(parts) > 1:
                port = int(parts[1])

        logger.info(f"Connecting to AirSim: {ip}:{port} (pure-socket RPC)")
        try:
            from adapters.airsim_rpc import AirSimDirectClient
            self._client = AirSimDirectClient(ip, port, timeout=timeout)
            if not self._client.connect():
                raise ConnectionError(f"Cannot connect to {ip}:{port}")
            if not self._client.ping():
                raise ConnectionError("ping failed")
            self._client.enable_api_control(True, self._vehicle_name)
            self._client.arm_disarm(True, self._vehicle_name)
            self._connected = True
            # 记录起飞原点
            pos = self._get_position_raw()
            if pos:
                self._home_position = pos
            logger.info(f"✅ AirSim connected: {ip}:{port}, vehicles={self._client.list_vehicles()}")
            return True
        except Exception as e:
            logger.error(f"❌ AirSim connect error: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        if self._client:
            self._client.close()
        self._connected = False

    # ── 状态读取 ──────────────────────────────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _get_position_raw(self) -> Optional[Position]:
        try:
            state = self._client.get_multirotor_state(self._vehicle_name)
            kin = state.get("kinematics_estimated", {})
            pos = kin.get("position", {})
            return Position(
                north=pos.get("x_val", 0.0),
                east=pos.get("y_val", 0.0),
                down=pos.get("z_val", 0.0),
            )
        except Exception:
            return None

    def get_state(self) -> Optional[VehicleState]:
        if not self._connected:
            return None
        try:
            raw = self._client.get_multirotor_state(self._vehicle_name)
            kin = raw.get("kinematics_estimated", {})
            pos = kin.get("position", {})
            vel = kin.get("linear_velocity", {})
            landed = raw.get("landed_state", 1)
            return VehicleState(
                position_ned=Position(
                    north=pos.get("x_val", 0.0),
                    east=pos.get("y_val", 0.0),
                    down=pos.get("z_val", 0.0),
                ),
                velocity=[vel.get("x_val", 0.0), vel.get("y_val", 0.0), vel.get("z_val", 0.0)],
                armed=True,
                in_air=(landed == 0),
            )
        except Exception as e:
            logger.warning(f"get_state error: {e}")
            return None

    def get_position(self) -> Optional[Position]:
        s = self.get_state()
        return s.position_ned if s else None

    def get_gps(self) -> Optional[GPSPosition]:
        return None  # SimpleFlight 无真实 GPS

    def get_battery(self) -> tuple:
        return (100.0, 100.0)

    def is_armed(self) -> bool:
        return self._connected

    def is_in_air(self) -> bool:
        s = self.get_state()
        return s.in_air if s else False

    # ── 飞行指令 ──────────────────────────────────────────────────────

    def arm(self) -> ActionResult:
        return ActionResult(success=True, message="AirSim: always armed when connected")

    def disarm(self) -> ActionResult:
        return ActionResult(success=True, message="AirSim: disarmed (mock)")

    def takeoff(self, altitude: float = 3.0) -> ActionResult:
        if not self._connected:
            return ActionResult(success=False, message="Not connected")
        try:
            self._client.takeoff_async_join(timeout_sec=20.0, vehicle_name=self._vehicle_name)
            return ActionResult(success=True, message=f"Takeoff to {altitude}m")
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def land(self) -> ActionResult:
        if not self._connected:
            return ActionResult(success=False, message="Not connected")
        try:
            self._client.land_async_join(vehicle_name=self._vehicle_name)
            return ActionResult(success=True, message="Landed")
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def hover(self, duration: float = 5.0) -> ActionResult:
        if not self._connected:
            return ActionResult(success=False, message="Not connected")
        try:
            self._client.hover_async_join(vehicle_name=self._vehicle_name)
            return ActionResult(success=True, message="Hovering")
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def fly_to(self, position: Position, speed: float = 5.0) -> ActionResult:
        return self.fly_to_ned(position.north, position.east, position.down, speed)

    def fly_to_ned(self, north: float, east: float, down: float,
                   speed: float = 5.0) -> ActionResult:
        if not self._connected:
            return ActionResult(success=False, message="Not connected")
        try:
            self._client.move_to_position_async_join(
                north, east, down, speed,
                timeout_sec=120.0, vehicle_name=self._vehicle_name
            )
            return ActionResult(success=True, message=f"Moved to ({north:.1f},{east:.1f},{down:.1f})")
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def return_to_launch(self) -> ActionResult:
        if self._home_position:
            return self.fly_to(self._home_position)
        return self.land()

    def get_home_position(self) -> Optional[Position]:
        return self._home_position

    def get_image_base64(self) -> Optional[str]:
        """获取 FPV 图像（JPEG base64）用于 Web UI 显示。"""
        if not self._connected:
            return None
        try:
            import cv2
            import numpy as np
            responses = self._client.sim_get_images([{
                "camera_name": "0",
                "image_type": 0,   # Scene
                "pixels_as_float": False,
                "compress": False,
            }], vehicle_name=self._vehicle_name)
            if responses:
                r = responses[0]
                h = r.get("height", 0)
                w = r.get("width", 0)
                data = r.get("image_data_uint8") or r.get("image_data", b"")
                if isinstance(data, str):
                    data = base64.b64decode(data)
                if h > 0 and w > 0 and data:
                    img = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
                    _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    return base64.b64encode(buf).decode()
        except Exception as e:
            logger.debug(f"get_image error: {e}")
        return None
