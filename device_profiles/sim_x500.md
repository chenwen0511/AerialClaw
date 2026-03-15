# X500 四旋翼无人机 (SITL) — 设备档案

> 创建时间: 2026-03-15 19:35
> 设备 ID: sim_x500

## 基本信息
- 型号: Holybro X500 / PX4 SITL sim_x500
- 类型: UAV
- 通信方式: mavlink

## 能力
- fly
- camera
- lidar
- hover

## 传感器
- gps
- imu
- camera_front
- camera_rear
- camera_left
- camera_right
- camera_down
- lidar_3d_360

## 物理限制
- max_speed: 10.0
- max_altitude: 120.0
- battery_capacity: 25min endurance
- weight: 2.0kg
- max_payload: 0.5kg

## 备注
PX4 SITL仿真环境，MAVLink端口14540。5路摄像头分辨率640x480（前后左右下）。3D激光雷达360度16线，最远30米。

## 技能绑定
> 由系统自动管理，设备接入时匹配，退出时挂起

## 经验记录
> 随任务执行自动积累
