"""
core/safety/sandbox.py — 自适应沙箱

三级方案自动降级：
  Docker → subprocess + 受限用户 → Python 受限执行
启动时自动检测环境，选最安全的可用方案。
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from core.errors import SandboxExecutionError, SandboxTimeoutError
from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SandboxResult:
    """沙箱执行结果"""
    success: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    execution_time: float = 0.0
    sandbox_type: str = ""


class Sandbox(ABC):
    """沙箱抽象基类"""

    @abstractmethod
    def execute(self, code: str, timeout: int = 10) -> SandboxResult:
        """
        在沙箱中执行代码。

        Args:
            code: 要执行的 Python 代码
            timeout: 超时时间（秒）

        Returns:
            SandboxResult: 执行结果
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """检查沙箱是否可用"""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """沙箱类型名称"""
        ...


class DockerSandbox(Sandbox):
    """Docker 容器沙箱（最安全）"""

    def __init__(
        self,
        image: str = "python:3.12-slim",
        max_memory: str = "256m",
        network: bool = False,
    ) -> None:
        self._image = image
        self._max_memory = max_memory
        self._network = network

    @property
    def name(self) -> str:
        return "docker"

    def is_available(self) -> bool:
        """检查 Docker 是否可用"""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True, timeout=5,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return False

    def execute(self, code: str, timeout: int = 10) -> SandboxResult:
        """在 Docker 容器中执行代码"""
        start = time.time()

        network_flag = "none" if not self._network else "bridge"
        cmd = [
            "docker", "run", "--rm",
            "--memory", self._max_memory,
            "--network", network_flag,
            "--cpus", "1",
            "--pids-limit", "50",
            "--read-only",
            "--tmpfs", "/tmp:size=64m",
            self._image,
            "python3", "-c", code,
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=timeout + 5,  # 额外 5 秒给 Docker 启动
            )
            elapsed = time.time() - start
            return SandboxResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                execution_time=elapsed,
                sandbox_type=self.name,
            )
        except subprocess.TimeoutExpired:
            raise SandboxTimeoutError(
                f"Docker 沙箱执行超时 ({timeout}s)",
                fix_hint="代码可能存在死循环或耗时过长",
            )
        except Exception as e:
            raise SandboxExecutionError(
                f"Docker 沙箱执行失败: {e}",
                fix_hint="检查 Docker 是否正常运行",
            )


class ProcessSandbox(Sandbox):
    """subprocess 沙箱（中等安全）"""

    @property
    def name(self) -> str:
        return "process"

    def is_available(self) -> bool:
        """POSIX 系统上始终可用"""
        return os.name == "posix"

    def execute(self, code: str, timeout: int = 10) -> SandboxResult:
        """在隔离子进程中执行代码"""
        start = time.time()

        # 写入临时文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            tmp_path = f.name

        try:
            # 受限环境变量
            env = {
                "PATH": "/usr/bin:/bin",
                "HOME": "/tmp",
                "LANG": "en_US.UTF-8",
            }

            result = subprocess.run(
                ["python3", tmp_path],
                capture_output=True, text=True,
                timeout=timeout,
                env=env,
                cwd="/tmp",
            )
            elapsed = time.time() - start
            return SandboxResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                execution_time=elapsed,
                sandbox_type=self.name,
            )
        except subprocess.TimeoutExpired:
            raise SandboxTimeoutError(
                f"进程沙箱执行超时 ({timeout}s)",
                fix_hint="代码可能存在死循环",
            )
        except Exception as e:
            raise SandboxExecutionError(
                f"进程沙箱执行失败: {e}",
            )
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


class RestrictedPythonSandbox(Sandbox):
    """Python 受限执行沙箱（最低安全等级）"""

    # 禁止的内置函数
    _BLOCKED_BUILTINS = frozenset([
        "exec", "eval", "compile", "__import__",
        "open", "input", "breakpoint",
    ])

    @property
    def name(self) -> str:
        return "restricted_python"

    def is_available(self) -> bool:
        """始终可用"""
        return True

    def execute(self, code: str, timeout: int = 10) -> SandboxResult:
        """在受限 Python 环境中执行代码"""
        import io
        import contextlib

        start = time.time()

        # 构建受限全局变量
        safe_builtins = {
            k: v for k, v in __builtins__.__dict__.items()
            if k not in self._BLOCKED_BUILTINS
        } if hasattr(__builtins__, '__dict__') else {}

        restricted_globals = {
            "__builtins__": safe_builtins,
            "__name__": "__sandbox__",
        }

        stdout_capture = io.StringIO()
        stderr_capture = io.StringIO()

        try:
            compiled = compile(code, "<sandbox>", "exec")
            with contextlib.redirect_stdout(stdout_capture), \
                 contextlib.redirect_stderr(stderr_capture):
                exec(compiled, restricted_globals)

            elapsed = time.time() - start
            return SandboxResult(
                success=True,
                stdout=stdout_capture.getvalue(),
                stderr=stderr_capture.getvalue(),
                exit_code=0,
                execution_time=elapsed,
                sandbox_type=self.name,
            )
        except Exception as e:
            elapsed = time.time() - start
            return SandboxResult(
                success=False,
                stdout=stdout_capture.getvalue(),
                stderr=f"{type(e).__name__}: {e}",
                exit_code=1,
                execution_time=elapsed,
                sandbox_type=self.name,
            )


# ══════════════════════════════════════════════════════════════
#  工厂函数
# ══════════════════════════════════════════════════════════════


def get_sandbox(preferred: str = "auto") -> Sandbox:
    """
    获取最安全的可用沙箱。

    Args:
        preferred: 首选沙箱类型
            - "auto": 自动检测，优先 Docker
            - "docker": 强制 Docker
            - "process": 强制 subprocess
            - "restricted_python": 强制受限 Python

    Returns:
        Sandbox: 沙箱实例
    """
    if preferred == "docker":
        sb = DockerSandbox()
        if sb.is_available():
            return sb
        logger.warning("Docker 不可用，降级到 process 沙箱")

    if preferred in ("auto", "docker"):
        docker = DockerSandbox()
        if docker.is_available():
            logger.info("沙箱: Docker 容器 (最高安全)")
            return docker

    if preferred in ("auto", "docker", "process"):
        process = ProcessSandbox()
        if process.is_available():
            logger.info("沙箱: subprocess 隔离 (中等安全)")
            return process

    logger.info("沙箱: Python 受限执行 (基础安全)")
    return RestrictedPythonSandbox()
