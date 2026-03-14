# AerialClaw 设备客户端

AerialClaw 遵循**大脑与身体分离**的设计原则。本目录提供三种"身体"接入模板，覆盖从嵌入式到机器人操作系统的典型场景。

---

## 目录结构

```
clients/
├── python/
│   └── aerialclaw_client.py   # Python 通用客户端
├── arduino/
│   └── aerialclaw_client.ino  # ESP32/Arduino 客户端
├── ros2/
│   └── aerialclaw_bridge.py   # ROS2 Humble 桥接节点
└── README.md
```

---

## Python 客户端 (`python/aerialclaw_client.py`)

适用于树莓派、Jetson、普通 Linux 设备，或任何能运行 Python 3.8+ 的平台。

### 安装依赖

```bash
pip install requests "python-socketio[client]"
```

### 快速开始

```python
from aerialclaw_client import AerialClawClient

client = AerialClawClient(
    server_url="http://192.168.1.100:5001",
    device_id="my_robot",
    device_type="UGV",
    capabilities=["drive", "camera"],
    sensors=["gps", "imu", "camera_front"],
)

# 1. 注册设备（获取 Token）
client.register()

# 2. 建立 WebSocket 连接（自动启动心跳）
client.connect_ws()

# 3. 注册指令处理器
@client.on_action
def handle(action_id: str, action: str, params: dict):
    print(f"执行: {action} 参数: {params}")
    # 返回 (成功?, 消息, 输出数据)
    return True, "执行完成", {}

# 4. 上报状态
client.report_state({"battery": 85.0, "status": "idle"})

# 5. 上报传感器
client.report_sensor("gps", "gps_main", {
    "latitude": 34.25, "longitude": 108.94, "altitude": 410.0
})

# 6. 保持运行
client.wait()
```

### API 概览

| 方法 | 说明 |
|------|------|
| `register()` | HTTP 注册设备，保存 Token |
| `connect_ws()` | 建立 WebSocket，自动认证+心跳 |
| `report_state(state_dict)` | 上报设备状态 |
| `report_sensor(type, id, data)` | 上报传感器数据 |
| `on_action(callback)` | 注册指令回调（可装饰器用） |
| `disconnect()` | 断开 WebSocket + 注销设备 |
| `wait()` | 阻塞直到连接断开 |

---

## Arduino/ESP32 客户端 (`arduino/aerialclaw_client.ino`)

适用于 ESP32 等资源受限的嵌入式设备。

### 依赖库（Arduino IDE 库管理器安装）

| 库名 | 作者 | 用途 |
|------|------|------|
| ArduinoJson | Benoit Blanchon | JSON 解析/生成 |
| WebSockets | Markus Sattler | WebSocket 客户端 |

### 配置步骤

1. 打开 `aerialclaw_client.ino`
2. 修改顶部配置区：
   ```cpp
   const char* WIFI_SSID     = "你的WiFi名";
   const char* WIFI_PASSWORD = "你的WiFi密码";
   const char* SERVER_HOST   = "192.168.1.100";  // 服务端 IP
   const int   SERVER_PORT   = 5001;
   const char* DEVICE_ID     = "esp32_01";        // 设备唯一 ID
   const char* DEVICE_TYPE   = "SENSOR";          // 设备类型
   ```
3. 在 `handleAction()` 函数中添加你的业务逻辑
4. 在 `loop()` 中添加传感器读取和上报

### 内置指令

| 指令 | 说明 |
|------|------|
| `blink` | 闪烁 LED（参数：`times`） |
| `get_status` | 返回当前状态 |
| `reset` | 重启设备 |

### 运行流程

```
上电
 ├── 连接 WiFi
 ├── POST /api/device/register → 获取 Token
 ├── WebSocket 连接 + device_connect 认证
 └── 主循环:
      ├── 每 5s 发送心跳
      ├── 每 10s 上报设备状态
      ├── 收到 device_action → 执行 → 回报结果
      └── (可扩展) 传感器读取 → 上报
```

---

## ROS2 桥接节点 (`ros2/aerialclaw_bridge.py`)

适用于运行 ROS2 Humble 的机器人（无人车、无人机、机械臂）。将 ROS2 话题生态与 AerialClaw AI 大脑无缝对接。

### 依赖

```bash
# ROS2 Humble（Ubuntu 22.04）
sudo apt install ros-humble-desktop

# Python 依赖
pip install requests "python-socketio[client]"
```

### 配置

通过环境变量覆盖默认值：

```bash
export AERIALCLAW_SERVER=http://192.168.1.100:5001
export AERIALCLAW_DEVICE_ID=my_ugv
export AERIALCLAW_DEVICE_TYPE=UGV
```

### 启动

```bash
# source ROS2 环境
source /opt/ros/humble/setup.bash

# 直接运行
python3 aerialclaw_bridge.py

# 或作为 ROS2 节点（需配置 package.xml + setup.py）
ros2 run my_robot aerialclaw_bridge
```

### 话题映射

| 方向 | ROS2 话题 | 消息类型 | AerialClaw 事件 |
|------|-----------|----------|-----------------|
| ↑ 上报 | `/odom` | `nav_msgs/Odometry` | `device_sensor` (odom) |
| ↑ 上报 | `/battery_state` | `sensor_msgs/BatteryState` | `device_sensor` (battery) |
| ↑ 上报 | `/camera/image_raw` | `sensor_msgs/Image` | `device_sensor` (camera) |
| ↓ 接收 | `/aerialclaw/action` | `std_msgs/String` (JSON) | `device_action` |

### 扩展示例：订阅 /aerialclaw/action

```python
# 在你的 ROS2 节点中订阅指令
import json
from std_msgs.msg import String

def action_callback(msg):
    cmd = json.loads(msg.data)
    print(f"收到指令: {cmd['action']} 参数: {cmd['params']}")
    # 调用 cmd_vel、MoveIt! 等执行

self.create_subscription(String, "/aerialclaw/action", action_callback, 10)
```

---

## 上报频率建议

| 数据类型 | 建议频率 | 说明 |
|----------|----------|------|
| 心跳 | 5 秒 | 固定，不可低于此值 |
| 设备状态 | 0.5~2 秒 | 根据动态性调整 |
| GPS/里程计 | 0.5~1 秒 | 避免网络过载 |
| IMU | 1~5 秒 | 按需上报 |
| 相机 | 0.5~1 秒 | 注意带宽 |
| LiDAR | 0.5~1 秒 | 注意带宽 |
| 电池 | 5~30 秒 | 变化缓慢 |

---

## 常见问题

**Q: 注册返回 409 DEVICE_ALREADY_EXISTS？**
A: 该 `device_id` 已注册。服务端重启后会清空，或修改 `device_id`。

**Q: WebSocket 认证失败？**
A: 确认先调用 `register()` 再调用 `connect_ws()`，Token 必须有效。

**Q: 心跳超时设备变为 offline？**
A: 服务端 10 秒无心跳则标记 offline。确保心跳线程正常运行（检查网络连通性）。

**Q: ESP32 连不上 WebSocket？**
A: 检查 `SERVER_HOST` 是否为局域网 IP（不是 `localhost`），以及服务端防火墙是否放行 5001 端口。

---

## 协议参考

完整协议文档请参阅 [`docs/DEVICE_PROTOCOL.md`](../docs/DEVICE_PROTOCOL.md)。
