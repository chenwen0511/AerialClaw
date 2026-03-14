"""
clients/python/aerialclaw_client.py — AerialClaw Python 设备客户端

轻量级封装，设备端用来接入 AerialClaw 服务端。
依赖：requests, python-socketio[client]

快速开始：
    client = AerialClawClient(
        server_url="http://localhost:5001",
        device_id="drone_01",
        device_type="UAV",
        capabilities=["fly", "camera"],
        sensors=["gps", "imu"],
    )
    client.register()
    client.connect_ws()

    @client.on_action
    def handle_action(action_id, action, params):
        print(f"执行指令: {action}, 参数: {params}")
        return True, "执行完成", {"result": "ok"}

    # 保持运行
    client.wait()
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
import socketio

# ──────────────────────────────────────────────────────────────
#  类型别名
# ──────────────────────────────────────────────────────────────

# 动作回调签名: (action_id, action, params) → (success, message, output)
ActionCallback = Callable[
    [str, str, Dict[str, Any]],
    Tuple[bool, str, Dict[str, Any]],
]


class AerialClawClient:
    """AerialClaw 设备端 Python 客户端。"""

    def __init__(
        self,
        server_url: str,
        device_id: str,
        device_type: str,
        capabilities: List[str],
        sensors: List[str],
        protocol: str = "http",
        metadata: Optional[Dict[str, Any]] = None,
        heartbeat_interval: float = 5.0,
    ) -> None:
        """
        Args:
            server_url:          AerialClaw 服务端地址，如 "http://localhost:5001"
            device_id:           设备唯一 ID，如 "drone_01"
            device_type:         设备类型：UAV / UGV / ARM / SENSOR / CUSTOM
            capabilities:        能力列表，如 ["fly", "camera"]
            sensors:             传感器列表，如 ["gps", "imu"]
            protocol:            协议标识，默认 "http"
            metadata:            附加元信息（型号、固件等），可选
            heartbeat_interval:  心跳间隔秒数，默认 5 秒
        """
        self.server_url = server_url.rstrip("/")
        self.device_id = device_id
        self.device_type = device_type
        self.capabilities = capabilities
        self.sensors = sensors
        self.protocol = protocol
        self.metadata = metadata or {}
        self.heartbeat_interval = heartbeat_interval

        self._token: Optional[str] = None
        self._sio = socketio.Client(reconnection=True, reconnection_attempts=5)
        self._action_callback: Optional[ActionCallback] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._connected = threading.Event()

        # 注册内部 Socket.IO 事件处理器
        self._register_sio_handlers()

    # ──────────────────────────────────────────────────────────
    #  公开 API
    # ──────────────────────────────────────────────────────────

    def register(self) -> str:
        """向服务端注册设备，保存并返回 Token。"""
        resp = requests.post(
            f"{self.server_url}/api/device/register",
            json={
                "device_id":    self.device_id,
                "device_type":  self.device_type,
                "capabilities": self.capabilities,
                "sensors":      self.sensors,
                "protocol":     self.protocol,
                "metadata":     self.metadata,
            },
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"注册失败: {data.get('error')}")
        self._token = data["token"]
        print(f"[AerialClaw] 设备 {self.device_id} 注册成功，Token: {self._token}")
        return self._token

    def connect_ws(self) -> None:
        """建立 WebSocket 连接并完成身份认证，启动心跳线程。"""
        if not self._token:
            raise RuntimeError("请先调用 register() 获取 Token")

        # Token 通过 URL 查询参数传递
        ws_url = f"{self.server_url}?token={self._token}"
        self._sio.connect(ws_url, transports=["websocket"])

        # 等待服务端 device_connected 确认（最多 5 秒）
        self._connected.wait(timeout=5)

        # 启动心跳后台线程
        self._stop_event.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="aerialclaw-heartbeat",
        )
        self._heartbeat_thread.start()

    def report_state(self, state: Dict[str, Any]) -> None:
        """通过 WebSocket 上报设备状态。"""
        self._sio.emit("device_state", {
            "device_id": self.device_id,
            "timestamp": time.time(),
            **state,
        })

    def report_sensor(
        self,
        sensor_type: str,
        sensor_id: str,
        data: Dict[str, Any],
    ) -> None:
        """通过 WebSocket 上报传感器数据。"""
        self._sio.emit("device_sensor", {
            "device_id":   self.device_id,
            "timestamp":   time.time(),
            "sensor_type": sensor_type,
            "sensor_id":   sensor_id,
            "data":        data,
        })

    def on_action(self, callback: ActionCallback) -> ActionCallback:
        """
        注册 device_action 回调（可用作装饰器）。

        回调签名：
            def handle(action_id: str, action: str, params: dict)
                -> (success: bool, message: str, output: dict)

        Example::
            @client.on_action
            def handle(action_id, action, params):
                return True, "done", {}
        """
        self._action_callback = callback
        return callback

    def disconnect(self) -> None:
        """断开 WebSocket 连接并注销设备。"""
        # 停止心跳
        self._stop_event.set()

        # 断开 WebSocket
        if self._sio.connected:
            self._sio.disconnect()

        # 注销设备
        if self._token:
            try:
                requests.delete(
                    f"{self.server_url}/api/device/{self.device_id}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=5,
                )
                print(f"[AerialClaw] 设备 {self.device_id} 已注销")
            except Exception as e:
                print(f"[AerialClaw] 注销请求失败（忽略）: {e}")

    def wait(self) -> None:
        """阻塞当前线程，直到 WebSocket 断开（适合脚本末尾保持运行）。"""
        self._sio.wait()

    # ──────────────────────────────────────────────────────────
    #  内部实现
    # ──────────────────────────────────────────────────────────

    def _register_sio_handlers(self) -> None:
        """注册 Socket.IO 事件处理器。"""

        @self._sio.on("connect")
        def _on_connect() -> None:
            # 连接后立即发送认证消息
            self._sio.emit("device_connect", {
                "device_id": self.device_id,
                "token":     self._token,
            })

        @self._sio.on("device_connected")
        def _on_device_connected(data: Dict[str, Any]) -> None:
            if data.get("ok"):
                print(f"[AerialClaw] WebSocket 认证成功: {data.get('message')}")
                self._connected.set()
            else:
                print(f"[AerialClaw] WebSocket 认证失败: {data}")

        @self._sio.on("device_action")
        def _on_action(data: Dict[str, Any]) -> None:
            action_id = data.get("action_id", "")
            action    = data.get("action", "")
            params    = data.get("params", {})

            if not self._action_callback:
                # 没有注册回调，返回不支持
                self._report_action_result(action_id, False, "未注册动作处理器", {})
                return

            t0 = time.time()
            try:
                success, message, output = self._action_callback(
                    action_id, action, params
                )
            except Exception as e:
                success, message, output = False, f"回调异常: {e}", {}

            self._report_action_result(
                action_id, success, message, output,
                cost_time=time.time() - t0,
            )

        @self._sio.on("heartbeat_ack")
        def _on_heartbeat_ack(_data: Any) -> None:
            pass  # 心跳确认，静默处理

        @self._sio.on("disconnect")
        def _on_disconnect() -> None:
            print("[AerialClaw] WebSocket 已断开")
            self._connected.clear()

    def _report_action_result(
        self,
        action_id: str,
        success: bool,
        message: str,
        output: Dict[str, Any],
        cost_time: float = 0.0,
    ) -> None:
        """向服务端回报指令执行结果。"""
        self._sio.emit("action_result", {
            "action_id": action_id,
            "device_id": self.device_id,
            "success":   success,
            "message":   message,
            "output":    output,
            "cost_time": cost_time,
        })

    def _heartbeat_loop(self) -> None:
        """心跳后台线程：每 heartbeat_interval 秒发一次心跳。"""
        while not self._stop_event.is_set():
            if self._sio.connected:
                self._sio.emit("heartbeat", {
                    "device_id": self.device_id,
                    "timestamp": time.time(),
                })
            self._stop_event.wait(timeout=self.heartbeat_interval)


# ──────────────────────────────────────────────────────────────
#  使用示例（直接运行此文件可测试）
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import math

    client = AerialClawClient(
        server_url="http://localhost:5001",
        device_id="demo_drone",
        device_type="UAV",
        capabilities=["fly", "camera"],
        sensors=["gps", "imu"],
        metadata={"model": "Demo UAV", "firmware": "v1.0"},
    )

    client.register()
    client.connect_ws()

    @client.on_action
    def handle(action_id: str, action: str, params: dict):
        print(f"  → 收到指令: {action}，参数: {params}")
        return True, f"{action} 执行成功", {"echo": params}

    # 模拟上报状态
    for i in range(3):
        client.report_state({
            "battery":  90.0 - i,
            "position": {"north": float(i), "east": 0.0, "down": -5.0},
            "status":   "idle",
        })
        client.report_sensor("imu", "imu_main", {
            "accel": [0.0, 0.0, -9.81],
            "gyro":  [0.0, 0.0, 0.0],
        })
        time.sleep(2)

    client.disconnect()
