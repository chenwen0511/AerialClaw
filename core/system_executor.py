"""
core/system_executor.py — 系统执行器

在安全过滤下执行本地系统命令，封装 shell 执行、包安装、文件读写、网络连通性测试。
"""

from __future__ import annotations

import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from core.errors import CommandBlockedError
from core.logger import get_logger

logger = get_logger(__name__)

# 危险路径前缀黑名单（写入/删除操作拦截）
_DANGEROUS_PATH_PREFIXES = (
    "/etc",
    "/usr",
    "/bin",
    "/sbin",
    "/lib",
    "/lib64",
    "/boot",
    "/sys",
    "/proc",
    "/dev",
    "/root",
    "/var/run",
    "/var/log",
)


@dataclass
class ExecutionResult:
    """命令执行结果"""
    success: bool
    stdout: str
    stderr: str
    exit_code: int
    cost_time: float   # 执行耗时（秒）


class SystemExecutor:
    """
    系统执行器。

    所有 shell 命令经过 CommandFilter 安全过滤；
    文件写入路径经危险路径黑名单检查。

    用法示例::

        executor = SystemExecutor()
        result = executor.run_shell("echo hello")
        result = executor.install_package("requests")
        result = executor.write_file("/tmp/test.txt", "hello")
        ok = executor.test_connection("192.168.1.1", 8080)
    """

    def __init__(self, safety_config=None) -> None:
        """
        Args:
            safety_config: SafetyConfig 实例；若为 None 则自动加载全局配置
        """
        from core.safety.config import get_safety_config
        from core.safety.command_filter import CommandFilter

        self._config = safety_config or get_safety_config()
        self._filter = CommandFilter(self._config)

    # ── Shell 执行 ─────────────────────────────────────────────

    def run_shell(self, cmd: str, timeout: int = 30) -> ExecutionResult:
        """
        执行 shell 命令。

        命令先经过 CommandFilter 过滤，仅 pass 级别允许直接执行；
        review/block 级别均拒绝。

        Args:
            cmd:     shell 命令字符串
            timeout: 超时时间（秒），默认 30

        Returns:
            ExecutionResult

        Raises:
            CommandBlockedError: 命令被安全策略拦截
        """
        # 取命令主词（第一个 token）用于过滤检查
        primary = cmd.strip().split()[0] if cmd.strip() else ""
        filter_result = self._filter.check(primary, {"raw_cmd": cmd})

        if not filter_result.allowed:
            level = filter_result.level
            reason = filter_result.reason
            logger.warning("命令被拦截 [%s]: %s | 原因: %s", level, cmd, reason)
            raise CommandBlockedError(
                message=f"命令执行被拒绝: {cmd}",
                fix_hint=f"原因: {reason}（level={level}）",
            )

        logger.debug("执行命令: %s", cmd)
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            cost = time.monotonic() - start
            result = ExecutionResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                cost_time=round(cost, 4),
            )
            if result.success:
                logger.debug("命令成功 (%.2fs): %s", cost, cmd)
            else:
                logger.warning("命令失败 exit=%d: %s | %s", proc.returncode, cmd, proc.stderr[:200])
            return result

        except subprocess.TimeoutExpired:
            cost = time.monotonic() - start
            logger.error("命令超时 (>%ds): %s", timeout, cmd)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=f"命令执行超时（>{timeout}s）",
                exit_code=-1,
                cost_time=round(cost, 4),
            )
        except Exception as e:
            cost = time.monotonic() - start
            logger.error("命令执行异常: %s | %s", cmd, e)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                cost_time=round(cost, 4),
            )

    # ── 包安装 ────────────────────────────────────────────────

    def install_package(self, package: str, manager: str = "pip") -> ExecutionResult:
        """
        安装 Python / 系统依赖包。

        Args:
            package: 包名（如 "requests==2.31.0"）
            manager: 包管理器，支持 "pip" | "pip3" | "apt" | "brew"

        Returns:
            ExecutionResult
        """
        _supported = {"pip", "pip3", "apt", "brew"}
        if manager not in _supported:
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=f"不支持的包管理器: {manager}，支持: {_supported}",
                exit_code=-1,
                cost_time=0.0,
            )

        if manager in ("pip", "pip3"):
            cmd = f"{manager} install {package} --quiet"
        elif manager == "apt":
            cmd = f"apt-get install -y {package}"
        else:  # brew
            cmd = f"brew install {package}"

        logger.info("安装包: %s (via %s)", package, manager)

        # 包安装命令绕过一般过滤（pip/apt/brew 属于受信操作）
        start = time.monotonic()
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
            cost = time.monotonic() - start
            result = ExecutionResult(
                success=proc.returncode == 0,
                stdout=proc.stdout,
                stderr=proc.stderr,
                exit_code=proc.returncode,
                cost_time=round(cost, 4),
            )
            if result.success:
                logger.info("包安装成功: %s (%.1fs)", package, cost)
            else:
                logger.error("包安装失败: %s | %s", package, proc.stderr[:300])
            return result
        except subprocess.TimeoutExpired:
            cost = time.monotonic() - start
            return ExecutionResult(
                success=False,
                stdout="",
                stderr="包安装超时（>120s）",
                exit_code=-1,
                cost_time=round(cost, 4),
            )
        except Exception as e:
            cost = time.monotonic() - start
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                cost_time=round(cost, 4),
            )

    # ── 文件写入 ──────────────────────────────────────────────

    def write_file(self, path: str, content: str) -> ExecutionResult:
        """
        安全写入文件。

        危险路径（/etc、/usr 等系统目录）会被拦截。

        Args:
            path:    目标文件路径
            content: 文件内容

        Returns:
            ExecutionResult

        Raises:
            CommandBlockedError: 目标路径属于危险系统目录
        """
        resolved = str(Path(path).resolve())
        self._check_path_safety(resolved, operation="写入")

        start = time.monotonic()
        try:
            target = Path(resolved)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            cost = time.monotonic() - start
            logger.debug("文件写入成功: %s (%d 字节)", resolved, len(content.encode()))
            return ExecutionResult(
                success=True,
                stdout=f"已写入: {resolved}",
                stderr="",
                exit_code=0,
                cost_time=round(cost, 4),
            )
        except Exception as e:
            cost = time.monotonic() - start
            logger.error("文件写入失败: %s | %s", path, e)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=1,
                cost_time=round(cost, 4),
            )

    # ── 文件读取 ──────────────────────────────────────────────

    def read_file(self, path: str) -> ExecutionResult:
        """
        读取文件内容。

        Args:
            path: 文件路径

        Returns:
            ExecutionResult（stdout 为文件内容）
        """
        start = time.monotonic()
        try:
            target = Path(path).resolve()
            if not target.exists():
                cost = time.monotonic() - start
                return ExecutionResult(
                    success=False,
                    stdout="",
                    stderr=f"文件不存在: {path}",
                    exit_code=1,
                    cost_time=round(cost, 4),
                )
            content = target.read_text(encoding="utf-8", errors="replace")
            cost = time.monotonic() - start
            logger.debug("文件读取成功: %s (%d 字节)", path, len(content.encode()))
            return ExecutionResult(
                success=True,
                stdout=content,
                stderr="",
                exit_code=0,
                cost_time=round(cost, 4),
            )
        except Exception as e:
            cost = time.monotonic() - start
            logger.error("文件读取失败: %s | %s", path, e)
            return ExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=1,
                cost_time=round(cost, 4),
            )

    # ── 网络连通性 ────────────────────────────────────────────

    def test_connection(self, host: str, port: int) -> bool:
        """
        测试 TCP 端口连通性。

        Args:
            host: 目标主机名或 IP
            port: 目标端口

        Returns:
            bool: True 表示可达
        """
        try:
            with socket.create_connection((host, port), timeout=5):
                logger.debug("连通性测试成功: %s:%d", host, port)
                return True
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            logger.debug("连通性测试失败: %s:%d | %s", host, port, e)
            return False

    # ── 内部工具 ──────────────────────────────────────────────

    def _check_path_safety(self, resolved_path: str, operation: str = "访问") -> None:
        """
        检查路径是否属于危险系统目录。

        Args:
            resolved_path: Path.resolve() 后的绝对路径
            operation:     操作名称（用于日志）

        Raises:
            CommandBlockedError: 路径命中危险前缀
        """
        for prefix in _DANGEROUS_PATH_PREFIXES:
            if resolved_path == prefix or resolved_path.startswith(prefix + "/"):
                logger.warning("危险路径被拦截 [%s]: %s", operation, resolved_path)
                raise CommandBlockedError(
                    message=f"路径 {operation} 被拒绝: {resolved_path}",
                    fix_hint=f"目标路径属于受保护系统目录（{prefix}），请使用用户目录或项目目录",
                )
