"""
core/skill_evolver.py — 技能进化器

分析技能历史表现，通过 LLM 自动生成改进建议并重写软技能策略文档。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class PerformanceReport:
    """技能表现分析报告"""
    skill_name: str
    success_rate: float          # [0.0, 1.0]，-1.0 表示无数据
    avg_cost_time: float         # 平均执行耗时（秒）
    total_executions: int
    common_errors: list[str]     # 高频错误摘要
    context_patterns: list[str]  # 常见执行上下文模式


class SkillEvolver:
    """
    技能进化器。

    职责：
    - 从 SkillMemory 提取技能统计，生成 PerformanceReport
    - 调用 LLM 分析瓶颈并给出改进建议
    - 重写软技能 Markdown 策略文档
    - 在沙箱中对比新旧文档的模拟效果

    用法示例::

        evolver = SkillEvolver(llm_client=client, skill_memory=mem)
        report = evolver.analyze_performance("patrol_area")
        suggestion = evolver.suggest_improvement(report)
        new_doc = evolver.rewrite_strategy("patrol_area")
        diff = evolver.compare_in_sandbox(old_doc, new_doc)
    """

    def __init__(
        self,
        llm_client: Any,
        skill_memory: Any,
        memory_manager: Optional[Any] = None,
    ) -> None:
        """
        Args:
            llm_client:     支持 .chat() 或 .complete() 的 LLM 客户端
            skill_memory:   memory.skill_memory.SkillMemory 实例
            memory_manager: memory.memory_manager.MemoryManager（可选，用于跨层上下文）
        """
        self._llm = llm_client
        self._skill_memory = skill_memory
        self._memory_manager = memory_manager

    # ── 分析 ──────────────────────────────────────────────────

    def analyze_performance(self, skill_name: str) -> PerformanceReport:
        """
        从 SkillMemory 提取统计数据，构建 PerformanceReport。

        Args:
            skill_name: 技能名称

        Returns:
            PerformanceReport
        """
        reliability = self._skill_memory.get_skill_reliability(skill_name)

        # 从原始执行日志中提取错误和上下文模式
        common_errors: list[str] = []
        context_patterns: list[str] = []

        logs: list[dict] = getattr(self._skill_memory, "_execution_logs", [])
        skill_logs = [log for log in logs if log.get("skill") == skill_name]

        # 统计错误信息
        error_counts: dict[str, int] = {}
        for log in skill_logs:
            if not log.get("success", True):
                err = log.get("error", log.get("reason", "unknown_error"))
                error_counts[str(err)] = error_counts.get(str(err), 0) + 1

        # 取 top-5 高频错误
        common_errors = [
            err for err, _ in sorted(
                error_counts.items(), key=lambda x: x[1], reverse=True
            )[:5]
        ]

        # 从 MemoryManager 获取上下文模式（若可用）
        if self._memory_manager:
            try:
                ctx = self._memory_manager.get_context_for_planning(
                    f"执行技能 {skill_name} 时的上下文模式"
                )
                if ctx:
                    # 每行作为一个模式，取前 5 条
                    context_patterns = [
                        line.strip()
                        for line in ctx.splitlines()
                        if line.strip()
                    ][:5]
            except Exception as e:
                logger.debug("获取上下文模式失败（可忽略）: %s", e)

        report = PerformanceReport(
            skill_name=skill_name,
            success_rate=reliability["success_rate"],
            avg_cost_time=reliability["average_cost_time"],
            total_executions=reliability["total_executions"],
            common_errors=common_errors,
            context_patterns=context_patterns,
        )

        logger.info(
            "技能分析完成: %s | 成功率=%.1f%% | 执行次数=%d",
            skill_name,
            report.success_rate * 100 if report.success_rate >= 0 else -1,
            report.total_executions,
        )
        return report

    # ── LLM 改进建议 ───────────────────────────────────────────

    def suggest_improvement(self, report: PerformanceReport) -> str:
        """
        根据 PerformanceReport 请求 LLM 给出改进建议。

        Args:
            report: analyze_performance() 返回的报告

        Returns:
            LLM 生成的改进建议文本
        """
        success_pct = (
            f"{report.success_rate * 100:.1f}%"
            if report.success_rate >= 0
            else "无历史数据"
        )

        prompt = (
            f"你是 AerialClaw 无人机系统的技能优化专家。\n"
            f"以下是技能 [{report.skill_name}] 的执行分析报告：\n\n"
            f"- 成功率：{success_pct}\n"
            f"- 平均耗时：{report.avg_cost_time:.2f} 秒\n"
            f"- 总执行次数：{report.total_executions}\n"
            f"- 常见错误：{', '.join(report.common_errors) or '暂无'}\n"
            f"- 上下文模式：{', '.join(report.context_patterns) or '暂无'}\n\n"
            f"请分析潜在问题并给出 3-5 条具体可操作的改进建议，"
            f"重点关注：错误处理、执行效率、鲁棒性。"
        )

        suggestion = self._call_llm(prompt)
        logger.info("已生成技能改进建议: %s (%d 字)", report.skill_name, len(suggestion))
        return suggestion

    # ── 重写策略文档 ──────────────────────────────────────────

    def rewrite_strategy(self, skill_name: str) -> str:
        """
        LLM 根据当前文档和历史表现，重写软技能 Markdown 策略文档。

        Args:
            skill_name: 软技能名称（对应 soft_docs/ 下的 .md 文件）

        Returns:
            重写后的 Markdown 文档字符串
        """
        from skills.soft_skill_manager import get_soft_skill_manager

        manager = get_soft_skill_manager()
        old_doc = manager.get_skill_doc(skill_name) if manager.skill_exists(skill_name) else ""

        report = self.analyze_performance(skill_name)
        success_pct = (
            f"{report.success_rate * 100:.1f}%"
            if report.success_rate >= 0
            else "无历史数据"
        )

        prompt = (
            f"你是 AerialClaw 无人机系统的软技能文档工程师。\n"
            f"请根据执行数据重写软技能 [{skill_name}] 的策略文档。\n\n"
            f"【当前文档】\n{old_doc or '（尚无文档）'}\n\n"
            f"【执行统计】\n"
            f"- 成功率：{success_pct}\n"
            f"- 平均耗时：{report.avg_cost_time:.2f} 秒\n"
            f"- 常见错误：{', '.join(report.common_errors) or '暂无'}\n\n"
            f"【要求】\n"
            f"1. 保持 Markdown 格式，包含：技能名称、目标、执行步骤、注意事项、历史经验\n"
            f"2. 在执行步骤中融入对常见错误的预防措施\n"
            f"3. 注意事项中新增基于数据的鲁棒性建议\n"
            f"4. 历史经验章节总结本次优化要点\n"
            f"5. 只输出 Markdown 文档内容，不要有多余解释"
        )

        new_doc = self._call_llm(prompt)
        logger.info("技能策略文档已重写: %s (%d 字)", skill_name, len(new_doc))
        return new_doc

    # ── 沙箱对比 ──────────────────────────────────────────────

    def compare_in_sandbox(self, old_doc: str, new_doc: str) -> dict:
        """
        让 LLM 模拟对比新旧文档的预期效果，返回对比报告。

        注：当前为 LLM 模拟评估（非真实运行），未来可接入沙箱执行器。

        Args:
            old_doc: 原策略文档
            new_doc: 重写后的策略文档

        Returns:
            dict: {
                "winner": "new" | "old" | "tie",
                "old_score": float,   # 0-10
                "new_score": float,   # 0-10
                "analysis": str,      # LLM 分析说明
                "improvements": list[str],
                "regressions": list[str],
            }
        """
        prompt = (
            f"你是 AerialClaw 软技能评估专家，请对比以下两个策略文档的预期执行质量。\n\n"
            f"【旧文档】\n{old_doc or '（空）'}\n\n"
            f"【新文档】\n{new_doc or '（空）'}\n\n"
            f"请从以下维度评分（0-10分）并给出分析：\n"
            f"- 步骤完整性\n- 错误处理能力\n- 执行效率\n- 鲁棒性\n\n"
            f"严格按如下 JSON 格式输出（不要有其他内容）：\n"
            f'{{"old_score": 数字, "new_score": 数字, '
            f'"analysis": "分析说明", '
            f'"improvements": ["改进点1", "改进点2"], '
            f'"regressions": ["退步点1"]}}'
        )

        raw = self._call_llm(prompt)

        try:
            import json
            # 提取 JSON（LLM 可能在前后附加多余文字）
            start = raw.find("{")
            end = raw.rfind("}") + 1
            data = json.loads(raw[start:end])

            old_score = float(data.get("old_score", 0))
            new_score = float(data.get("new_score", 0))

            if new_score > old_score:
                winner = "new"
            elif old_score > new_score:
                winner = "old"
            else:
                winner = "tie"

            return {
                "winner": winner,
                "old_score": old_score,
                "new_score": new_score,
                "analysis": data.get("analysis", ""),
                "improvements": data.get("improvements", []),
                "regressions": data.get("regressions", []),
            }
        except Exception as e:
            logger.warning("沙箱对比结果解析失败: %s，返回原始文本", e)
            return {
                "winner": "unknown",
                "old_score": 0.0,
                "new_score": 0.0,
                "analysis": raw,
                "improvements": [],
                "regressions": [],
            }

    # ── 内部工具 ──────────────────────────────────────────────

    def _call_llm(self, prompt: str) -> str:
        """
        统一 LLM 调用入口，兼容多种客户端接口。

        支持的接口形式：
        - client.chat(prompt) -> str
        - client.complete(prompt) -> str
        - client.chat.completions.create(...) (OpenAI 风格)
        """
        try:
            # 优先尝试 .chat()
            if hasattr(self._llm, "chat"):
                result = self._llm.chat(prompt)
                if isinstance(result, str):
                    return result
                # OpenAI 风格返回对象
                if hasattr(result, "choices"):
                    return result.choices[0].message.content or ""

            # 尝试 .complete()
            if hasattr(self._llm, "complete"):
                result = self._llm.complete(prompt)
                if isinstance(result, str):
                    return result

            # 尝试 OpenAI 风格 .chat.completions.create()
            if hasattr(self._llm, "chat") and hasattr(self._llm.chat, "completions"):
                resp = self._llm.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "user", "content": prompt}],
                )
                return resp.choices[0].message.content or ""

            raise AttributeError("LLM 客户端不支持已知接口（chat / complete）")

        except Exception as e:
            logger.error("LLM 调用失败: %s", e)
            return f"[LLM 调用失败: {e}]"
