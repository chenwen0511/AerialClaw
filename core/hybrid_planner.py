"""
core/hybrid_planner.py — AerialClaw 边缘-云端混合规划器

策略：
  - 简单任务（simple）  → 本地小模型，低延迟
  - 中等任务（moderate）→ 本地优先，超时后降级为预设
  - 复杂任务（complex） → 云端大模型，能力强
  - 断网时              → 切换为预设规划（preset），保证基本可用

使用方式：
    planner = HybridPlanner(
        local_client=get_client(module="local"),
        cloud_client=get_client(module="cloud"),
    )
    result = planner.plan("帮我搜索灾区东北角")
    # result = {"plan": "...", "backend": "cloud", "complexity": "complex"}
"""

from __future__ import annotations

import time
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

from core.errors import LLMConnectionError, LLMResponseError
from core.logger import get_logger

logger = get_logger(__name__)

# 复杂度分级
_COMPLEXITY_SIMPLE = "simple"
_COMPLEXITY_MODERATE = "moderate"
_COMPLEXITY_COMPLEX = "complex"

# 简单任务关键词（出现任意一个 → simple）
_SIMPLE_KEYWORDS = frozenset({
    "悬停", "hover", "起飞", "takeoff", "降落", "land",
    "返航", "return", "电量", "battery", "状态", "status",
    "ping", "高度", "altitude", "速度", "speed",
})

# 复杂任务关键词（出现任意一个 → complex）
_COMPLEX_KEYWORDS = frozenset({
    "搜救", "搜索", "规划路径", "path planning", "多机协同",
    "区域覆盖", "obstacle avoidance", "避障", "自主", "autonomous",
    "巡逻策略", "目标跟踪", "tracking", "建图", "mapping",
})

# 预设规划（断网时兜底）
_PRESET_PLANS: Dict[str, str] = {
    _COMPLEXITY_SIMPLE: (
        "【预设-简单】无法连接模型，执行基础安全动作：\n"
        "1. 保持当前位置悬停\n"
        "2. 等待网络恢复或人工指令\n"
        "3. 电量低于20%时自动降落"
    ),
    _COMPLEXITY_MODERATE: (
        "【预设-中等】无法连接模型，执行保守策略：\n"
        "1. 完成当前动作后悬停\n"
        "2. 原地旋转360°观察环境\n"
        "3. 等待网络恢复，超过60s则返航"
    ),
    _COMPLEXITY_COMPLEX: (
        "【预设-复杂】无法连接模型，中止复杂任务：\n"
        "1. 立即悬停，不执行复杂操作\n"
        "2. 标记当前位置\n"
        "3. 返回起飞点，等待人工决策"
    ),
}

# 云端连通性探测目标（轻量级）
_CLOUD_PROBE_URL = "https://www.baidu.com"
_CLOUD_PROBE_TIMEOUT = 3.0


# ══════════════════════════════════════════════════════════════
#  HybridPlanner
# ══════════════════════════════════════════════════════════════


class HybridPlanner:
    """
    边缘-云端混合规划器。

    根据任务复杂度自动选择后端：
      simple   → local_client
      moderate → local_client（失败则预设）
      complex  → cloud_client（离线则预设）

    Args:
        local_client:  本地 LLM 客户端（实现 .chat(messages) → str）。
        cloud_client:  云端 LLM 客户端（同接口）。
        local_timeout: 本地调用超时（秒），默认 10.0。
        cloud_timeout: 云端调用超时（秒），默认 30.0。
        system_prompt: 传给模型的系统提示，None 时使用默认值。
    """

    def __init__(
        self,
        local_client=None,
        cloud_client=None,
        local_timeout: float = 10.0,
        cloud_timeout: float = 30.0,
        system_prompt: Optional[str] = None,
    ) -> None:
        self._local = local_client
        self._cloud = cloud_client
        self._local_timeout = local_timeout
        self._cloud_timeout = cloud_timeout
        self._system_prompt = system_prompt or (
            "你是 AerialClaw 飞控规划器。根据任务描述生成清晰、可执行的步骤列表。"
            "每步以数字编号，简洁描述动作和参数。禁止输出代码块。"
        )
        # 云端可达性缓存，避免每次规划都探测
        self._cloud_available_cache: Optional[bool] = None
        self._cloud_cache_ts: float = 0.0
        self._cloud_cache_ttl: float = 30.0  # 缓存 30 秒

        logger.info(
            "HybridPlanner 初始化: local=%s, cloud=%s",
            "✓" if local_client else "✗",
            "✓" if cloud_client else "✗",
        )

    # ── 主入口 ───────────────────────────────────────────────

    def plan(self, task: str, complexity: str = "auto") -> Dict[str, Any]:
        """
        为任务生成执行规划。

        Args:
            task:       任务描述文本。
            complexity: 复杂度提示：
                          'auto'     → 自动估算
                          'simple'   → 强制本地
                          'moderate' → 强制本地
                          'complex'  → 强制云端

        Returns:
            字典，包含：
              - plan       (str)  : 规划内容
              - backend    (str)  : 'local' | 'cloud' | 'preset'
              - complexity (str)  : 'simple' | 'moderate' | 'complex'
              - elapsed    (float): 耗时（秒）
              - task       (str)  : 原始任务

        Raises:
            ValueError: complexity 传入非法值。
        """
        valid = {"auto", _COMPLEXITY_SIMPLE, _COMPLEXITY_MODERATE, _COMPLEXITY_COMPLEX}
        if complexity not in valid:
            raise ValueError(
                f"complexity 无效值 '{complexity}'，可选: {sorted(valid)}"
            )

        start = time.time()

        # 1. 确定复杂度
        actual_complexity = (
            self.estimate_complexity(task)
            if complexity == "auto"
            else complexity
        )

        # 2. 根据复杂度选择后端
        plan_text, backend = self._dispatch(task, actual_complexity)

        elapsed = round(time.time() - start, 3)
        logger.info(
            "HybridPlanner.plan: complexity=%s backend=%s elapsed=%.3fs",
            actual_complexity, backend, elapsed,
        )

        return {
            "plan": plan_text,
            "backend": backend,
            "complexity": actual_complexity,
            "elapsed": elapsed,
            "task": task,
        }

    # ── 复杂度估算 ───────────────────────────────────────────

    def estimate_complexity(self, task: str) -> str:
        """
        估算任务复杂度。

        规则（优先级从高到低）：
          1. 包含 _COMPLEX_KEYWORDS → complex
          2. 包含 _SIMPLE_KEYWORDS  → simple
          3. 任务长度 > 50 字符     → moderate
          4. 其他                   → simple

        Args:
            task: 任务描述。

        Returns:
            'simple' | 'moderate' | 'complex'
        """
        task_lower = task.lower()

        for kw in _COMPLEX_KEYWORDS:
            if kw in task_lower:
                logger.debug("复杂度估算: complex (命中关键词 '%s')", kw)
                return _COMPLEXITY_COMPLEX

        for kw in _SIMPLE_KEYWORDS:
            if kw in task_lower:
                logger.debug("复杂度估算: simple (命中关键词 '%s')", kw)
                return _COMPLEXITY_SIMPLE

        if len(task) > 50:
            logger.debug("复杂度估算: moderate (任务长度 %d > 50)", len(task))
            return _COMPLEXITY_MODERATE

        return _COMPLEXITY_SIMPLE

    # ── 云端可达性 ───────────────────────────────────────────

    def is_cloud_available(self) -> bool:
        """
        检测云端是否可达（带 30 秒缓存，避免频繁探测）。

        Returns:
            True 表示可访问互联网。
        """
        now = time.time()
        if (
            self._cloud_available_cache is not None
            and now - self._cloud_cache_ts < self._cloud_cache_ttl
        ):
            return self._cloud_available_cache

        available = self._probe_cloud()
        self._cloud_available_cache = available
        self._cloud_cache_ts = now
        logger.debug("云端可达性: %s", "✓" if available else "✗")
        return available

    def invalidate_cloud_cache(self) -> None:
        """手动失效云端可达性缓存，下次调用 is_cloud_available() 会重新探测。"""
        self._cloud_available_cache = None

    # ── 内部方法 ─────────────────────────────────────────────

    def _dispatch(self, task: str, complexity: str) -> tuple[str, str]:
        """
        根据复杂度将任务分发到对应后端。

        Returns:
            (plan_text, backend_name)
        """
        if complexity == _COMPLEXITY_COMPLEX:
            return self._call_cloud_or_preset(task, complexity)

        # simple / moderate → 本地
        return self._call_local_or_preset(task, complexity)

    def _call_local_or_preset(
        self, task: str, complexity: str
    ) -> tuple[str, str]:
        """尝试本地模型，失败时降级到预设。"""
        if self._local is None:
            logger.warning("HybridPlanner: 无本地模型，使用预设规划")
            return _PRESET_PLANS[complexity], "preset"

        try:
            result = self._invoke(self._local, task, self._local_timeout)
            return result, "local"
        except Exception as e:
            logger.warning("本地模型调用失败: %s，降级到预设规划", e)
            return _PRESET_PLANS[complexity], "preset"

    def _call_cloud_or_preset(
        self, task: str, complexity: str
    ) -> tuple[str, str]:
        """检查云端可达性，可达则调用云端，否则降级到预设。"""
        if self._cloud is None:
            logger.warning("HybridPlanner: 无云端模型，使用预设规划")
            return _PRESET_PLANS[complexity], "preset"

        if not self.is_cloud_available():
            logger.warning("HybridPlanner: 云端不可达，使用预设规划")
            return _PRESET_PLANS[complexity], "preset"

        try:
            result = self._invoke(self._cloud, task, self._cloud_timeout)
            return result, "cloud"
        except Exception as e:
            logger.warning("云端模型调用失败: %s，降级到预设规划", e)
            self.invalidate_cloud_cache()
            return _PRESET_PLANS[complexity], "preset"

    def _invoke(self, client: Any, task: str, timeout: float) -> str:
        """
        调用 LLM 客户端并返回规划文本。

        Args:
            client:  实现 .chat(messages) 的客户端。
            task:    任务描述。
            timeout: 调用超时（秒）。

        Returns:
            模型返回的规划文本。

        Raises:
            LLMResponseError: 返回为空。
            Exception: 客户端自身抛出的异常。
        """
        messages = [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": task},
        ]
        reply: str = client.chat(messages)
        if not reply or not reply.strip():
            raise LLMResponseError(
                "LLM 返回空响应",
                fix_hint="检查模型是否正常运行，任务描述是否过短",
            )
        return reply.strip()

    def _probe_cloud(self) -> bool:
        """发起轻量 HTTP GET 探测云端网络连通性。"""
        try:
            req = urllib.request.Request(
                _CLOUD_PROBE_URL,
                headers={"User-Agent": "AerialClaw-HybridPlanner/2.0"},
                method="HEAD",
            )
            with urllib.request.urlopen(req, timeout=_CLOUD_PROBE_TIMEOUT):
                return True
        except Exception:
            return False
