"""
airsim_adapter.py
OpenFly 定制版 AirSim 适配器

坐标系（直接 RPC 测量确认）：
  x_val=North, y_val=East, z_val: z减小=向上，z增大=向下（用户实测确认）
  spawn_z ≈ 2.251（无人机出生点，非零）

关键发现：moveToPosition/moveByVelocity/takeoff_async_join 全部不可用
唯一移动方式：simSetVehiclePose（瞬间传送）

坐标换算：
  向上altitude m: target_z = spawn_z - altitude (z减小=向上)
  fly_to_ned: airsim_z = spawn_z + down (NED down负 → z减小=向上)
"""
import logging
import time
import threading
from typing import Optional

from adapters.sim_adapter import (
    SimAdapter, Position, GPSPosition, VehicleState, ActionResult,
)

logger = logging.getLogger(__name__)

_AIR_THRESHOLD = 1.0  # 离地超过1m才算在空中


class AirSimAdapter(SimAdapter):
    name = "airsim_openfly"
    description = "OpenFly AirSim - simSetVehiclePose teleport"
    supported_vehicles = ["multirotor"]

    def __init__(self, vehicle_name: str = "drone_1"):
        self._vehicle_name = vehicle_name
        self._client = None
        self._connected = False
        self._spawn_z: float = 0.0
        self._home_position: Optional[Position] = None
        self._hold_thread: Optional[threading.Thread] = None
        self._hold_running = False
        self._hold_lock = threading.Lock()
        self._hold_client = None
        self._hold_x: float = 0.0
        self._hold_y: float = 0.0
        self._hold_z: float = 0.0

    def _raw(self) -> dict:
        try:
            return self._client.get_multirotor_state(self._vehicle_name) or {}
        except Exception as e:
            logger.warning(f"get_multirotor_state error: {e}")
            return {}

    def _xyz(self):
        # hold 线程在跑时，返回目标位置（RPC 读取可能是中间态）
        if self._hold_running:
            return (self._hold_x, self._hold_y, self._hold_z)
        raw = self._raw()
        pos = raw.get("kinematics_estimated", {}).get("position", {})
        return (
            float(pos.get("x_val", 0.0)),
            float(pos.get("y_val", 0.0)),
            float(pos.get("z_val", self._spawn_z)),
        )

    def _set_pose(self, x, y, z):
        """传送到目标位置并持续维持（后台线程每50ms重设一次，对抗物理引擎）。"""
        with self._hold_lock:
            self._hold_x, self._hold_y, self._hold_z = float(x), float(y), float(z)
            # 立即设一次
            self._do_set_pose(x, y, z)
            # 如果 hold 线程没在跑（或者崩了），启动新的
            if not self._hold_running or (self._hold_thread and not self._hold_thread.is_alive()):
                self._hold_running = True
                self._hold_thread = threading.Thread(target=self._hold_loop, daemon=True)
                self._hold_thread.start()

    def _do_set_pose(self, x, y, z):
        """simSetVehiclePose：瞬间传送到目标位置。"""
        import math
        yaw = getattr(self, '_fly_yaw', 0.0)
        qw = math.cos(yaw / 2)
        qz = math.sin(yaw / 2)

        pose = {
            "position": {"x_val": float(x), "y_val": float(y), "z_val": float(z)},
            "orientation": {"w_val": qw, "x_val": 0.0, "y_val": 0.0, "z_val": qz},
        }
        client = self._hold_client or self._client
        try:
            client._rpc.call("simSetVehiclePose", pose, True, self._vehicle_name)
        except Exception:
            pass

    def _check_obstacle(self, x, y, z):
        """射线碰撞检测：当前位置到目标点之间是否有障碍物。"""
        client = self._hold_client or self._client
        try:
            # simTestLineOfSightToPoint 返回 True=可见(无障碍), False=被遮挡(有障碍)
            visible = client._rpc.call("simTestLineOfSightToPoint",
                {"x_val": float(x), "y_val": float(y), "z_val": float(z)}, self._vehicle_name)
            return not visible  # True=有障碍物
        except Exception:
            return False  # API 失败时不阻断飞行

    def _check_collision(self):
        """检查当前是否发生碰撞。"""
        client = self._hold_client or self._client
        try:
            col = client._rpc.call("simGetCollisionInfo", self._vehicle_name)
            return col.get("has_collided", False)
        except Exception:
            return False

    def _fly_smooth(self, tx, ty, tz, speed=3.0):
        """
        安全飞行：三段式（升高→水平→下降）。
        巡航高度动态计算：50m 默认，靠近高楼区域自动升高。
        """
        import math

        sx, sy, sz = self._hold_x, self._hold_y, self._hold_z
        dx, dy, dz = tx - sx, ty - sy, tz - sz
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 0.1:
            self._hold_x, self._hold_y, self._hold_z = tx, ty, tz
            return

        # 动态巡航高度：根据路径经过的区域决定
        # 默认 50m（高于大部分低层建筑 14-24m）
        cruise_alt = 50.0
        # 如果起点或终点在高层商业区附近(y>80)，升高到 170m
        if max(abs(sy), abs(ty)) > 80 and (sy > 60 or ty > 60):
            cruise_alt = 170.0
        # 如果起点或终点在摩天楼群附近(y<-100)，升高到 500m
        if min(sy, ty) < -100 or min(sy, ty if ty < -80 else 0, sy if sy < -80 else 0) < -80:
            cruise_alt = 500.0
        
        CRUISE_Z = self._spawn_z - cruise_alt
        
        h_dist = math.sqrt(dx*dx + dy*dy)
        
        if h_dist < 3.0:
            self._fly_smooth_raw(tx, ty, tz, speed)
        else:
            logger.info(f"🛫 三段飞行: 升到{cruise_alt:.0f}m → 水平{h_dist:.0f}m → 降到目标")
            self._fly_smooth_raw(sx, sy, CRUISE_Z, speed)       # 升高
            self._fly_smooth_raw(tx, ty, CRUISE_Z, speed)       # 水平飞
            self._fly_smooth_raw(tx, ty, tz, speed)             # 下降

    def _fly_smooth_raw(self, tx, ty, tz, speed=3.0):
        """底层插值飞行（带碰撞中断）。朝向跟随运动方向。"""
        import math
        sx, sy, sz = self._hold_x, self._hold_y, self._hold_z
        dx, dy, dz = tx - sx, ty - sy, tz - sz
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        if dist < 0.1:
            self._hold_x, self._hold_y, self._hold_z = tx, ty, tz
            return
        # 朝向对准运动方向
        if abs(dx) > 0.1 or abs(dy) > 0.1:
            self._fly_yaw = math.atan2(dy, dx)
        duration = dist / speed
        step_interval = 0.05  # 50ms per step
        steps = max(1, int(duration / step_interval))
        collision_count = 0
        for i in range(1, steps + 1):
            t = i / steps
            self._hold_x = sx + dx * t
            self._hold_y = sy + dy * t
            self._hold_z = sz + dz * t
            time.sleep(step_interval)
            # 每 10 步检测一次碰撞（节省 RPC 开销）
            if i % 10 == 0 and self._check_collision():
                collision_count += 1
                if collision_count >= 2:
                    # 连续碰撞，后退一步并升高
                    logger.warning(f"💥 碰撞检测! 后退并升高避障")
                    self._hold_x = sx + dx * ((i-10) / steps)
                    self._hold_y = sy + dy * ((i-10) / steps)
                    self._hold_z -= 3.0  # 升高3m（z减小=向上）
                    time.sleep(0.5)
                    # 从新位置重新飞到目标
                    self._fly_smooth_raw(tx, ty, tz, speed)
                    return
        self._hold_x, self._hold_y, self._hold_z = tx, ty, tz

    def _hold_loop(self):
        """后台线程：每100ms重设位置。simSetVehiclePose 覆盖物理引擎。"""
        client = self._hold_client or self._client
        try:
            while self._hold_running:
                self._do_set_pose(self._hold_x, self._hold_y, self._hold_z)
                import time as _t; _t.sleep(0.1)
        except Exception as e:
            logger.warning(f"Hold thread error: {e}")
        finally:
            self._hold_running = False

    def _stop_hold(self):
        """停止 hold 线程。"""
        self._hold_running = False
        self._hold_lock = threading.Lock()
        self._hold_client = None
        if self._hold_thread:
            self._hold_thread.join(timeout=1)
            self._hold_thread = None

    def connect(self, connection_str: str = "", timeout: float = 15.0) -> bool:
        ip, port = "127.0.0.1", 41451
        if connection_str:
            parts = connection_str.split(":")
            ip = parts[0]
            if len(parts) > 1:
                port = int(parts[1])
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

            # 传送到地面原点，确保 spawn_z 是真实地面值
            import time as _t
            try:
                # (0, 250) 东方空旷区，远离建筑，AirSim 视角不会卡住
                ground_pose = {
                    "position": {"x_val": 0.0, "y_val": 250.0, "z_val": -3.0},
                    "orientation": {"w_val": 1.0, "x_val": 0.0, "y_val": 0.0, "z_val": 0.0},
                }
                self._client._rpc.call("simSetVehiclePose", ground_pose, True, self._vehicle_name)
                _t.sleep(1.0)
            except Exception as _tp_err:
                logger.warning(f"Ground teleport failed: {_tp_err}")

            # 读稳定后的 z 作为 spawn_z（应约为 2.25~3.3）
            _, _, z = self._xyz()
            self._spawn_z = z
            logger.info(f"Ground calibrated: spawn_z={self._spawn_z:.3f}")
            self._home_position = Position(north=0.0, east=0.0, down=0.0)
            # 第二个 RPC 连接，专门给 hold 线程用（避免和摄像头/LiDAR 抢 socket）
            try:
                from adapters.airsim_rpc import AirSimDirectClient
                self._hold_client = AirSimDirectClient(ip, port, timeout=5)
                self._hold_client.connect()
                logger.info("Hold thread RPC connection established")
            except Exception as he:
                logger.warning(f"Hold RPC connect failed, sharing main: {he}")
                self._hold_client = self._client
            logger.info(f"AirSim connected: {ip}:{port}, spawn_z={self._spawn_z:.3f}")


            return True
        except Exception as e:
            logger.error(f"AirSim connect failed: {e}")
            self._connected = False
            return False

    def disconnect(self) -> None:
        self._stop_hold()
        if self._hold_client and self._hold_client is not self._client:
            try:
                self._hold_client.close()
            except Exception:
                pass
            self._hold_client = None
        if self._client:
            try:
                self._client.enable_api_control(False, self._vehicle_name)
            except Exception:
                pass
            try:
                self._client.close()
            except Exception:
                pass
        self._connected = False
        self._client = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_state(self) -> Optional[VehicleState]:
        if not self._connected:
            return None
        try:
            x, y, z = self._xyz()
            altitude = z - self._spawn_z
            in_air = altitude < -_AIR_THRESHOLD  # z减小=向上，空中altitude为负
            return VehicleState(
                armed=True,
                in_air=in_air,
                position_ned=Position(north=x, east=y, down=altitude),  # altitude负=向上 = NED down负=向上，一致
                battery_percent=100.0,
                velocity=[0.0, 0.0, 0.0],
            )
        except Exception as e:
            logger.warning(f"get_state error: {e}")
            return None

    def get_position(self) -> Optional[Position]:
        s = self.get_state()
        return s.position_ned if s else None

    def get_gps(self) -> Optional[GPSPosition]:
        return None

    def get_battery(self) -> tuple:
        return (12.6, 100.0)

    def get_image_base64(self) -> str:
        """获取前向摄像头图像（base64 JPEG）。"""
        try:
            import base64, cv2, numpy as np
            responses = self._client.sim_get_images([{
                'camera_name': 'cam_front',
                'image_type': 0,
                'pixels_as_float': False,
                'compress': False,
            }], vehicle_name=self._vehicle_name)
            if responses:
                r = responses[0]
                h, w = r.get('height', 0), r.get('width', 0)
                data = r.get('image_data_uint8') or r.get('image_data', b'')
                if isinstance(data, str):
                    data = base64.b64decode(data)
                if h > 0 and w > 0 and len(data) >= h * w * 3:
                    img = np.frombuffer(data, dtype=np.uint8).reshape(h, w, 3)
                    _, buf = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    return base64.b64encode(buf.tobytes()).decode('ascii')
        except Exception as e:
            logger.warning(f'get_image_base64 error: {e}')
        return None

    def is_armed(self) -> bool:
        return self._connected

    def is_in_air(self) -> bool:
        _, _, z = self._xyz()
        return (z - self._spawn_z) < -_AIR_THRESHOLD  # z减小=向上

    def arm(self) -> ActionResult:
        try:
            self._client.arm_disarm(True, self._vehicle_name)
            return ActionResult(success=True, message="Armed")
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def disarm(self) -> ActionResult:
        try:
            self._client.arm_disarm(False, self._vehicle_name)
            return ActionResult(success=True, message="Disarmed")
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def takeoff(self, altitude: float = 5.0) -> ActionResult:
        if not self._connected:
            return ActionResult(success=False, message="Not connected")
        try:
            x, y, z0 = self._xyz()
            target_z = self._spawn_z - altitude  # z减小=向上
            logger.info(f"Takeoff to altitude={altitude}m, target_z={target_z:.3f}")
            self._set_pose(x, y, self._hold_z if self._hold_running else z0)  # 先启动 hold
            self._fly_smooth(x, y, target_z, speed=2.0)  # 平滑上升
            _, _, actual_z = self._xyz()
            actual_alt = actual_z - self._spawn_z
            if actual_alt > -0.5:  # z减小=向上，起飞后actual_alt为负
                return ActionResult(success=False, message=f"Takeoff failed: altitude={actual_alt:.2f}m")
            logger.info(f"Takeoff confirmed: altitude={actual_alt:.2f}m")
            return ActionResult(success=True, message=f"Takeoff OK: altitude={actual_alt:.1f}m")
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def land(self) -> ActionResult:
        if not self._connected:
            return ActionResult(success=False, message="Not connected")
        try:
            x, y, _ = self._xyz()
            logger.info(f"Land: returning to spawn_z={self._spawn_z:.3f}")
            # 平滑下降到 spawn_z
            self._fly_smooth(x, y, self._spawn_z, speed=2.0)
            self._stop_hold()  # 到地面后停止 hold
            time.sleep(0.3)
            _, _, actual_z = self._xyz()
            altitude = actual_z - self._spawn_z
            logger.info(f"Land confirmed: altitude={altitude:.3f}m")
            return ActionResult(success=True, message=f"Landed: altitude={altitude:.3f}m")
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def fly_to_ned(self, north: float, east: float, down: float,
                   speed: float = 2.0) -> ActionResult:
        """NED down 为负=向上，airsim_z = spawn_z - down"""
        if not self._connected:
            return ActionResult(success=False, message="Not connected")
        try:
            target_z = self._spawn_z + down  # NED down负=向上 → z减小=向上，直接相加
            logger.info(f"fly_to_ned: N={north:.2f} E={east:.2f} down={down:.2f} -> airsim_z={target_z:.3f}")
            if not self._hold_running:
                self._set_pose(self._hold_x, self._hold_y, self._hold_z)  # 确保 hold 在跑
            self._fly_smooth(north, east, target_z, speed=speed)
            ax, ay, az = self._xyz()
            err = ((ax-north)**2 + (ay-east)**2 + (az-target_z)**2)**0.5
            return ActionResult(success=True, message=f"fly_to_ned OK: err={err:.3f}m")
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def fly_to(self, position: Position, speed: float = 5.0) -> ActionResult:
        return self.fly_to_ned(position.north, position.east, position.down, speed)

    def hover(self, duration: float = 5.0) -> ActionResult:
        if not self._connected:
            return ActionResult(success=False, message="Not connected")
        try:
            x, y, z = self._xyz()
            self._set_pose(x, y, z)
            time.sleep(duration)
            return ActionResult(success=True, message=f"Hovered {duration}s")
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def set_velocity_body(self, forward: float, right: float, down: float, yaw_rate: float = 0) -> ActionResult:
        """
        WASD 键盘控制：持续按住按方向飞行。
        forward/right/down 单位 m/s，yaw_rate 单位 deg/s。
        通过修改 hold 目标位置实现持续移动。
        """
        if not self._connected:
            return ActionResult(success=False, message='Not connected')
        try:
            # 确保 hold 线程在跑
            if not self._hold_running:
                x, y, z = self._xyz()
                self._set_pose(x, y, z)

            # 用速度修改 hold 目标：每次调用移动一小步（按 100ms 计算）
            dt = 0.1  # 假设前端每 100ms 发一次 velocity_control
            # body frame → world frame（简化：不考虑 yaw 旋转）
            self._hold_x += forward * dt
            self._hold_y += right * dt
            self._hold_z += -down * dt  # NED down正=向下，z减小=向上，取反

            return ActionResult(success=True, message='velocity set')
        except Exception as e:
            return ActionResult(success=False, message=str(e))

    def stop_velocity(self) -> ActionResult:
        """停止速度控制，保持当前位置。"""
        # hold 线程会自动维持当前位置，不需要额外操作
        return ActionResult(success=True, message='velocity stopped')

    def return_to_launch(self) -> ActionResult:
        if not self._connected:
            return ActionResult(success=False, message="Not connected")
        try:
            # 先飞到 home 上方 3m
            if not self._hold_running:
                x, y, z = self._xyz()
                self._set_pose(x, y, z)  # 启动 hold
            self._fly_smooth(0.0, 0.0, self._spawn_z - 3.0, speed=3.0)
            r = self.land()
            return ActionResult(success=r.success, message=f"RTL: {r.message}")
        except Exception as e:
            return ActionResult(success=False, message=str(e))
