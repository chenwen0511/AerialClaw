"""
core/failsafe.py — AerialClaw 断网应急策略

功能：
  - 心跳超时 → 悬停 → 等待 → 执行后续动作（返航/降落）
  - 网络断开 → 立即触发预设安全策略
  - 每台设备独立配置 FailsafePolicy
  - 与 DeviceManager 解耦，通过回调下发指令

使用方式：
    failsafe = Failsafe(device_manager=dm)
    failsafe.set_policy("drone_01", FailsafePolicy(
        hover_timeout=15.0,
        then="return_to_launch",
    ))
    # 在心跳监控线程中调用：
    failsafe.on_heartbeat_timeout("drone_01")
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Optional

from core.errors import DeviceNotFoundError
from core.logger import get_logger

logger = get_logger(__name__)

# 支持的后续动作
_VALID_THEN_ACTIONS = frozenset({"land", "return_to_launch", "hover"})
_VALID_LOW_BATTERY_ACTIONS = frozenset({"land", "return_to_launch"})


# ══════════════════════════════════════════════════════════════
#  FailsafePolicy
# ══════════════════════════════════════════════════════════════


@dataclass
class FailsafePolicy:
    """
    设备应急策略配置。

    Attributes:
        hover_timeout:       心跳超时后先悬停等待的秒数（0 表示跳过悬停直接执行 then）。
        then:                悬停超时后执行的动作：
                               - 'land'             : 原地降落
                               - 'return_to_launch' : 返回起飞点
                               - 'hover'            : 持续悬停，等人工干预
        min_battery_action:  低电量时的动作（'land' 或 'return_to_launch'）。
        min_battery_pct:     触发低电量动作的电量百分比阈值，默认 15。
        enabled:             False 时该设备的 failsafe 全部禁用（调试用）。
    """
    hover_timeout: float = 10.0
    then: str = "return_to_launch"
    min_battery_action: str = "land"
    min_battery_pct: float = 15.0
    enabled: bool = True

    def __post_init__(self) -> None:
        if self.then not in _VALID_THEN_ACTIONS:
            raise ValueError(
                f"FailsafePolicy.then 无效值 '{self.then}'，"
                f"可选: {sorted(_VALID_THEN_ACTIONS)}"
            )
        if self.min_battery_action not in _VALID_LOW_BATTERY_ACTIONS:
            raise ValueError(
                f"FailsafePolicy.min_battery_action 无效值 '{self.min_battery_action}'，"
                f"可选: {sorted(_VALID_LOW_BATTERY_ACTIONS)}"
            )
        if self.hover_timeout < 0:
            raise ValueError("hover_timeout 不能为负数")
        if not (0.0 <= self.min_battery_pct <= 100.0):
            raise ValueError("min_battery_pct 必须在 0~100 之间")


# ══════════════════════════════════════════════════════════════
#  FailsafeEvent — 内部事件记录
# ══════════════════════════════════════════════════════════════


@dataclass
class FailsafeEvent:
    """单次 failsafe 触发记录，用于审计和调试。"""
    device_id: str
    trigger: str          # 'heartbeat_timeout' | 'network_lost' | 'low_battery'
    action_taken: str     # 实际执行的动作
    timestamp: float = field(default_factory=time.time)
    note: str = ""


# ══════════════════════════════════════════════════════════════
#  Failsafe
# ══════════════════════════════════════════════════════════════


class Failsafe:
    """
    断网应急策略管理器。

    与 DeviceManager 解耦：通过注册 action_callback 下发指令，
    不直接依赖 DeviceManager（可在单元测试中单独使用）。

    Args:
        device_manager: 可选，传入后自动注册离线回调。
    """

    # 默认策略（未单独配置的设备使用此策略）
    DEFAULT_POLICY = FailsafePolicy()

    def __init__(self, device_manager=None) -> None:
        self._policies: Dict[str, FailsafePolicy] = {}
        self._events: list[FailsafeEvent] = []
        self._lock = threading.RLock()
        self._action_callback: Optional[Callable[[str, str, dict], None]] = None
        self._hover_timers: Dict[str, threading.Timer] = {}

        if device_manager is not None:
            device_manager.on_device_offline(self.on_heartbeat_timeout)
            logger.info("Failsafe 已绑定 DeviceManager 离线回调")

    # ── 策略管理 ─────────────────────────────────────────────

    def set_policy(self, device_id: str, policy: FailsafePolicy) -> None:
        """
        为指定设备配置 failsafe 策略。

        Args:
            device_id: 设备 ID。
            policy:    FailsafePolicy 实例。
        """
        with self._lock:
            self._policies[device_id] = policy
        logger.info(
            "Failsafe 策略已设置 [%s]: hover=%ss → %s, 低电量=%s%%→%s",
            device_id,
            policy.hover_timeout,
            policy.then,
            policy.min_battery_pct,
            policy.min_battery_action,
        )

    def get_policy(self, device_id: str) -> FailsafePolicy:
        """
        获取设备的 failsafe 策略，未配置则返回 DEFAULT_POLICY。

        Args:
            device_id: 设备 ID。

        Returns:
            FailsafePolicy 实例。
        """
        with self._lock:
            return self._policies.get(device_id, self.DEFAULT_POLICY)

    def remove_policy(self, device_id: str) -> None:
        """
        删除设备策略，恢复为默认策略。

        Args:
            device_id: 设备 ID。
        """
        with self._lock:
            removed = self._policies.pop(device_id, None)
        if removed:
            logger.info("Failsafe 策略已移除 [%s]，将使用默认策略", device_id)

    # ── 触发入口 ─────────────────────────────────────────────

    def on_heartbeat_timeout(self, device_id: str) -> None:
        """
        心跳超时回调。

        流程：悬停（hover_timeout 秒）→ 执行 policy.then 动作。
        若 hover_timeout == 0，直接执行后续动作。

        Args:
            device_id: 超时的设备 ID。
        """
        policy = self.get_policy(device_id)
        if not policy.enabled:
            logger.debug("Failsafe 已禁用 [%s]，跳过心跳超时处理", device_id)
            return

        logger.warning(
            "Failsafe 触发 [%s]: 心跳超时 → 悬停 %.1fs → %s",
            device_id, policy.hover_timeout, policy.then,
        )

        # Step 1: 悬停
        self._send_action(device_id, "hover", {})
        self._record_event(device_id, "heartbeat_timeout", "hover")

        if policy.hover_timeout <= 0:
            # 无等待，直接执行后续动作
            self._execute_then(device_id, policy)
            return

        # Step 2: 定时器到期后执行 then 动作
        with self._lock:
            # 取消旧定时器（防止重复触发）
            old = self._hover_timers.pop(device_id, None)
            if old:
                old.cancel()

            timer = threading.Timer(
                policy.hover_timeout,
                self._on_hover_expired,
                args=(device_id, policy),
            )
            timer.daemon = True
            timer.start()
            self._hover_timers[device_id] = timer

        logger.info(
            "Failsafe [%s]: 悬停等待 %.1fs，之后执行 '%s'",
            device_id, policy.hover_timeout, policy.then,
        )

    def on_network_lost(self, device_id: str) -> None:
        """
        网络断开回调。立即执行安全策略（跳过悬停等待）。

        Args:
            device_id: 断网的设备 ID。
        """
        policy = self.get_policy(device_id)
        if not policy.enabled:
            logger.debug("Failsafe 已禁用 [%s]，跳过网络断开处理", device_id)
            return

        logger.warning(
            "Failsafe 触发 [%s]: 网络断开 → 立即执行 '%s'",
            device_id, policy.then,
        )
        # 取消悬停定时器（如果有）
        self._cancel_hover_timer(device_id)
        self._execute_then(device_id, policy, trigger="network_lost")

    def on_low_battery(self, device_id: str, battery_pct: float) -> None:
        """
        低电量回调。当电量低于策略阈值时触发。

        Args:
            device_id:   设备 ID。
            battery_pct: 当前电量百分比（0~100）。
        """
        policy = self.get_policy(device_id)
        if not policy.enabled:
            return
        if battery_pct > policy.min_battery_pct:
            return

        logger.warning(
            "Failsafe 触发 [%s]: 低电量 %.1f%% (阈值 %.1f%%) → %s",
            device_id, battery_pct, policy.min_battery_pct, policy.min_battery_action,
        )
        self._cancel_hover_timer(device_id)
        self._send_action(device_id, policy.min_battery_action, {})
        self._record_event(
            device_id, "low_battery", policy.min_battery_action,
            note=f"battery={battery_pct:.1f}%",
        )

    def cancel(self, device_id: str) -> None:
        """
        取消设备的悬停等待定时器（设备重连后调用）。

        Args:
            device_id: 设备 ID。
        """
        self._cancel_hover_timer(device_id)
        logger.info("Failsafe [%s]: 悬停等待已取消（设备重连）", device_id)

    # ── 回调注册 ─────────────────────────────────────────────

    def set_action_callback(
        self,
        callback: Callable[[str, str, dict], None],
    ) -> None:
        """
        注册指令下发回调。

        Callback 签名：callback(device_id: str, action: str, params: dict) -> None

        Args:
            callback: 当 failsafe 需要下发指令时调用。
        """
        self._action_callback = callback

    # ── 事件历史 ─────────────────────────────────────────────

    def get_events(self, device_id: Optional[str] = None) -> list[FailsafeEvent]:
        """
        获取 failsafe 事件历史。

        Args:
            device_id: 过滤指定设备，None 返回所有。

        Returns:
            FailsafeEvent 列表（按时间升序）。
        """
        with self._lock:
            if device_id is None:
                return list(self._events)
            return [e for e in self._events if e.device_id == device_id]

    def clear_events(self) -> None:
        """清空事件历史。"""
        with self._lock:
            self._events.clear()

    # ── 内部方法 ─────────────────────────────────────────────

    def _on_hover_expired(self, device_id: str, policy: FailsafePolicy) -> None:
        """悬停定时器到期，执行 then 动作。"""
        with self._lock:
            self._hover_timers.pop(device_id, None)
        logger.info(
            "Failsafe [%s]: 悬停等待结束，执行 '%s'",
            device_id, policy.then,
        )
        self._execute_then(device_id, policy)

    def _execute_then(
        self,
        device_id: str,
        policy: FailsafePolicy,
        trigger: str = "heartbeat_timeout",
    ) -> None:
        """执行 policy.then 指定的动作并记录事件。"""
        self._send_action(device_id, policy.then, {})
        self._record_event(device_id, trigger, policy.then)

    def _send_action(self, device_id: str, action: str, params: dict) -> None:
        """通过回调下发指令，无回调时仅记录日志。"""
        if self._action_callback:
            try:
                self._action_callback(device_id, action, params)
                logger.info("Failsafe 指令下发 [%s]: %s %s", device_id, action, params)
            except Exception as e:
                logger.error(
                    "Failsafe 指令下发失败 [%s] %s: %s", device_id, action, e
                )
        else:
            logger.warning(
                "Failsafe [%s]: 无 action_callback，指令 '%s' 未实际下发",
                device_id, action,
            )

    def _cancel_hover_timer(self, device_id: str) -> None:
        """取消指定设备的悬停等待定时器。"""
        with self._lock:
            timer = self._hover_timers.pop(device_id, None)
        if timer:
            timer.cancel()

    def _record_event(
        self,
        device_id: str,
        trigger: str,
        action_taken: str,
        note: str = "",
    ) -> None:
        """记录一条 failsafe 事件（保留最近 1000 条）。"""
        event = FailsafeEvent(
            device_id=device_id,
            trigger=trigger,
            action_taken=action_taken,
            note=note,
        )
        with self._lock:
            self._events.append(event)
            if len(self._events) > 1000:
                self._events = self._events[-1000:]
