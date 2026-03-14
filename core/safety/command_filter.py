"""
core/safety/command_filter.py — 命令过滤器

白名单/黑名单命令过滤，作为安全体系的第一道关卡。
黑名单命令直接拦截，白名单外的命令需要审批。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

from core.errors import CommandBlockedError
from core.logger import get_logger
from core.safety.config import SafetyConfig

logger = get_logger(__name__)


@dataclass
class FilterResult:
    """过滤结果"""
    allowed: bool
    level: str       # pass / review / block
    reason: str = ""


# 硬编码黑名单 — 无论配置如何都不允许
_HARDCODED_BLACKLIST = frozenset([
    "disable_safety",
    "override_envelope",
    "rm -rf",
    "shutdown",
    "reboot",
    "format",
    "mkfs",
])


class CommandFilter:
    """
    命令过滤器。

    安全体系第一道关卡：
    1. 硬编码黑名单 → 直接拦截（不可配置绕过）
    2. 配置黑名单 → 直接拦截
    3. 白名单 → 自动通过
    4. 其余 → 需要审批
    """

    def __init__(self, config: SafetyConfig) -> None:
        self._config = config
        self._custom_blacklist: List[str] = []
        self._custom_whitelist: List[str] = []

    def check(self, command: str, params: Dict[str, Any] = None) -> FilterResult:
        """
        检查命令是否允许执行。

        Args:
            command: 命令名称
            params: 命令参数

        Returns:
            FilterResult: 过滤结果
        """
        cmd_lower = command.lower().strip()

        # 第一关：硬编码黑名单
        if cmd_lower in _HARDCODED_BLACKLIST:
            logger.warning("命令被硬编码黑名单拦截: %s", command)
            return FilterResult(
                allowed=False,
                level="block",
                reason=f"命令 '{command}' 被安全系统禁止（硬编码黑名单）",
            )

        # 第二关：配置黑名单（支持前缀匹配）
        for pattern in self._config.blacklist:
            if cmd_lower == pattern.lower() or cmd_lower.startswith(pattern.lower()):
                logger.warning("命令被配置黑名单拦截: %s (匹配 %s)", command, pattern)
                return FilterResult(
                    allowed=False,
                    level="block",
                    reason=f"命令 '{command}' 被安全配置禁止（匹配规则: {pattern}）",
                )

        # 第三关：白名单
        all_whitelist = list(self._config.whitelist) + self._custom_whitelist
        if cmd_lower in [w.lower() for w in all_whitelist]:
            return FilterResult(
                allowed=True,
                level="pass",
                reason="命令在白名单中，自动通过",
            )

        # 第四关：需要审批的命令
        if cmd_lower in [c.lower() for c in self._config.confirm_required]:
            return FilterResult(
                allowed=False,
                level="review",
                reason=f"命令 '{command}' 需要人工确认",
            )

        # 默认：需要审批
        return FilterResult(
            allowed=False,
            level="review",
            reason=f"命令 '{command}' 不在白名单中，需要审批",
        )

    def add_to_whitelist(self, command: str) -> None:
        """动态添加白名单命令"""
        self._custom_whitelist.append(command)
        logger.info("动态添加白名单: %s", command)

    def add_to_blacklist(self, command: str) -> None:
        """动态添加黑名单命令"""
        self._custom_blacklist.append(command)
        logger.info("动态添加黑名单: %s", command)
