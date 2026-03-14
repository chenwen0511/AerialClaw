"""
core/preflight.py — AerialClaw 启动前环境自检

在 server.py 启动时调用 run_preflight()，自动检测所有依赖和配置。
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

# ── 数据结构 ──────────────────────────────────────────────

@dataclass
class CheckResult:
    """单项检查结果"""
    name: str
    status: Literal["ok", "warn", "fail"]
    message: str
    fix_hint: str = ""

    @property
    def icon(self) -> str:
        return {"ok": "✅", "warn": "⚠️", "fail": "❌"}[self.status]

    def __str__(self) -> str:
        line = f"  {self.icon} {self.name}: {self.message}"
        if self.fix_hint and self.status != "ok":
            line += f"\n     → {self.fix_hint}"
        return line


@dataclass
class PreflightReport:
    """自检报告"""
    results: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.status == "ok")

    @property
    def warnings(self) -> int:
        return sum(1 for r in self.results if r.status == "warn")

    @property
    def failures(self) -> int:
        return sum(1 for r in self.results if r.status == "fail")

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def can_start(self) -> bool:
        """有 fail 也能启动（降级运行），但会警告"""
        return True

    def __str__(self) -> str:
        lines = [
            "",
            "🔍 AerialClaw 环境自检",
            "─" * 40,
        ]
        for r in self.results:
            lines.append(str(r))
        lines.append("─" * 40)
        lines.append(f"  结果: {self.passed}✅  {self.warnings}⚠️  {self.failures}❌  / {self.total} 项")
        if self.failures > 0:
            lines.append("  ⚠️ 部分功能不可用，系统将降级运行")
        else:
            lines.append("  🚀 系统就绪")
        lines.append("")
        return "\n".join(lines)


# ── 检查函数 ──────────────────────────────────────────────

def _check_python() -> CheckResult:
    v = sys.version_info
    if v >= (3, 10):
        return CheckResult("Python", "ok", f"{v.major}.{v.minor}.{v.micro}")
    return CheckResult("Python", "fail",
        f"{v.major}.{v.minor} (需要 >= 3.10)",
        "安装 Python 3.10+: https://python.org")


def _check_dependencies() -> CheckResult:
    missing = []
    for pkg in ["flask", "flask_socketio", "flask_cors", "yaml", "mavsdk"]:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing.append(pkg)
    if not missing:
        return CheckResult("Python 依赖", "ok", "核心包已安装")
    return CheckResult("Python 依赖", "fail",
        f"缺少: {', '.join(missing)}",
        "pip install -r requirements.txt")


def _check_env() -> CheckResult:
    env_path = Path(".env")
    if not env_path.exists():
        return CheckResult(".env 配置", "fail",
            "文件不存在",
            "cp .env.example .env 然后填入配置")

    key = os.environ.get("LLM_API_KEY", "")
    if not key or key in ("your-llm-api-key-here", ""):
        provider = os.environ.get("ACTIVE_PROVIDER", "unknown")
        if provider == "ollama_local":
            return CheckResult(".env 配置", "ok", "Ollama 本地模式（无需 Key）")
        return CheckResult(".env 配置", "warn",
            f"LLM_API_KEY 未配置 (provider={provider})",
            "编辑 .env 填入 API Key，或切换到 ollama_local")
    return CheckResult(".env 配置", "ok", f"已配置 (provider={os.environ.get('ACTIVE_PROVIDER', 'unknown')})")


def _check_llm() -> CheckResult:
    key = os.environ.get("LLM_API_KEY", "")
    provider = os.environ.get("ACTIVE_PROVIDER", "")
    if provider == "ollama_local":
        # 测试 Ollama 连接
        try:
            import requests
            url = os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434/v1")
            r = requests.get(f"{url.rstrip('/v1')}/api/tags", timeout=3)
            if r.status_code == 200:
                return CheckResult("LLM 连接", "ok", f"Ollama 在线")
        except Exception:
            pass
        return CheckResult("LLM 连接", "warn",
            "Ollama 未响应",
            "启动 Ollama: ollama serve")

    if not key or key in ("your-llm-api-key-here", ""):
        return CheckResult("LLM 连接", "warn",
            "API Key 未配置，跳过连接测试",
            "编辑 .env 填入 LLM_API_KEY")

    try:
        import requests
        url = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
        r = requests.get(f"{url}/models",
                         headers={"Authorization": f"Bearer {key}"},
                         timeout=5)
        if r.status_code == 200:
            return CheckResult("LLM 连接", "ok", f"API 在线 ({url})")
        return CheckResult("LLM 连接", "warn",
            f"API 返回 {r.status_code}",
            "检查 LLM_BASE_URL 和 LLM_API_KEY 是否正确")
    except Exception as e:
        return CheckResult("LLM 连接", "warn",
            f"连接失败: {str(e)[:50]}",
            "检查网络和 LLM_BASE_URL")


def _check_web_ui() -> CheckResult:
    dist = Path("ui/dist/index.html")
    if dist.exists():
        return CheckResult("Web UI", "ok", "已构建")
    return CheckResult("Web UI", "warn",
        "ui/dist/ 不存在",
        "cd ui && npm install && npm run build")


def _check_simulation() -> CheckResult:
    try:
        import mavsdk
        ver = getattr(mavsdk, '__version__', 'installed')
        return CheckResult("MAVSDK", "ok", f"已安装 ({ver})")
    except ImportError:
        return CheckResult("MAVSDK", "warn",
            "未安装（仿真功能不可用）",
            "pip install mavsdk")


def _check_robot_profile() -> CheckResult:
    required = ["SOUL.md", "BODY.md", "MEMORY.md", "SKILLS.md"]
    missing = [f for f in required if not Path(f"robot_profile/{f}").exists()]
    if not missing:
        return CheckResult("Robot Profile", "ok", f"{len(required)} 个文档就绪")
    return CheckResult("Robot Profile", "warn",
        f"缺少: {', '.join(missing)}",
        "这些文档会在首次启动时自动生成")


# ── 入口函数 ──────────────────────────────────────────────

def run_preflight() -> PreflightReport:
    """执行全部自检，返回报告"""
    # 先加载 .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    report = PreflightReport()
    checks = [
        _check_python,
        _check_dependencies,
        _check_env,
        _check_llm,
        _check_web_ui,
        _check_simulation,
        _check_robot_profile,
    ]

    for check_fn in checks:
        try:
            result = check_fn()
        except Exception as e:
            result = CheckResult(check_fn.__name__, "fail", f"检查异常: {e}")
        report.results.append(result)

    # 打印报告
    print(str(report))
    return report


if __name__ == "__main__":
    run_preflight()
