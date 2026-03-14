"""
core/device_manager.py — 通用设备管理器

管理所有通过通用协议接入的设备：
  - 注册/注销
  - 状态与传感器数据更新
  - 指令下发与结果回收
  - 心跳检测（10s 超时 → offline）
  - 线程安全
"""

from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.errors import (
    DeviceNotFoundError,
    DeviceTimeoutError,
)
from core.logger import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
#  Data Classes
# ══════════════════════════════════════════════════════════════


@dataclass
class DeviceInfo:
    """设备注册信息"""
    device_id: str
    device_type: str                  # UAV / UGV / ARM / SENSOR / CUSTOM
    capabilities: List[str]           # ["fly", "camera", "lidar"]
    sensors: List[str]                # ["gps", "imu", "camera_front"]
    protocol: str                     # mavlink / ros2 / http / custom
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Action:
    """下发给设备的指令"""
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    timeout: float = 30.0


@dataclass
class ActionResult:
    """指令执行结果"""
    action_id: str
    success: bool
    message: str = ""
    output: Dict[str, Any] = field(default_factory=dict)
    cost_time: float = 0.0


@dataclass
class Device:
    """设备运行时状态"""
    info: DeviceInfo
    token: str
    status: str = "online"            # online / offline
    last_heartbeat: float = 0.0
    state: Dict[str, Any] = field(default_factory=dict)
    sensor_data: Dict[str, Any] = field(default_factory=dict)
    registered_at: float = 0.0
    ws_sid: Optional[str] = None      # WebSocket session ID


# ══════════════════════════════════════════════════════════════
#  Device Manager
# ══════════════════════════════════════════════════════════════


class DeviceManager:
    """
    通用设备管理器。

    管理所有通过通用协议（HTTP + WebSocket）接入的设备。
    线程安全，支持并发注册/更新/查询。
    """

    HEARTBEAT_TIMEOUT = 10.0  # 秒，心跳超时阈值

    def __init__(self) -> None:
        self._devices: Dict[str, Device] = {}
        self._lock = threading.RLock()
        self._action_callbacks: Dict[str, Callable] = {}
        self._pending_actions: Dict[str, threading.Event] = {}
        self._action_results: Dict[str, ActionResult] = {}
        self._on_device_offline: Optional[Callable[[str], None]] = None
        self._on_device_online: Optional[Callable[[str], None]] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._running = False

    # ── 生命周期 ─────────────────────────────────────────────

    def start(self) -> None:
        """启动心跳监控线程"""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._heartbeat_monitor,
            daemon=True,
            name="device-heartbeat-monitor",
        )
        self._monitor_thread.start()
        logger.info("设备管理器已启动 (心跳超时=%ss)", self.HEARTBEAT_TIMEOUT)

    def stop(self) -> None:
        """停止心跳监控"""
        self._running = False

    # ── 注册 / 注销 ─────────────────────────────────────────

    def register(self, info: DeviceInfo) -> str:
        """
        注册设备，返回认证 Token。

        Args:
            info: 设备信息

        Returns:
            token: 设备认证令牌

        Raises:
            ValueError: device_id 为空或已注册
        """
        if not info.device_id:
            raise ValueError("device_id 不能为空")

        with self._lock:
            if info.device_id in self._devices:
                raise ValueError(f"设备 {info.device_id} 已注册")

            token = f"ac_{info.device_id}_{secrets.token_hex(8)}"
            now = time.time()
            device = Device(
                info=info,
                token=token,
                status="online",
                last_heartbeat=now,
                registered_at=now,
            )
            self._devices[info.device_id] = device

        logger.info(
            "设备注册: %s (%s) 能力=%s",
            info.device_id, info.device_type, info.capabilities,
        )
        return token

    def unregister(self, device_id: str) -> None:
        """
        注销设备。

        Args:
            device_id: 设备 ID

        Raises:
            DeviceNotFoundError: 设备不存在
        """
        with self._lock:
            device = self._devices.pop(device_id, None)
            if device is None:
                raise DeviceNotFoundError(
                    f"设备 {device_id} 未注册",
                    fix_hint="请检查设备 ID 是否正确",
                )
        logger.info("设备注销: %s", device_id)

    # ── 认证 ─────────────────────────────────────────────────

    def validate_token(self, device_id: str, token: str) -> bool:
        """验证设备 Token"""
        with self._lock:
            device = self._devices.get(device_id)
            if device is None:
                return False
            return device.token == token

    # ── 状态更新 ─────────────────────────────────────────────

    def update_state(self, device_id: str, state: Dict[str, Any]) -> None:
        """
        更新设备状态。

        Args:
            device_id: 设备 ID
            state: 状态字典

        Raises:
            DeviceNotFoundError: 设备不存在
        """
        device = self._get_device(device_id)
        with self._lock:
            device.state.update(state)
            device.last_heartbeat = time.time()
            if device.status == "offline":
                device.status = "online"
                logger.info("设备恢复在线: %s", device_id)
                if self._on_device_online:
                    self._on_device_online(device_id)

    def update_sensor(self, device_id: str, data: Dict[str, Any]) -> None:
        """
        更新传感器数据。

        Args:
            device_id: 设备 ID
            data: 传感器数据，包含 sensor_type 和 sensor_id

        Raises:
            DeviceNotFoundError: 设备不存在
        """
        device = self._get_device(device_id)
        sensor_id = data.get("sensor_id", data.get("sensor_type", "unknown"))
        with self._lock:
            device.sensor_data[sensor_id] = data
            device.last_heartbeat = time.time()

    def heartbeat(self, device_id: str) -> None:
        """
        处理设备心跳。

        Args:
            device_id: 设备 ID

        Raises:
            DeviceNotFoundError: 设备不存在
        """
        device = self._get_device(device_id)
        with self._lock:
            device.last_heartbeat = time.time()
            if device.status == "offline":
                device.status = "online"
                logger.info("设备恢复在线: %s", device_id)
                if self._on_device_online:
                    self._on_device_online(device_id)

    # ── 指令下发 ─────────────────────────────────────────────

    def send_action(
        self,
        device_id: str,
        action: Action,
    ) -> ActionResult:
        """
        向设备下发指令并等待结果。

        通过 WebSocket 推送 device_action 事件到设备端，
        设备执行后通过 action_result 事件回报。

        Args:
            device_id: 设备 ID
            action: 指令

        Returns:
            ActionResult: 执行结果

        Raises:
            DeviceNotFoundError: 设备不存在
            DeviceTimeoutError: 设备离线或执行超时
        """
        device = self._get_device(device_id)

        if device.status == "offline":
            raise DeviceTimeoutError(
                f"设备 {device_id} 离线，无法下发指令",
                fix_hint="请检查设备连接和心跳状态",
            )

        action_id = f"act_{int(time.time())}_{secrets.token_hex(4)}"
        event = threading.Event()

        with self._lock:
            self._pending_actions[action_id] = event

        # 通过回调函数推送指令到设备
        action_payload = {
            "action_id": action_id,
            "device_id": device_id,
            "action": action.action,
            "params": action.params,
            "timeout": action.timeout,
        }

        callback = self._action_callbacks.get(device_id)
        if callback:
            try:
                callback(action_payload)
            except Exception as e:
                logger.error("指令下发失败 [%s]: %s", device_id, e)
                with self._lock:
                    self._pending_actions.pop(action_id, None)
                return ActionResult(
                    action_id=action_id,
                    success=False,
                    message=f"指令下发失败: {e}",
                )

        # 等待设备回报
        start = time.time()
        completed = event.wait(timeout=action.timeout)
        elapsed = time.time() - start

        with self._lock:
            self._pending_actions.pop(action_id, None)
            result = self._action_results.pop(action_id, None)

        if not completed or result is None:
            raise DeviceTimeoutError(
                f"指令 {action.action} 执行超时 ({action.timeout}s)",
                fix_hint="设备可能离线或处理时间过长",
            )

        result.cost_time = elapsed
        return result

    def report_action_result(self, action_id: str, result: ActionResult) -> None:
        """
        设备回报指令执行结果。

        Args:
            action_id: 指令 ID
            result: 执行结果
        """
        with self._lock:
            self._action_results[action_id] = result
            event = self._pending_actions.get(action_id)
            if event:
                event.set()

    # ── 注册回调 ─────────────────────────────────────────────

    def set_action_callback(
        self,
        device_id: str,
        callback: Callable[[Dict[str, Any]], None],
    ) -> None:
        """注册指令下发回调（WebSocket emit 函数）"""
        with self._lock:
            self._action_callbacks[device_id] = callback

    def set_ws_sid(self, device_id: str, sid: str) -> None:
        """绑定 WebSocket session ID"""
        device = self._get_device(device_id)
        with self._lock:
            device.ws_sid = sid

    def on_device_offline(self, callback: Callable[[str], None]) -> None:
        """注册设备离线回调"""
        self._on_device_offline = callback

    def on_device_online(self, callback: Callable[[str], None]) -> None:
        """注册设备上线回调"""
        self._on_device_online = callback

    # ── 查询 ─────────────────────────────────────────────────

    def list_devices(self) -> List[Device]:
        """返回所有已注册设备"""
        with self._lock:
            return list(self._devices.values())

    def get_device(self, device_id: str) -> Optional[Device]:
        """获取设备（不抛异常）"""
        with self._lock:
            return self._devices.get(device_id)

    def get_device_state(self, device_id: str) -> Dict[str, Any]:
        """获取设备状态"""
        device = self._get_device(device_id)
        with self._lock:
            return {
                "device_id": device_id,
                "device_type": device.info.device_type,
                "status": device.status,
                "last_heartbeat": device.last_heartbeat,
                "state": dict(device.state),
                "sensor_data": dict(device.sensor_data),
            }

    def device_count(self) -> int:
        """返回注册设备数"""
        with self._lock:
            return len(self._devices)

    # ── 内部方法 ─────────────────────────────────────────────

    def _get_device(self, device_id: str) -> Device:
        """获取设备，不存在则抛异常"""
        with self._lock:
            device = self._devices.get(device_id)
        if device is None:
            raise DeviceNotFoundError(
                f"设备 {device_id} 未注册",
                fix_hint="请先通过 POST /api/device/register 注册设备",
            )
        return device

    def _heartbeat_monitor(self) -> None:
        """后台线程：检测心跳超时"""
        while self._running:
            try:
                now = time.time()
                with self._lock:
                    for device_id, device in self._devices.items():
                        if device.status != "online":
                            continue
                        elapsed = now - device.last_heartbeat
                        if elapsed > self.HEARTBEAT_TIMEOUT:
                            device.status = "offline"
                            logger.warning(
                                "设备心跳超时: %s (%.1fs 无响应)",
                                device_id, elapsed,
                            )
                            if self._on_device_offline:
                                try:
                                    self._on_device_offline(device_id)
                                except Exception as e:
                                    logger.error(
                                        "离线回调异常 [%s]: %s",
                                        device_id, e,
                                    )
            except Exception as e:
                logger.error("心跳监控异常: %s", e)
            time.sleep(2)

    def to_dict(self, device: Device) -> Dict[str, Any]:
        """设备序列化为字典（供 API 返回）"""
        return {
            "device_id": device.info.device_id,
            "device_type": device.info.device_type,
            "capabilities": device.info.capabilities,
            "sensors": device.info.sensors,
            "protocol": device.info.protocol,
            "metadata": device.info.metadata,
            "status": device.status,
            "last_heartbeat": device.last_heartbeat,
            "registered_at": device.registered_at,
            "state": dict(device.state),
        }