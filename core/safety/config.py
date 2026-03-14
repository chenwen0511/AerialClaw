"""
core/safety/config.py — 安全配置加载器

从 config/safety_config.yaml 加载安全配置，
提供统一的访问接口。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logger import get_logger

logger = get_logger(__name__)

# 默认配置（YAML 文件缺失时的 fallback）
_DEFAULTS = {
    "safety_level": "standard",
    "blacklist": [
        "rm -rf", "shutdown", "reboot", "disable_safety",
        "override_envelope", "format", "mkfs", "dd if=",
    ],
    "whitelist": [
        "get_position", "get_battery", "hover", "observe",
        "detect_object", "get_sensor_data", "scan_area",
    ],
    "flight_envelope": {
        "max_speed": 10.0,
        "max_altitude": 120.0,
        "min_altitude": 0.5,
        "max_distance": 500.0,
        "min_battery": 15.0,
        "critical_battery": 5.0,
        "heartbeat_timeout": 10,
        "max_tilt_angle": 35.0,
        "geofence_enabled": True,
    },
}


class SafetyConfig:
    """
    安全配置管理器。

    从 config/safety_config.yaml 加载配置。
    文件缺失时使用内置默认值。
    """

    def __init__(self, config_path: str = "config/safety_config.yaml") -> None:
        self._path = config_path
        self._data: Dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """加载 YAML 配置文件"""
        path = Path(self._path)
        if not path.exists():
            logger.warning(
                "安全配置文件不存在: %s, 使用默认配置", self._path
            )
            self._data = dict(_DEFAULTS)
            return

        try:
            import yaml
            with open(path, "r", encoding="utf-8") as f:
                self._data = yaml.safe_load(f) or {}
            logger.info("安全配置已加载: %s (等级=%s)", self._path, self.level)
        except ImportError:
            logger.warning("PyYAML 未安装，使用默认安全配置")
            self._data = dict(_DEFAULTS)
        except Exception as e:
            logger.error("安全配置加载失败: %s, 使用默认配置", e)
            self._data = dict(_DEFAULTS)

    def reload(self) -> None:
        """重新加载配置文件"""
        self._load()

    @property
    def level(self) -> str:
        """当前安全等级: strict / standard / permissive"""
        return self._data.get("safety_level", "standard")

    @property
    def blacklist(self) -> List[str]:
        """永远禁止的命令列表"""
        return self._data.get("blacklist", _DEFAULTS["blacklist"])

    @property
    def whitelist(self) -> List[str]:
        """允许自动执行的命令列表"""
        return self._data.get("whitelist", _DEFAULTS["whitelist"])

    @property
    def confirm_required(self) -> List[str]:
        """需要人工确认的操作列表"""
        return self._data.get("confirm_required", [])

    @property
    def envelope(self) -> Dict[str, Any]:
        """安全包线参数"""
        return self._data.get("flight_envelope", _DEFAULTS["flight_envelope"])

    @property
    def approval_levels(self) -> Dict[str, Any]:
        """各安全等级的审批规则"""
        levels = self._data.get("approval_levels", {})
        return levels.get(self.level, {})

    @property
    def sandbox_config(self) -> Dict[str, Any]:
        """沙箱配置"""
        return self._data.get("sandbox", {
            "preferred": "auto",
            "execution_timeout": 10,
            "network_enabled": False,
        })

    @property
    def audit_config(self) -> Dict[str, Any]:
        """审计日志配置"""
        return self._data.get("audit", {
            "enabled": True,
            "log_dir": "logs/audit",
            "max_entries": 10000,
        })

    def get(self, key: str, default: Any = None) -> Any:
        """获取任意配置项"""
        return self._data.get(key, default)


# ── 全局单例 ─────────────────────────────────────────────────

_instance: Optional[SafetyConfig] = None


def get_safety_config(config_path: str = "config/safety_config.yaml") -> SafetyConfig:
    """获取全局安全配置单例"""
    global _instance
    if _instance is None:
        _instance = SafetyConfig(config_path)
    return _instance
