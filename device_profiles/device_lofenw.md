# X500 SITL — 设备档案

> 创建时间: 2026-03-15 20:52
> 设备 ID: device_lofenw

## 基本信息
- 型号: Holybro X500 (PX4 SITL)
- 类型: UAV
- 通信方式: mavlink

## 能力
- fly
- camera
- lidar

## 传感器
- gps
- imu
- camera_front
- camera_rear
- camera_left
- camera_right
- camera_down
- lidar_2d

## 物理限制
- max_speed: 12.0
- max_altitude: 120.0
- battery_capacity: simulated
- weight: 2.0kg
- max_payload: None

## 备注
PX4 SITL仿真环境，MAVSDK通过UDP 14540连接。激光雷达扫描角度未确认，默认360°。电池为仿真电池，无真实容量限制。

## 技能绑定
> 由系统自动管理，设备接入时匹配，退出时挂起

## 经验记录
> 随任务执行自动积累
