"""
core/safety/flight_envelope.py — 安全包线

硬编码物理限制，不可绕过。
LLM 改不了，用户关不掉。
这是安全体系的最后一道防线。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from core.errors import SafetyViolationError
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SafetyResult:
    """安全校验结果"""
    safe: bool
    reason: str = ""
    override_action: Optional[str] = None  # 强制执行的替代动作


class FlightEnvelope:
    """
    物理安全包线。

    硬编码限制，在所有指令执行前校验。
    任何超出安全范围的操作都会被拦截或降级。

    这些值在代码中定义，不从配置文件加载，
    确保 LLM 和用户都无法绕过。
    """

    # ── 硬编码限制（不可修改）──────────────────────────────

    MAX_SPEED: float = 10.0          # m/s 最大速度
    MAX_ALTITUDE: float = 120.0      # m   最大高度
    MIN_ALTITUDE: float = 0.3        # m   最低安全高度
    MAX_DISTANCE: float = 500.0      # m   最远距离
    MIN_BATTERY: float = 15.0        # %   低电量返航阈值
    CRITICAL_BATTERY: float = 5.0    # %   极低电量强制降落
    HEARTBEAT_TIMEOUT: int = 10      # s   心跳超时
    MAX_TILT_ANGLE: float = 35.0     # deg 最大倾斜角

    def validate(
        self,
        action: str,
        params: Dict[str, Any],
        device_state: Dict[str, Any],
    ) -> SafetyResult:
        """
        校验指令是否在安全包线内。

        Args:
            action: 指令名称
            params: 指令参数
            device_state: 设备当前状态

        Returns:
            SafetyResult: 校验结果
        """
        # 电量检查（优先级最高）
        battery = device_state.get("battery", 100)
        battery_result = self._check_battery(battery, action)
        if not battery_result.safe:
            return battery_result

        # 按动作类型分发校验
        validators = {
            "takeoff": self._validate_takeoff,
            "fly_to": self._validate_fly_to,
            "fly_relative": self._validate_fly_relative,
            "change_altitude": self._validate_altitude,
            "velocity_control": self._validate_velocity,
        }

        validator = validators.get(action)
        if validator:
            return validator(params, device_state)

        return SafetyResult(safe=True)

    def _check_battery(self, battery: float, action: str) -> SafetyResult:
        """电量安全检查"""
        if battery <= self.CRITICAL_BATTERY:
            logger.critical(
                "极低电量 %.1f%% — 强制降落", battery,
            )
            return SafetyResult(
                safe=False,
                reason=f"极低电量 ({battery}%)，强制降落",
                override_action="land",
            )

        if battery <= self.MIN_BATTERY and action not in ("land", "return_to_launch"):
            logger.warning(
                "低电量 %.1f%% — 强制返航", battery,
            )
            return SafetyResult(
                safe=False,
                reason=f"低电量 ({battery}%)，必须返航或降落",
                override_action="return_to_launch",
            )

        return SafetyResult(safe=True)

    def _validate_takeoff(
        self, params: Dict[str, Any], state: Dict[str, Any]
    ) -> SafetyResult:
        """起飞校验"""
        alt = params.get("altitude", 5.0)
        if alt > self.MAX_ALTITUDE:
            return SafetyResult(
                safe=False,
                reason=f"起飞高度 {alt}m 超出限制 ({self.MAX_ALTITUDE}m)",
            )
        if alt < self.MIN_ALTITUDE:
            return SafetyResult(
                safe=False,
                reason=f"起飞高度 {alt}m 低于最小安全高度 ({self.MIN_ALTITUDE}m)",
            )
        return SafetyResult(safe=True)

    def _validate_fly_to(
        self, params: Dict[str, Any], state: Dict[str, Any]
    ) -> SafetyResult:
        """飞行目标校验"""
        # 高度检查
        down = params.get("down", 0)
        altitude = -down if down != 0 else params.get("altitude", 0)
        if altitude > self.MAX_ALTITUDE:
            return SafetyResult(
                safe=False,
                reason=f"目标高度 {altitude}m 超出限制 ({self.MAX_ALTITUDE}m)",
            )

        # 距离检查
        north = params.get("north", 0)
        east = params.get("east", 0)
        distance = (north ** 2 + east ** 2) ** 0.5
        if distance > self.MAX_DISTANCE:
            return SafetyResult(
                safe=False,
                reason=f"目标距离 {distance:.0f}m 超出限制 ({self.MAX_DISTANCE}m)",
            )

        return SafetyResult(safe=True)

    def _validate_fly_relative(
        self, params: Dict[str, Any], state: Dict[str, Any]
    ) -> SafetyResult:
        """相对飞行校验"""
        # 计算目标绝对位置
        pos = state.get("position", {})
        if isinstance(pos, list) and len(pos) >= 3:
            cur_n, cur_e, cur_alt = pos[0], pos[1], -pos[2]
        elif isinstance(pos, dict):
            cur_n = pos.get("north", 0)
            cur_e = pos.get("east", 0)
            cur_alt = -pos.get("down", 0)
        else:
            cur_n = cur_e = cur_alt = 0

        delta_n = params.get("north", params.get("forward", 0))
        delta_e = params.get("east", params.get("right", 0))
        delta_alt = params.get("up", -params.get("down", 0))

        target_alt = cur_alt + delta_alt
        if target_alt > self.MAX_ALTITUDE:
            return SafetyResult(
                safe=False,
                reason=f"目标高度 {target_alt:.1f}m 超出限制",
            )

        target_n = cur_n + delta_n
        target_e = cur_e + delta_e
        distance = (target_n ** 2 + target_e ** 2) ** 0.5
        if distance > self.MAX_DISTANCE:
            return SafetyResult(
                safe=False,
                reason=f"目标距离 {distance:.0f}m 超出限制",
            )

        return SafetyResult(safe=True)

    def _validate_altitude(
        self, params: Dict[str, Any], state: Dict[str, Any]
    ) -> SafetyResult:
        """高度变更校验"""
        alt = params.get("altitude", 0)
        if alt > self.MAX_ALTITUDE:
            return SafetyResult(
                safe=False,
                reason=f"目标高度 {alt}m 超出限制 ({self.MAX_ALTITUDE}m)",
            )
        if alt < self.MIN_ALTITUDE:
            return SafetyResult(
                safe=False,
                reason=f"目标高度 {alt}m 低于安全高度 ({self.MIN_ALTITUDE}m)",
            )
        return SafetyResult(safe=True)

    def _validate_velocity(
        self, params: Dict[str, Any], state: Dict[str, Any]
    ) -> SafetyResult:
        """速度校验"""
        fwd = abs(params.get("forward", 0))
        right = abs(params.get("right", 0))
        down = abs(params.get("down", 0))
        speed = (fwd ** 2 + right ** 2 + down ** 2) ** 0.5

        if speed > self.MAX_SPEED:
            return SafetyResult(
                safe=False,
                reason=f"速度 {speed:.1f}m/s 超出限制 ({self.MAX_SPEED}m/s)",
            )

        return SafetyResult(safe=True)
