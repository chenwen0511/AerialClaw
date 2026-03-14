"""
adapters/protocol_adapter.py — 通用协议适配器

通过 DeviceManager 代理所有操作，让任何实现了通用协议的设备
都能被 AerialClaw 当作标准硬件使用。

使用场景：
  - HTTP/WebSocket 接入的第三方设备
  - Arduino/ESP32 通过通用协议接入
  - ROS2 设备通过桥接节点接入
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from adapters.base_adapter import BaseAdapter, RobotType
from core.device_manager import (
    Action,
    ActionResult,
    Device,
    DeviceManager,
)
from core.logger import get_logger

logger = get_logger(__name__)

# 设备类型到 RobotType 映射
_TYPE_MAP: Dict[str, RobotType] = {
    "UAV": RobotType.DRONE,
    "UGV": RobotType.GROUND_VEHICLE,
    "ARM": RobotType.ARM,
    "SENSOR": RobotType.SENSOR,
}


class ProtocolAdapter(BaseAdapter):
    """
    通用协议适配器。

    将 BaseAdapter 的标准接口代理到 DeviceManager，
    通过通用协议（HTTP + WebSocket）与设备通信。
    """

    def __init__(
        self,
        device_manager: DeviceManager,
        device_id: str,
    ) -> None:
        """
        Args:
            device_manager: 设备管理器实例
            device_id: 目标设备 ID
        """
        device = device_manager.get_device(device_id)
        device_type = device.info.device_type if device else "CUSTOM"
        robot_type = _TYPE_MAP.get(device_type, RobotType.SENSOR)

        super().__init__(robot_id=device_id, robot_type=robot_type)

        self.dm = device_manager
        self.device_id = device_id
        self.name = f"ProtocolAdapter({device_id})"

    # ── BaseAdapter 实现 ─────────────────────────────────────

    def connect(self) -> bool:
        """检查设备是否在线"""
        device = self.dm.get_device(self.device_id)
        if device and device.status == "online":
            self.is_connected = True
            return True
        self.is_connected = False
        return False

    def disconnect(self) -> bool:
        """断开设备连接"""
        self.is_connected = False
        return True

    def get_sensor_data(self) -> Dict[str, Any]:
        """获取设备最新传感器数据"""
        try:
            state = self.dm.get_device_state(self.device_id)
            return state.get("sensor_data", {})
        except Exception as e:
            logger.warning("获取传感器数据失败 [%s]: %s", self.device_id, e)
            return {}

    def execute_command(self, command: str, params: Dict[str, Any]) -> bool:
        """执行控制命令"""
        try:
            action = Action(action=command, params=params)
            result = self.dm.send_action(self.device_id, action)
            return result.success
        except Exception as e:
            logger.error("命令执行失败 [%s] %s: %s", self.device_id, command, e)
            return False

    def get_status(self) -> Dict[str, Any]:
        """获取设备状态"""
        try:
            state = self.dm.get_device_state(self.device_id)
            return {
                "battery": state.get("state", {}).get("battery", 0),
                "position": state.get("state", {}).get("position", [0, 0, 0]),
                "state": state.get("state", {}).get("status", "unknown"),
                "errors": state.get("state", {}).get("errors", []),
                "online": state.get("status") == "online",
            }
        except Exception as e:
            logger.warning("获取状态失败 [%s]: %s", self.device_id, e)
            return {"battery": 0, "position": [0, 0, 0], "state": "error", "errors": [str(e)]}

    def get_capabilities(self) -> List[str]:
        """返回设备支持的能力列表"""
        device = self.dm.get_device(self.device_id)
        if device:
            return device.info.capabilities
        return []

    # ── 高级指令（代理到 DeviceManager）──────────────────────

    def _send(self, action: str, params: Optional[Dict[str, Any]] = None,
              timeout: float = 30.0) -> ActionResult:
        """通用指令发送"""
        return self.dm.send_action(
            self.device_id,
            Action(action=action, params=params or {}, timeout=timeout),
        )

    def takeoff(self, altitude: float = 5.0) -> ActionResult:
        """起飞到指定高度"""
        return self._send("takeoff", {"altitude": altitude})

    def land(self) -> ActionResult:
        """降落"""
        return self._send("land")

    def fly_to(self, north: float, east: float, down: float) -> ActionResult:
        """飞行到指定 NED 坐标"""
        return self._send("fly_to", {"north": north, "east": east, "down": down})

    def hover(self, duration: float = 0) -> ActionResult:
        """悬停"""
        return self._send("hover", {"duration": duration})

    def return_to_launch(self) -> ActionResult:
        """返航"""
        return self._send("return_to_launch")

    def change_altitude(self, altitude: float) -> ActionResult:
        """改变高度"""
        return self._send("change_altitude", {"altitude": altitude})

    def set_velocity_body(
        self, forward: float, right: float, down: float, yaw_rate: float = 0
    ) -> ActionResult:
        """Body 坐标系速度控制"""
        return self._send("velocity_control", {
            "forward": forward,
            "right": right,
            "down": down,
            "yaw_rate": yaw_rate,
        })

    def stop_velocity(self) -> ActionResult:
        """停止运动"""
        return self._send("velocity_control", {
            "forward": 0, "right": 0, "down": 0, "yaw_rate": 0,
        })

    # ── 查询指令 ─────────────────────────────────────────────

    def get_position(self) -> Dict[str, float]:
        """获取当前位置 (NED)"""
        state = self.dm.get_device_state(self.device_id)
        pos = state.get("state", {}).get("position", {})
        if isinstance(pos, list) and len(pos) >= 3:
            return {"north": pos[0], "east": pos[1], "down": pos[2]}
        if isinstance(pos, dict):
            return pos
        return {"north": 0, "east": 0, "down": 0}

    def get_battery(self) -> float:
        """获取电量百分比"""
        state = self.dm.get_device_state(self.device_id)
        return state.get("state", {}).get("battery", 0)

    def is_in_air(self) -> bool:
        """是否在空中"""
        state = self.dm.get_device_state(self.device_id)
        return state.get("state", {}).get("in_air", False)

    def is_armed(self) -> bool:
        """是否解锁"""
        state = self.dm.get_device_state(self.device_id)
        return state.get("state", {}).get("armed", False)

    def is_connected(self) -> bool:
        """设备是否在线"""
        device = self.dm.get_device(self.device_id)
        return device is not None and device.status == "online"
