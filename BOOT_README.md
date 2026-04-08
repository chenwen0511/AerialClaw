# AerialClaw 启动与问题定位（PX4 + Gazebo）

本文说明：**从零启动仿真与控制台**、**环境与进程如何对齐**、以及 **网页无相机 / 传感器桥接失败** 时如何系统排查。

---

## 一、整体架构（你要心里有数）

| 组件 | 作用 |
|------|------|
| **Gazebo Sim** | 物理世界、传感器（相机/IMU/GPS 等） |
| **PX4 SITL** | 飞控软件在环 |
| **Micro XRCE-DDS Agent** | PX4 与 DDS 相关通信 |
| **server.py** | Web API、WebSocket、**Gazebo 传感器桥接**（相机推流到前端） |
| **浏览器 :5001** | 控制台 UI |

数据流要点：**相机画面**来自 Gazebo 的 **`.../sensor/.../image` 话题**，由 **系统 Python + `gz.transport13`** 订阅后编码，经 Socket.IO 推到浏览器。

---

## 二、推荐启动顺序

### 1. 一次性环境准备（新机或少见）

```bash
cd /path/to/AerialClaw
./scripts/setup_px4.sh
```

### 2. 终端 A：启动仿真

**必须**与下文 **server 使用相同的** `GZ_PARTITION`，且 **需要网页多路相机** 时请使用带相机的机型（如 `x500_lidar_2d_cam`），不要用裸 `x500`（无相机话题）。

```bash
cd /path/to/AerialClaw
export GZ_PARTITION=aerialclaw
./scripts/start_sim.sh urban_rescue x500_lidar_2d_cam
```

- 第一个参数：`world`（如 `default`、`urban_rescue`）
- 第二个参数：**PX4/Gazebo 机型**（要出图请用 `x500_lidar_2d_cam` 或项目 `sim/models` 中配套模型）

日志：`/tmp/aerialclaw_gz.log`、`/tmp/aerialclaw_px4.log`、`/tmp/aerialclaw_dds.log`

### 3. 终端 B：启动 Web 服务（务必用系统 Python）

**不要用 Miniconda 的 Python 跑带 Gazebo 相机的 server**：apt 的 `python3-gz-transport13` 仅适配 **`/usr/bin/python3`**（Ubuntu 22.04 上多为 3.10），Conda 3.11+ / 3.13 会导致 **传感器桥接无法启动**。

首次为系统 Python 安装依赖：

```bash
cd /path/to/AerialClaw
/usr/bin/python3 -m pip install --user -r requirements.txt
```

启动：

```bash
cd /path/to/AerialClaw
export GZ_PARTITION=aerialclaw
export PX4_GZ_WORLD=default
export PX4_SIM_MODEL=x500_lidar_2d_cam
chmod +x ./scripts/run_server_px4.sh   # 仅需一次
./scripts/run_server_px4.sh
```

浏览器打开：**http://127.0.0.1:5001** → 点击 **初始化**，等待约 **15～20 秒**（传感器桥接在初始化后延迟启动）。

---

## 三、环境变量对齐表（不一致必出怪问题）

| 变量 | 含义 | 建议 |
|------|------|------|
| `GZ_PARTITION` | Gazebo Transport 分区 | 仿真终端与 **server 终端必须完全相同**（如 `aerialclaw`） |
| `PX4_GZ_WORLD` | 世界名 | 与 `start_sim.sh` **第一个参数**一致 |
| `PX4_SIM_MODEL` | 机型（无前缀 `_0`） | 与 `start_sim.sh` **第二个参数**一致；要相机用 `x500_lidar_2d_cam` |

---

## 四、问题定位（按顺序做）

### 1. 仿真里到底有没有相机话题？

在 **仿真运行中**、且 **`export GZ_PARTITION` 与启动仿真时一致**：

```bash
export GZ_PARTITION=aerialclaw
gz topic -l | grep -iE 'image|camera'
```

- **无任何 `.../image`**：常见原因是当前 spawn 的是 **`x500_0`**（无相机），或纯无头且无渲染导致相机未发布。请用 **`x500_lidar_2d_cam` 重启仿真**。
- **有 `.../cam_*/image`**：Gazebo 侧正常，继续查 server。

### 2. 模型名是否仍为 `x500_0`？

```bash
gz topic -l | grep '/model/' | head -20
```

若只有 `x500_0` 而无 `x500_lidar_2d_cam_0`，网页 **必然 NO SIGNAL**（与 server 无关）。

### 3. 传感器桥接是否启动？

```bash
curl -s http://127.0.0.1:5001/api/sensor/status | python3 -m json.tool
```

- `"running": false` 且 `"传感器桥接未启动"`：多为 **未用系统 Python 跑 server**（Conda/venv 无 `gz.transport`）、**仿真未起 / `GZ_PARTITION` 不一致**、或 **桥接线程尚未跑完约 15s 延迟**（PX4 模式在 MAVSDK 连接后会自动拉桥接）。
- 确认服务进程：

```bash
curl -sI http://127.0.0.1:5001/ | grep -i Server
```

若显示 **Python/3.13** 等 Conda 版本，请改为 **`./scripts/run_server_px4.sh`**。

### 4. 相机 HTTP 是否可用？

```bash
curl -I http://127.0.0.1:5001/api/sensor/camera
```

**200** 且 `Content-Type: image/jpeg` 为正常；**503** 表示桥接无帧或适配器无图。

若日志出现 **`超时未收到图像: .../cam_right/...`**：多为 **该 topic 尚未发布**（仿真刚起、无头/无渲染未出图、`GZ_PARTITION` 与仿真不一致）或 **首帧较慢**。桥接已用 **持久订阅 + 缓存** 降低丢帧；仍缺图时可加大首帧等待：`export GZ_CAMERA_TIMEOUT_MS=15000` 后重启 server。请在仿真运行时执行 `gz topic -l | grep cam_right` 确认该路径存在。

### 5. 系统 Python 能否加载 Gazebo 绑定？

```bash
/usr/bin/python3 -c "import gz.transport13; from gz.msgs10.image_pb2 import Image; print('ok')"
```

失败则：

```bash
sudo apt install python3-gz-transport13 python3-gz-msgs10
```

### 6. 日志

- 应用：`logs/YYYY-MM-DD.log`
- 仿真：`/tmp/aerialclaw_*.log`

### 7. `takeoff` / `arm` 报 `COMMAND_DENIED`（Command Denied）

多为 **PX4 预解锁检查未通过**（EKF/GPS/home 未就绪、或 SITL 要求 GPS 才能解锁）。

- **先等**：仿真与 MAVSDK 连接后 **再等 10～30 秒** 再点起飞；适配器会 **等待 `health.is_armable`** 并多次重试 `arm()`。
- **一键放宽（仅 SITL）**：启动 server 前执行  
  `export PX4_SITL_RELAX_ARM=1`  
  会在起飞/解锁前尝试设置 `COM_ARM_WO_GPS=1`（允许无 GPS 解锁）。
- **手动**：在 PX4 shell / QGC 参数中：`param set COM_ARM_WO_GPS 1`，必要时查看 `listener vehicle_status` / 预解锁失败原因。

---

## 五、Micro XRCE-DDS Agent 与 Gazebo 常见告警

- **`MotorFailurePlugin` 找不到**：多为可选插件缺失，多数 **不影响**基本 SITL。
- **`gz_frame_id` SDF Warning**：Gazebo 扩展字段提示，一般 **可忽略**。
- **EGL / 黑屏 / 无图**：有桌面时尽量保证 **DISPLAY** 与 **GPU/软件渲染** 可用；纯 `-s` 无头在部分机器上 **相机不发布**，需带渲染或软件 GL 试错。

---

## 六、一键自检清单

- [ ] `gz topic -l` 中出现 **`x500_lidar_2d_cam_0`**（或你选用的带相机模型）及 **`.../image`**
- [ ] 两终端 **`GZ_PARTITION` 一致**
- [ ] **`PX4_GZ_WORLD` / `PX4_SIM_MODEL`** 与 `start_sim` 一致
- [ ] **`/usr/bin/python3`** 可 `import gz.transport13`
- [ ] 使用 **`./scripts/run_server_px4.sh`** 或等价方式启动 server
- [ ] 浏览器已 **初始化** 并等待传感器桥接延迟结束
- [ ] **`/api/sensor/status`** 中 `running: true`

---

更完整的仿真说明见：`docs/SIMULATION_SETUP.md`、`README_CN.md`。
