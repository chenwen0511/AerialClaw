"""
core/safety/audit_log.py — 操作审计日志

记录所有设备操作，支持查询和导出。
"""

from __future__ import annotations

import json
import os
import time
import threading
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class AuditEntry:
    """单条审计记录"""
    timestamp: float
    device_id: str
    action: str
    params: Dict[str, Any]
    result: str              # success / fail / blocked / timeout
    user: str = "system"
    reason: str = ""
    cost_time: float = 0.0
    entry_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return asdict(self)


class AuditLog:
    """
    操作审计日志。

    记录所有设备操作，支持：
    - 按设备/时间范围查询
    - 导出为 JSON 文件
    - 自动轮转（超过 max_entries 条后删除最旧的）
    """

    def __init__(
        self,
        log_dir: str = "logs/audit",
        max_entries: int = 10000,
    ) -> None:
        self._log_dir = Path(log_dir)
        self._max_entries = max_entries
        self._entries: List[AuditEntry] = []
        self._lock = threading.Lock()
        self._counter = 0

        # 确保目录存在
        self._log_dir.mkdir(parents=True, exist_ok=True)
        logger.info("审计日志初始化: %s (最大 %d 条)", log_dir, max_entries)

    def log_action(
        self,
        device_id: str,
        action: str,
        params: Dict[str, Any],
        result: str,
        user: str = "system",
        reason: str = "",
        cost_time: float = 0.0,
    ) -> str:
        """
        记录一条操作日志。

        Args:
            device_id: 设备 ID
            action: 操作名称
            params: 操作参数
            result: 执行结果（success/fail/blocked/timeout）
            user: 操作者
            reason: 补充说明
            cost_time: 耗时（秒）

        Returns:
            entry_id: 日志条目 ID
        """
        with self._lock:
            self._counter += 1
            entry_id = f"audit_{int(time.time())}_{self._counter}"

        entry = AuditEntry(
            timestamp=time.time(),
            device_id=device_id,
            action=action,
            params=params,
            result=result,
            user=user,
            reason=reason,
            cost_time=cost_time,
            entry_id=entry_id,
        )

        with self._lock:
            self._entries.append(entry)
            # 轮转
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]

        # 安全相关操作打日志
        if result in ("blocked", "fail"):
            logger.warning(
                "审计 [%s] %s/%s → %s: %s",
                device_id, action, json.dumps(params, ensure_ascii=False)[:80],
                result, reason,
            )

        return entry_id

    def get_log(
        self,
        device_id: Optional[str] = None,
        limit: int = 100,
        action: Optional[str] = None,
        result: Optional[str] = None,
    ) -> List[AuditEntry]:
        """
        查询审计日志。

        Args:
            device_id: 按设备 ID 过滤
            limit: 最大返回条数
            action: 按动作过滤
            result: 按结果过滤

        Returns:
            匹配的日志条目列表（最新在前）
        """
        with self._lock:
            entries = list(reversed(self._entries))

        filtered = []
        for entry in entries:
            if device_id and entry.device_id != device_id:
                continue
            if action and entry.action != action:
                continue
            if result and entry.result != result:
                continue
            filtered.append(entry)
            if len(filtered) >= limit:
                break

        return filtered

    def export(self, path: Optional[str] = None) -> str:
        """
        导出审计日志为 JSON 文件。

        Args:
            path: 文件路径，默认自动生成

        Returns:
            导出文件路径
        """
        if path is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            path = str(self._log_dir / f"audit_{timestamp}.json")

        with self._lock:
            entries = [e.to_dict() for e in self._entries]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)

        logger.info("审计日志导出: %s (%d 条)", path, len(entries))
        return path

    def count(self) -> int:
        """返回日志条目数"""
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        """清空日志"""
        with self._lock:
            self._entries.clear()
        logger.info("审计日志已清空")
