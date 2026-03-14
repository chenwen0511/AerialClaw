"""
core/bootstrap.py — 首次启动引导流程

AerialClaw 首次启动时的初始化引导：
  阶段一（静态 UI）：配置 LLM API Key + 测试连接
  阶段二（LLM 接管）：起名字 → 选风格 → 选场景 → 安全等级
  结果写入：SOUL.md + .env + safety_config.yaml
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from core.logger import get_logger

logger = get_logger(__name__)

_BASE_DIR = Path(__file__).parent.parent


class BootstrapManager:
    """
    首次启动引导管理器。

    检测是否需要引导，管理引导流程状态。
    """

    def __init__(self) -> None:
        self._state: Dict[str, Any] = {
            "phase": "check",      # check / llm_config / llm_test / personality / safety / done
            "completed": False,
            "llm_configured": False,
            "personality_set": False,
            "safety_configured": False,
        }

    def needs_bootstrap(self) -> bool:
        """
        检测是否需要首次引导。

        条件：.env 不存在或 LLM_API_KEY 为空
        """
        env_path = _BASE_DIR / ".env"
        if not env_path.exists():
            return True

        # 检查 .env 中是否有有效的 LLM 配置
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                content = f.read()
            # 至少要配置了一个 provider 的 key
            has_key = any(
                line.strip() and not line.startswith("#")
                and "API_KEY" in line and "your-" not in line.lower()
                for line in content.splitlines()
            )
            return not has_key
        except Exception:
            return True

    def get_state(self) -> Dict[str, Any]:
        """获取当前引导状态"""
        return dict(self._state)

    def set_phase(self, phase: str) -> None:
        """设置当前阶段"""
        self._state["phase"] = phase
        logger.info("引导阶段: %s", phase)

    # ── 阶段一：LLM 配置 ────────────────────────────────────

    def save_llm_config(
        self,
        provider: str,
        base_url: str,
        api_key: str,
        model: str,
    ) -> bool:
        """
        保存 LLM 配置到 .env 文件。

        Args:
            provider: 提供商名称
            base_url: API 地址
            api_key: API Key
            model: 模型名称

        Returns:
            是否保存成功
        """
        env_path = _BASE_DIR / ".env"
        try:
            # 读取现有 .env 或从 .env.example 复制
            if env_path.exists():
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
            else:
                example = _BASE_DIR / ".env.example"
                if example.exists():
                    with open(example, "r", encoding="utf-8") as f:
                        lines = f.readlines()
                else:
                    lines = []

            # 更新或追加配置
            env_vars = {
                "LLM_BASE_URL": base_url,
                "LLM_API_KEY": api_key,
                "LLM_MODEL": model,
            }

            updated = set()
            new_lines = []
            for line in lines:
                key = line.split("=")[0].strip() if "=" in line else ""
                if key in env_vars:
                    new_lines.append(f"{key}={env_vars[key]}\n")
                    updated.add(key)
                else:
                    new_lines.append(line)

            # 追加未更新的变量
            for key, value in env_vars.items():
                if key not in updated:
                    new_lines.append(f"{key}={value}\n")

            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(new_lines)

            self._state["llm_configured"] = True
            logger.info("LLM 配置已保存: provider=%s model=%s", provider, model)
            return True

        except Exception as e:
            logger.error("保存 LLM 配置失败: %s", e)
            return False

    def test_llm_connection(self, base_url: str, api_key: str, model: str) -> Dict[str, Any]:
        """
        测试 LLM 连接。

        Returns:
            {"ok": bool, "message": str, "model": str}
        """
        try:
            import requests
            resp = requests.post(
                f"{base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": "回复 ok"}],
                    "max_tokens": 10,
                },
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {"ok": True, "message": f"连接成功: {reply}", "model": model}
            return {"ok": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"ok": False, "message": f"连接失败: {e}"}

    # ── 阶段二：个性化配置 ──────────────────────────────────

    def save_personality(
        self,
        name: str = "AerialClaw",
        style: str = "professional",
    ) -> bool:
        """
        保存 AI 个性配置到 SOUL.md。

        Args:
            name: AI 名字
            style: 对话风格

        Returns:
            是否保存成功
        """
        soul_path = _BASE_DIR / "SOUL.md"
        try:
            content = f"""# SOUL.md — {name} 的灵魂

## 身份
- 名字: {name}
- 类型: 具身智能体控制大脑
- 风格: {style}

## 核心行为
- 我是设备的"大脑"，通过技能控制"身体"
- 我会先观察环境，再做出决策
- 安全是第一优先级，任何时候都不绕过安全包线
- 失败时反思原因，下次做得更好

## 对话风格
- 简洁明了，不说废话
- 执行任务时汇报进度
- 遇到不确定的情况主动询问
"""
            with open(soul_path, "w", encoding="utf-8") as f:
                f.write(content)

            self._state["personality_set"] = True
            logger.info("个性配置已保存: name=%s style=%s", name, style)
            return True
        except Exception as e:
            logger.error("保存个性配置失败: %s", e)
            return False

    # ── 阶段三：安全配置 ─────────────────────────────────────

    def save_safety_level(self, level: str = "standard") -> bool:
        """
        设置安全等级。

        Args:
            level: strict / standard / permissive

        Returns:
            是否保存成功
        """
        config_path = _BASE_DIR / "config" / "safety_config.yaml"
        if not config_path.exists():
            logger.warning("安全配置文件不存在")
            return False

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                content = f.read()

            # 替换 safety_level 行
            import re
            content = re.sub(
                r"^safety_level:\s*\w+",
                f"safety_level: {level}",
                content,
                flags=re.MULTILINE,
            )

            with open(config_path, "w", encoding="utf-8") as f:
                f.write(content)

            self._state["safety_configured"] = True
            logger.info("安全等级已设置: %s", level)
            return True
        except Exception as e:
            logger.error("保存安全等级失败: %s", e)
            return False

    def complete(self) -> None:
        """标记引导完成"""
        self._state["phase"] = "done"
        self._state["completed"] = True
        logger.info("首次引导完成")


# ── 全局单例 ─────────────────────────────────────────────────

_instance: Optional[BootstrapManager] = None


def get_bootstrap_manager() -> BootstrapManager:
    """获取引导管理器单例"""
    global _instance
    if _instance is None:
        _instance = BootstrapManager()
    return _instance
