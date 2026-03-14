"""
clients/ros2/aerialclaw_bridge.py — AerialClaw ROS2 桥接节点

将 ROS2 机器人接入 AerialClaw 服务端：
  - 订阅 /odom, /battery_state, /camera/image_raw 话题
  - 把 ROS2 传感器数据转换为 AerialClaw 协议上报
  - 接收 AerialClaw 下发的指令，转换为 ROS2 话题发布

使用方式（ROS2 Humble）：
    # 方式 1：直接运行
    python3 aerialclaw_bridge.py

    # 方式 2：作为 ROS2 节点（推荐）
    ros2 run <your_package> aerialclaw_bridge

环境变量（可选覆盖默认值）：
    AERIALCLAW_SERVER=http://localhost:5001
    AERIALCLAW_DEVICE_ID=ros2_robot_01
    AERIALCLAW_DEVICE_TYPE=UGV

依赖：
    pip install requests python-socketio[client]
    # ROS2 Humble 内置: rclpy, sensor_msgs, nav_msgs, std_msgs
"""

from __future__ import annotations

import base64
import os
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import requests
import socketio

# ── ROS2 导入（运行时需要 source /opt/ros/humble/setup.bash）──
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState, Image
from std_msgs.msg import String


# ══════════════════════════════════════════════════════════════
#  配置
# ══════════════════════════════════════════════════════════════

AERIALCLAW_SERVER: str = os.getenv("AERIALCLAW_SERVER", "http://localhost:5001")
DEVICE_ID: str         = os.getenv("AERIALCLAW_DEVICE_ID", "ros2_robot_01")
DEVICE_TYPE: str       = os.getenv("AERIALCLAW_DEVICE_TYPE", "UGV")

# 传感器上报频率限制（秒），防止带宽过载
ODOM_REPORT_INTERVAL:    float = 0.5    # 里程计：每 0.5 秒上报一次
BATTERY_REPORT_INTERVAL: float = 5.0   # 电池：每 5 秒上报一次
CAMERA_REPORT_INTERVAL:  float = 1.0   # 相机：每 1 秒上报一帧
HEARTBEAT_INTERVAL:      float = 5.0   # 心跳：每 5 秒

# 能力与传感器声明
CAPABILITIES: List[str] = ["drive", "camera"]
SENSORS: List[str]      = ["odom", "battery", "camera_front"]


# ══════════════════════════════════════════════════════════════
#  AerialClaw 连接层（复用 Python 客户端逻辑）
# ══════════════════════════════════════════════════════════════

class AerialClawConnection:
    """
    封装与 AerialClaw 服务端的 HTTP + WebSocket 通信。
    供 ROS2 桥接节点调用。
    """

    def __init__(
        self,
        server_url: str,
        device_id: str,
        device_type: str,
        capabilities: List[str],
        sensors: List[str],
    ) -> None:
        self.server_url  = server_url.rstrip("/")
        self.device_id   = device_id
        self.device_type = device_type
        self.capabilities = capabilities
        self.sensors      = sensors

        self._token: Optional[str] = None
        self._sio    = socketio.Client(reconnection=True, reconnection_attempts=10)
        self._connected = threading.Event()
        self._stop      = threading.Event()
        self._action_cb: Optional[
            Callable[[str, str, Dict[str, Any]], Tuple[bool, str, Dict[str, Any]]]
        ] = None

        self._register_handlers()

    # ── 公开接口 ──────────────────────────────────────────────

    def register(self) -> None:
        """HTTP 注册设备。"""
        resp = requests.post(
            f"{self.server_url}/api/device/register",
            json={
                "device_id":    self.device_id,
                "device_type":  self.device_type,
                "capabilities": self.capabilities,
                "sensors":      self.sensors,
                "protocol":     "ros2",
                "metadata":     {"ros_distro": "humble"},
            },
            timeout=10,
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"设备注册失败: {data.get('error')}")
        self._token = data["token"]

    def connect(self) -> None:
        """建立 WebSocket 连接，启动心跳线程。"""
        if not self._token:
            raise RuntimeError("请先调用 register()")
        ws_url = f"{self.server_url}?token={self._token}"
        self._sio.connect(ws_url, transports=["websocket"])
        self._connected.wait(timeout=10)
        threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="aerialclaw-heartbeat",
        ).start()

    def emit_state(self, state: Dict[str, Any]) -> None:
        """上报设备状态。"""
        if self._sio.connected:
            self._sio.emit("device_state", {
                "device_id": self.device_id,
                "timestamp": time.time(),
                **state,
            })

    def emit_sensor(
        self,
        sensor_type: str,
        sensor_id: str,
        data: Dict[str, Any],
    ) -> None:
        """上报传感器数据。"""
        if self._sio.connected:
            self._sio.emit("device_sensor", {
                "device_id":   self.device_id,
                "timestamp":   time.time(),
                "sensor_type": sensor_type,
                "sensor_id":   sensor_id,
                "data":        data,
            })

    def set_action_callback(
        self,
        cb: Callable[[str, str, Dict[str, Any]], Tuple[bool, str, Dict[str, Any]]],
    ) -> None:
        """设置指令回调。"""
        self._action_cb = cb

    def disconnect(self) -> None:
        """断开并注销。"""
        self._stop.set()
        if self._sio.connected:
            self._sio.disconnect()
        if self._token:
            try:
                requests.delete(
                    f"{self.server_url}/api/device/{self.device_id}",
                    headers={"Authorization": f"Bearer {self._token}"},
                    timeout=5,
                )
            except Exception:
                pass

    # ── 内部实现 ──────────────────────────────────────────────

    def _register_handlers(self) -> None:
        @self._sio.on("connect")
        def _on_connect() -> None:
            self._sio.emit("device_connect", {
                "device_id": self.device_id,
                "token":     self._token,
            })

        @self._sio.on("device_connected")
        def _on_authed(data: Dict[str, Any]) -> None:
            if data.get("ok"):
                self._connected.set()

        @self._sio.on("device_action")
        def _on_action(data: Dict[str, Any]) -> None:
            action_id = data.get("action_id", "")
            action    = data.get("action", "")
            params    = data.get("params", {})
            if not self._action_cb:
                self._reply(action_id, False, "无动作处理器", {})
                return
            t0 = time.time()
            try:
                ok, msg, out = self._action_cb(action_id, action, params)
            except Exception as e:
                ok, msg, out = False, f"回调异常: {e}", {}
            self._reply(action_id, ok, msg, out, time.time() - t0)

        @self._sio.on("heartbeat_ack")
        def _on_ack(_: Any) -> None:
            pass

    def _reply(
        self,
        action_id: str,
        success: bool,
        message: str,
        output: Dict[str, Any],
        cost_time: float = 0.0,
    ) -> None:
        self._sio.emit("action_result", {
            "action_id": action_id,
            "device_id": self.device_id,
            "success":   success,
            "message":   message,
            "output":    output,
            "cost_time": cost_time,
        })

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            if self._sio.connected:
                self._sio.emit("heartbeat", {
                    "device_id": self.device_id,
                    "timestamp": time.time(),
                })
            self._stop.wait(timeout=HEARTBEAT_INTERVAL)


# ══════════════════════════════════════════════════════════════
#  ROS2 桥接节点
# ══════════════════════════════════════════════════════════════

class AerialClawBridge(Node):
    """
    ROS2 桥接节点，将 ROS2 话题与 AerialClaw 服务端双向互联。

    话题订阅（ROS2 → AerialClaw）：
        /odom              nav_msgs/Odometry      → odom 传感器
        /battery_state     sensor_msgs/BatteryState → 电池状态
        /camera/image_raw  sensor_msgs/Image      → 相机图像

    话题发布（AerialClaw → ROS2）：
        /aerialclaw/action  std_msgs/String       → JSON 格式的指令
    """

    def __init__(self) -> None:
        super().__init__("aerialclaw_bridge")
        self.get_logger().info("AerialClaw 桥接节点启动中...")

        # 上报时间限速
        self._last_odom_report    = 0.0
        self._last_battery_report = 0.0
        self._last_camera_report  = 0.0

        # 缓存最新里程计用于状态上报
        self._latest_battery: float = 100.0
        self._latest_position: Dict[str, float] = {"north": 0.0, "east": 0.0, "down": 0.0}

        # ── 初始化 AerialClaw 连接 ───────────────────────────
        self._ac = AerialClawConnection(
            server_url=AERIALCLAW_SERVER,
            device_id=DEVICE_ID,
            device_type=DEVICE_TYPE,
            capabilities=CAPABILITIES,
            sensors=SENSORS,
        )
        self._ac.set_action_callback(self._handle_action)

        try:
            self._ac.register()
            self._get_logger().info(f"设备注册成功: {DEVICE_ID}")
            self._ac.connect()
            self.get_logger().info("AerialClaw WebSocket 已连接")
        except Exception as e:
            self.get_logger().error(f"AerialClaw 连接失败: {e}")
            raise

        # ── ROS2 订阅者 ──────────────────────────────────────

        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            depth=10,
        )

        # 里程计（包含位置、速度、姿态）
        self.create_subscription(
            Odometry,
            "/odom",
            self._on_odom,
            qos,
        )

        # 电池状态
        self.create_subscription(
            BatteryState,
            "/battery_state",
            self._on_battery,
            qos,
        )

        # 相机图像（压缩后上报）
        self.create_subscription(
            Image,
            "/camera/image_raw",
            self._on_camera,
            qos,
        )

        # ── ROS2 发布者（AerialClaw → ROS2）─────────────────
        self._action_pub = self.create_publisher(
            String,
            "/aerialclaw/action",
            10,
        )

        self.get_logger().info("订阅话题: /odom, /battery_state, /camera/image_raw")
        self.get_logger().info("发布话题: /aerialclaw/action")
        self.get_logger().info("桥接节点就绪！")

    # ── ROS2 话题回调（ROS2 → AerialClaw）───────────────────

    def _on_odom(self, msg: Odometry) -> None:
        """里程计回调：转换为 NED 坐标并上报。"""
        now = time.time()
        if now - self._last_odom_report < ODOM_REPORT_INTERVAL:
            return
        self._last_odom_report = now

        pos = msg.pose.pose.position
        # ROS2 默认坐标系为 ENU，转换为 AerialClaw NED
        # ENU (x=East, y=North, z=Up) → NED (north, east, down=-z)
        north = pos.y
        east  = pos.x
        down  = -pos.z
        self._latest_position = {"north": north, "east": east, "down": down}

        vel = msg.twist.twist.linear
        orient = msg.pose.pose.orientation

        self._ac.emit_sensor("odom", "odom_main", {
            "position":    {"north": north, "east": east, "down": down},
            "velocity":    {"vx": vel.x, "vy": vel.y, "vz": vel.z},
            "orientation": {
                "x": orient.x,
                "y": orient.y,
                "z": orient.z,
                "w": orient.w,
            },
        })

        # 同步更新设备状态
        self._ac.emit_state({
            "battery":  self._latest_battery,
            "position": self._latest_position,
            "status":   "idle",
        })

    def _on_battery(self, msg: BatteryState) -> None:
        """电池状态回调：上报电量百分比。"""
        now = time.time()
        if now - self._last_battery_report < BATTERY_REPORT_INTERVAL:
            return
        self._last_battery_report = now

        # BatteryState.percentage 范围 0.0~1.0，转为百分比
        pct = msg.percentage * 100.0 if msg.percentage >= 0 else -1.0
        self._latest_battery = pct

        self._ac.emit_sensor("battery", "battery_main", {
            "percentage": pct,
            "voltage":    msg.voltage,
            "current":    msg.current,
            "charge":     msg.charge,
            "capacity":   msg.capacity,
            "power_supply_status": msg.power_supply_status,
        })

    def _on_camera(self, msg: Image) -> None:
        """相机回调：将图像 Base64 编码后上报（降帧）。"""
        now = time.time()
        if now - self._last_camera_report < CAMERA_REPORT_INTERVAL:
            return
        self._last_camera_report = now

        # 原始图像数据 → Base64
        img_b64 = base64.b64encode(bytes(msg.data)).decode("ascii")

        self._ac.emit_sensor("camera", "camera_front", {
            "image_base64": img_b64,
            "width":        msg.width,
            "height":       msg.height,
            "encoding":     msg.encoding,   # e.g. "rgb8", "bgr8"
            "step":         msg.step,
        })

    # ── AerialClaw → ROS2 指令处理 ───────────────────────────

    def _handle_action(
        self,
        action_id: str,
        action: str,
        params: Dict[str, Any],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        接收 AerialClaw 下发的指令，发布到 /aerialclaw/action 话题。

        下游 ROS2 节点（如导航栈、执行器）订阅此话题并执行。
        当前实现：异步发布，立即返回成功（fire-and-forget）。
        如需同步等待结果，可替换为 Action Server 模式。
        """
        import json

        payload = {
            "action_id": action_id,
            "action":    action,
            "params":    params,
            "timestamp": time.time(),
        }

        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self._action_pub.publish(msg)

        self.get_logger().info(
            f"[指令] 已发布到 /aerialclaw/action: {action} {params}"
        )
        return True, f"指令 {action} 已发布到 ROS2", {}

    # ── 清理 ─────────────────────────────────────────────────

    def destroy_node(self) -> None:
        """节点销毁时断开 AerialClaw 连接。"""
        self.get_logger().info("桥接节点关闭，断开 AerialClaw...")
        self._ac.disconnect()
        super().destroy_node()

    # ── 私有辅助 ─────────────────────────────────────────────

    def _get_logger(self):
        """兼容调用（__init__ 中 super().__init__ 之前不可用 get_logger）。"""
        return self.get_logger()


# ══════════════════════════════════════════════════════════════
#  入口
# ══════════════════════════════════════════════════════════════

def main(args=None) -> None:
    """ROS2 节点入口，供 ros2 run 调用或直接 python3 运行。"""
    rclpy.init(args=args)
    node = AerialClawBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info("收到 Ctrl-C，退出...")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
