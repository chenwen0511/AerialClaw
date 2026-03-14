"""
core/safety/approval.py — 分级审批系统

根据安全等级定义审批规则：
  - auto:    自动通过（低风险操作）
  - confirm: 需要人工确认（中风险操作）
  - deny:    永远禁止（高风险操作）
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

from core.errors import ApprovalRequiredError, CommandBlockedError
from core.logger import get_logger
from core.safety.config import SafetyConfig

logger = get_logger(__name__)


class ApprovalLevel(Enum):
    """审批等级"""
    AUTO = "auto"         # 自动通过
    CONFIRM = "confirm"   # 需要人工确认
    DENY = "deny"         # 永远禁止


@dataclass
class ApprovalRequest:
    """审批请求"""
    request_id: str
    action: str
    params: Dict[str, Any]
    device_id: str
    level: ApprovalLevel
    created_at: float
    status: str = "pending"   # pending / approved / rejected / timeout
    reviewed_by: str = ""


@dataclass
class ApprovalResult:
    """审批结果"""
    approved: bool
    level: ApprovalLevel
    reason: str = ""
    request_id: str = ""


class ApprovalManager:
    """
    分级审批管理器。

    根据当前安全等级和操作类型决定审批级别。
    支持同步等待人工确认（WebSocket 推送审批请求到前端）。
    """

    DEFAULT_TIMEOUT = 60.0  # 审批超时时间（秒）

    def __init__(self, config: SafetyConfig) -> None:
        self._config = config
        self._pending: Dict[str, ApprovalRequest] = {}
        self._events: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._on_approval_request: Optional[Callable] = None

    def check(self, action: str) -> ApprovalLevel:
        """
        检查操作的审批等级。

        Args:
            action: 操作名称

        Returns:
            ApprovalLevel: 审批等级
        """
        levels = self._config.approval_levels
        action_lower = action.lower()

        # deny 列表
        deny_list = [a.lower() for a in levels.get("deny", [])]
        if action_lower in deny_list:
            return ApprovalLevel.DENY

        # auto 列表
        auto_list = [a.lower() for a in levels.get("auto", [])]
        if action_lower in auto_list:
            return ApprovalLevel.AUTO

        # confirm 列表
        confirm_list = [a.lower() for a in levels.get("confirm", [])]
        if action_lower in confirm_list:
            return ApprovalLevel.CONFIRM

        # 默认需要确认
        return ApprovalLevel.CONFIRM

    def request_approval(
        self,
        action: str,
        params: Dict[str, Any],
        device_id: str = "",
        timeout: float = None,
    ) -> ApprovalResult:
        """
        发起审批请求。

        对于 AUTO 级别直接返回通过。
        对于 DENY 级别直接拒绝。
        对于 CONFIRM 级别推送请求到前端，等待人工确认。

        Args:
            action: 操作名称
            params: 操作参数
            device_id: 设备 ID
            timeout: 超时时间

        Returns:
            ApprovalResult: 审批结果
        """
        level = self.check(action)

        if level == ApprovalLevel.AUTO:
            return ApprovalResult(
                approved=True,
                level=level,
                reason="自动通过（低风险操作）",
            )

        if level == ApprovalLevel.DENY:
            logger.warning("操作被禁止: %s", action)
            raise CommandBlockedError(
                f"操作 '{action}' 被安全策略禁止",
                fix_hint="此操作在当前安全等级下不允许执行",
            )

        # CONFIRM: 需要人工确认
        return self._wait_for_confirmation(
            action, params, device_id,
            timeout or self.DEFAULT_TIMEOUT,
        )

    def _wait_for_confirmation(
        self,
        action: str,
        params: Dict[str, Any],
        device_id: str,
        timeout: float,
    ) -> ApprovalResult:
        """等待人工确认"""
        with self._lock:
            self._counter += 1
            request_id = f"apr_{int(time.time())}_{self._counter}"

        request = ApprovalRequest(
            request_id=request_id,
            action=action,
            params=params,
            device_id=device_id,
            level=ApprovalLevel.CONFIRM,
            created_at=time.time(),
        )

        event = threading.Event()
        with self._lock:
            self._pending[request_id] = request
            self._events[request_id] = event

        # 推送审批请求到前端
        if self._on_approval_request:
            try:
                self._on_approval_request({
                    "request_id": request_id,
                    "action": action,
                    "params": params,
                    "device_id": device_id,
                    "level": "confirm",
                    "timeout": timeout,
                })
            except Exception as e:
                logger.error("推送审批请求失败: %s", e)

        logger.info(
            "等待审批: %s [%s] (超时 %.0fs)",
            action, request_id, timeout,
        )

        # 等待确认
        confirmed = event.wait(timeout=timeout)

        with self._lock:
            request = self._pending.pop(request_id, request)
            self._events.pop(request_id, None)

        if not confirmed:
            request.status = "timeout"
            logger.warning("审批超时: %s [%s]", action, request_id)
            return ApprovalResult(
                approved=False,
                level=ApprovalLevel.CONFIRM,
                reason=f"审批超时 ({timeout}s)",
                request_id=request_id,
            )

        approved = request.status == "approved"
        return ApprovalResult(
            approved=approved,
            level=ApprovalLevel.CONFIRM,
            reason=f"{'已批准' if approved else '已拒绝'} by {request.reviewed_by}",
            request_id=request_id,
        )

    def approve(self, request_id: str, reviewer: str = "user") -> bool:
        """
        批准审批请求。

        Args:
            request_id: 请求 ID
            reviewer: 审批人

        Returns:
            是否成功
        """
        with self._lock:
            request = self._pending.get(request_id)
            event = self._events.get(request_id)

        if not request or not event:
            return False

        request.status = "approved"
        request.reviewed_by = reviewer
        event.set()
        logger.info("审批通过: %s [%s] by %s", request.action, request_id, reviewer)
        return True

    def reject(self, request_id: str, reviewer: str = "user") -> bool:
        """
        拒绝审批请求。

        Args:
            request_id: 请求 ID
            reviewer: 审批人

        Returns:
            是否成功
        """
        with self._lock:
            request = self._pending.get(request_id)
            event = self._events.get(request_id)

        if not request or not event:
            return False

        request.status = "rejected"
        request.reviewed_by = reviewer
        event.set()
        logger.info("审批拒绝: %s [%s] by %s", request.action, request_id, reviewer)
        return True

    def set_approval_callback(
        self, callback: Callable[[Dict[str, Any]], None]
    ) -> None:
        """注册审批请求推送回调（WebSocket emit）"""
        self._on_approval_request = callback

    def get_pending(self) -> list:
        """获取所有待审批请求"""
        with self._lock:
            return [
                {
                    "request_id": r.request_id,
                    "action": r.action,
                    "params": r.params,
                    "device_id": r.device_id,
                    "created_at": r.created_at,
                }
                for r in self._pending.values()
            ]
