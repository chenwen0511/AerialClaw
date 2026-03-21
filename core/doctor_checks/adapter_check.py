"""
core/doctor_checks/adapter_check.py — 适配器 & 硬技能联通检查

检查项:
    1. AdapterStatusCheck  — 适配器是否初始化、连接、类型
    2. AdapterStateCheck   — 能否获取飞行器状态 (get_state)
    3. HardSkillCheck      — 硬技能注册表是否可用、能否匹配适配器
    4. AirSimConnectionCheck — AirSim 专项: TCP 41451 探活 + API ping
"""

from __future__ import annotations

import socket
from core.doctor import HealthCheck, CheckResult


class AdapterStatusCheck(HealthCheck):
    """检查当前适配器是否已初始化并连接"""
    name = "适配器状态"
    category = "adapter"

    def check(self) -> CheckResult:
        try:
            from adapters.adapter_manager import get_adapter, list_adapters
            adapter = get_adapter()

            registered = list_adapters()
            reg_names = [a["name"] for a in registered]

            if adapter is None:
                return self._warn(
                    f"适配器未初始化 (已注册: {', '.join(reg_names)})",
                    "调用 init_adapter('airsim') 或 init_adapter('px4') 初始化"
                )

            name = getattr(adapter, 'name', 'unknown')
            desc = getattr(adapter, 'description', '')

            # 检查连接状态
            connected = False
            try:
                connected = adapter.is_connected
                if callable(connected):
                    connected = connected()
            except Exception:
                pass

            if connected:
                return self._ok(f"{name} 已连接 ({desc})")
            else:
                return self._warn(
                    f"{name} 已初始化但未连接",
                    f"检查仿真环境是否运行, 或调用 adapter.connect()"
                )
        except Exception as e:
            return self._fail(f"适配器检查异常: {str(e)[:80]}")


class AdapterStateCheck(HealthCheck):
    """检查能否通过适配器获取飞行器状态"""
    name = "飞行器状态"
    category = "adapter"

    def check(self) -> CheckResult:
        try:
            from adapters.adapter_manager import get_adapter
            adapter = get_adapter()

            if adapter is None:
                return self._warn("适配器未初始化, 跳过状态检查")

            # 尝试获取状态
            state = adapter.get_state()
            if state is None:
                return self._warn(
                    "get_state() 返回 None",
                    "检查仿真环境是否正常运行"
                )

            # 读取关键状态字段
            info_parts = []
            if hasattr(state, 'armed'):
                info_parts.append(f"armed={state.armed}")
            if hasattr(state, 'in_air'):
                info_parts.append(f"in_air={state.in_air}")
            if hasattr(state, 'position_ned') and state.position_ned:
                p = state.position_ned
                info_parts.append(f"NED=({p.north:.1f},{p.east:.1f},{p.down:.1f})")

            return self._ok(f"可用 ({', '.join(info_parts)})")
        except Exception as e:
            return self._fail(
                f"状态获取失败: {str(e)[:80]}",
                "检查仿真连接或适配器实现"
            )


class HardSkillCheck(HealthCheck):
    """检查硬技能是否可用"""
    name = "硬技能"
    category = "adapter"

    def check(self) -> CheckResult:
        try:
            from adapters.adapter_manager import get_adapter

            # 检查硬技能导入
            from skills.motor_skills import (
                Takeoff, Land, FlyTo, Hover, GetPosition, GetBattery, ReturnToLaunch
            )

            skill_classes = [Takeoff, Land, FlyTo, Hover, GetPosition, GetBattery, ReturnToLaunch]
            skill_names = [s.name for s in skill_classes]

            adapter = get_adapter()
            if adapter is None:
                return self._warn(
                    f"{len(skill_classes)} 个硬技能已注册, 但无适配器",
                    "初始化适配器后硬技能才能执行"
                )

            # 验证适配器有硬技能需要的关键方法
            adapter_name = getattr(adapter, 'name', 'unknown')
            required_methods = ['takeoff', 'land', 'fly_to_ned', 'hover', 'get_position', 'get_battery']
            missing = [m for m in required_methods if not hasattr(adapter, m)]

            if missing:
                return self._warn(
                    f"适配器 {adapter_name} 缺少方法: {', '.join(missing)}",
                    "检查适配器实现是否完整"
                )

            return self._ok(f"{len(skill_classes)} 个技能就绪, 适配器: {adapter_name}")
        except ImportError as e:
            return self._fail(f"硬技能导入失败: {str(e)[:80]}")
        except Exception as e:
            return self._fail(f"硬技能检查异常: {str(e)[:80]}")


class HardSkillDryRunCheck(HealthCheck):
    """端到端硬技能 dry run: takeoff → get_position → hover → fly_to → land
    
    优先级:
        1. 已初始化且已连接的适配器 → 直接用
        2. AirSim TCP 41451 可达 → 临时连接 AirSim 做真实 dry run
        3. 都没有 → 用 mock 验证代码链路
    """
    name = "硬技能联通"
    category = "adapter"

    def _try_get_live_adapter(self):
        """尝试获取已连接的适配器，或临时连一个。"""
        from adapters.adapter_manager import get_adapter
        adapter = get_adapter()
        temp = False

        if adapter is not None:
            connected = adapter.is_connected
            if callable(connected):
                connected = connected()
            if connected:
                return adapter, False  # 已有且已连接

        # 尝试临时连接 AirSim
        try:
            s = socket.create_connection(("127.0.0.1", 41451), timeout=2)
            s.close()
            # AirSim 可达，临时创建 adapter
            from adapters.airsim_adapter import AirSimAdapter
            adapter = AirSimAdapter()
            ok = adapter.connect(timeout=10)
            if ok:
                return adapter, True
        except Exception:
            pass

        # fallback: mock
        from adapters.mock_adapter import MockAdapter
        adapter = MockAdapter()
        adapter.connect()
        return adapter, True

    def check(self) -> CheckResult:
        try:
            adapter, is_temp = self._try_get_live_adapter()
            adapter_name = getattr(adapter, 'name', 'unknown')
            errors = []

            # 1. takeoff
            r = adapter.takeoff(3.0)
            if not r.success:
                errors.append(f"takeoff: {r.message}")

            # 2. get_position
            try:
                pos = adapter.get_position()
                if pos is None:
                    errors.append("get_position: 返回 None")
            except Exception as e:
                errors.append(f"get_position: {str(e)[:60]}")

            # 3. hover
            r = adapter.hover(0.5)
            if not r.success:
                errors.append(f"hover: {r.message}")

            # 4. fly_to_ned
            r = adapter.fly_to_ned(1.0, 0.0, -3.0, speed=2.0)
            if not r.success:
                errors.append(f"fly_to_ned: {r.message}")

            # 5. land
            r = adapter.land()
            if not r.success:
                errors.append(f"land: {r.message}")

            # 清理临时 adapter
            if is_temp:
                try:
                    adapter.disconnect()
                except Exception:
                    pass

            if errors:
                return self._warn(
                    f"{len(errors)} 个技能失败 ({adapter_name}): {'; '.join(errors[:2])}",
                    "检查适配器方法实现或仿真环境状态"
                )

            return self._ok(f"5/5 技能通过 [{adapter_name}]: takeoff→position→hover→fly_to→land")

        except ImportError as e:
            return self._fail(f"导入失败: {str(e)[:80]}")
        except Exception as e:
            return self._fail(f"dry run 异常: {str(e)[:80]}")


class AirSimConnectionCheck(HealthCheck):
    """AirSim 专项: TCP 探活 + API 级检查"""
    name = "AirSim"
    category = "connection"

    def check(self) -> CheckResult:
        # 1) TCP 探活 41451
        ip, port = "127.0.0.1", 41451
        tcp_ok = False
        try:
            s = socket.create_connection((ip, port), timeout=2)
            s.close()
            tcp_ok = True
        except Exception:
            pass

        if not tcp_ok:
            return self._warn(
                "AirSim 未检测到 (TCP 41451 不可达)",
                "启动 AirSim: ./AirSimExe 或 UE5 项目运行"
            )

        # 2) 如果当前适配器是 AirSim, 检查 API 级连接
        try:
            from adapters.adapter_manager import get_adapter
            adapter = get_adapter()
            if adapter and getattr(adapter, 'name', '') == 'airsim_simpleflight':
                connected = adapter.is_connected
                if callable(connected):
                    connected = connected()
                if connected:
                    return self._ok("TCP + API 均正常")
                return self._warn("TCP 可达但 API 未连接", "调用 init_adapter('airsim')")
        except Exception:
            pass

        return self._ok(f"TCP {ip}:{port} 可达")
