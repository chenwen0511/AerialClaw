"""
core/device_analyzer.py — 设备分析器

LLM 分析设备能力，自动生成 BODY.md 和匹配技能。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.device_manager import DeviceInfo
from core.errors import LLMResponseError
from core.logger import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
#  Data Classes
# ══════════════════════════════════════════════════════════════


@dataclass
class AnalysisResult:
    """LLM 分析设备的结构化结果"""
    device_type: str                        # UAV / UGV / ARM / SENSOR / CUSTOM
    capabilities: List[str]                 # 设备支持的能力列表
    limitations: List[str]                  # 设备限制/不支持的功能
    recommended_skills: List[str]           # 推荐启用的技能名称
    unsupported_skills: List[str]           # 不适用于此设备的技能
    new_skills_needed: List[Dict[str, str]] # 需要新建的技能: [{"name": ..., "reason": ...}]
    body_md: str                            # 生成的 BODY.md 内容


@dataclass
class SkillMatch:
    """技能匹配结果"""
    available: List[str] = field(default_factory=list)      # 已有且可用的技能
    unavailable: List[str] = field(default_factory=list)    # 推荐但当前不可用的技能
    needs_creation: List[Dict[str, str]] = field(default_factory=list)  # 需要新建的技能


# ══════════════════════════════════════════════════════════════
#  Device Analyzer
# ══════════════════════════════════════════════════════════════

_ANALYZE_SYSTEM = """\
你是 AerialClaw 机器人中间件的设备分析专家。
根据用户提供的设备信息，分析设备能力并输出结构化 JSON。

CRITICAL: 你必须只输出合法 JSON，不要包含任何解释、注释或 Markdown 代码块。
CRITICAL: JSON 结构必须严格遵循以下 schema，字段不可缺失：

{
  "device_type": "UAV|UGV|ARM|SENSOR|CUSTOM",
  "capabilities": ["string", ...],
  "limitations": ["string", ...],
  "recommended_skills": ["skill_name", ...],
  "unsupported_skills": ["skill_name", ...],
  "new_skills_needed": [
    {"name": "skill_name", "reason": "why needed"}
  ]
}

capabilities 示例值：fly, hover, camera, lidar, gps, arm_control, navigate, stream_video
recommended_skills 使用下划线命名，如：takeoff, land, move_to, capture_photo"""

_BODY_SYSTEM = """\
你是 AerialClaw 技术文档撰写专家。
根据设备分析结果，生成标准格式的 BODY.md 机器人技能文档。

CRITICAL: 只输出 Markdown 文本，不要包含任何额外解释。
文档结构必须包含：
1. # 设备名称 标题
2. ## 设备概述 — 类型、协议、核心能力
3. ## 可用技能 — 每个技能一行，格式: `- skill_name: 功能描述`
4. ## 限制说明 — 设备不支持的功能
5. ## 传感器列表 — 可用传感器
6. ## 使用示例 — 1~3 个自然语言指令示例"""


class DeviceAnalyzer:
    """
    设备能力分析器。

    调用 LLM 分析接入设备的能力，自动生成：
    - AnalysisResult: 结构化能力描述
    - BODY.md: 供 SkillLoader 和用户阅读的技能文档
    - SkillMatch: 与现有技能的匹配情况
    """

    def __init__(self, llm_client) -> None:
        """
        Args:
            llm_client: LLMClient 实例，需提供 chat(messages) -> str 方法
        """
        self._llm = llm_client

    # ── 主分析入口 ────────────────────────────────────────

    def analyze(self, device_info: DeviceInfo) -> AnalysisResult:
        """
        LLM 分析设备能力，返回结构化结果。

        Args:
            device_info: 已注册的设备信息

        Returns:
            AnalysisResult

        Raises:
            LLMResponseError: LLM 返回格式不合法
        """
        logger.info("开始分析设备: %s (%s)", device_info.device_id, device_info.device_type)

        user_prompt = self._build_analyze_prompt(device_info)
        messages = [
            {"role": "system", "content": _ANALYZE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        raw = self._llm.chat(messages)
        data = self._parse_json(raw, context="设备分析")

        try:
            result = AnalysisResult(
                device_type=data.get("device_type", device_info.device_type),
                capabilities=data.get("capabilities", device_info.capabilities),
                limitations=data.get("limitations", []),
                recommended_skills=data.get("recommended_skills", []),
                unsupported_skills=data.get("unsupported_skills", []),
                new_skills_needed=data.get("new_skills_needed", []),
                body_md="",  # 下一步生成
            )
        except (KeyError, TypeError) as e:
            raise LLMResponseError(
                f"分析结果字段缺失: {e}",
                fix_hint="检查 LLM 是否遵循了 JSON schema",
            )

        result.body_md = self.generate_body(result, device_info)
        logger.info(
            "设备分析完成: %s | 能力=%d 推荐技能=%d 需新建=%d",
            device_info.device_id,
            len(result.capabilities),
            len(result.recommended_skills),
            len(result.new_skills_needed),
        )
        return result

    # ── BODY.md 生成 ──────────────────────────────────────

    def generate_body(
        self,
        analysis: AnalysisResult,
        device_info: Optional[DeviceInfo] = None,
    ) -> str:
        """
        根据分析结果生成 BODY.md 内容。

        Args:
            analysis: 设备分析结果
            device_info: 原始设备信息（可选，用于补充传感器列表）

        Returns:
            BODY.md 的 Markdown 字符串
        """
        sensors = device_info.sensors if device_info else []
        user_prompt = (
            f"设备类型: {analysis.device_type}\n"
            f"协议: {device_info.protocol if device_info else 'unknown'}\n"
            f"能力: {', '.join(analysis.capabilities)}\n"
            f"限制: {', '.join(analysis.limitations)}\n"
            f"推荐技能: {', '.join(analysis.recommended_skills)}\n"
            f"不支持技能: {', '.join(analysis.unsupported_skills)}\n"
            f"传感器: {', '.join(sensors)}\n"
            f"需新建技能: {json.dumps(analysis.new_skills_needed, ensure_ascii=False)}\n"
        )
        messages = [
            {"role": "system", "content": _BODY_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]
        body = self._llm.chat(messages)
        logger.debug("BODY.md 生成完成 (%d 字节)", len(body))
        return body

    # ── 技能匹配 ──────────────────────────────────────────

    def match_skills(
        self,
        analysis: AnalysisResult,
        existing_skills: List[str],
    ) -> SkillMatch:
        """
        将分析结果中推荐的技能与已有技能列表比对。

        Args:
            analysis: 设备分析结果
            existing_skills: 当前已注册的技能名称列表

        Returns:
            SkillMatch
        """
        existing_set = set(existing_skills)
        recommended_set = set(analysis.recommended_skills)

        available = sorted(recommended_set & existing_set)
        unavailable = sorted(recommended_set - existing_set)

        match = SkillMatch(
            available=available,
            unavailable=unavailable,
            needs_creation=analysis.new_skills_needed,
        )
        logger.info(
            "技能匹配: 可用=%d 缺失=%d 需新建=%d",
            len(match.available),
            len(match.unavailable),
            len(match.needs_creation),
        )
        return match

    # ── 内部工具 ──────────────────────────────────────────

    def _build_analyze_prompt(self, info: DeviceInfo) -> str:
        metadata_str = json.dumps(info.metadata, ensure_ascii=False, indent=2) if info.metadata else "{}"
        return (
            f"设备 ID: {info.device_id}\n"
            f"设备类型: {info.device_type}\n"
            f"已声明能力: {', '.join(info.capabilities)}\n"
            f"传感器: {', '.join(info.sensors)}\n"
            f"通信协议: {info.protocol}\n"
            f"元数据:\n{metadata_str}\n\n"
            "请分析该设备的完整能力并输出 JSON。"
        )

    def _parse_json(self, raw: str, context: str = "") -> Dict[str, Any]:
        """从 LLM 原始输出中提取 JSON 对象"""
        # 去掉 markdown 代码块
        cleaned = re.sub(r"```(?:json)?\s*", "", raw).replace("```", "").strip()
        # 尝试提取第一个 {...} 块
        match = re.search(r"\{[\s\S]+\}", cleaned)
        if match:
            cleaned = match.group(0)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise LLMResponseError(
                f"[{context}] LLM 返回的 JSON 无法解析: {e}",
                fix_hint="检查 LLM 是否输出了纯 JSON，确保未包含额外文字",
            )
