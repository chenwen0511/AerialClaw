"""
core/code_generator.py — Adapter 代码生成器

LLM 生成 Adapter 代码，沙箱测试，自动修复，部署。
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Optional

from core.device_manager import DeviceInfo
from core.errors import LLMResponseError, SandboxExecutionError
from core.logger import get_logger
from core.safety.sandbox import SandboxResult, get_sandbox

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
#  BaseAdapter 接口摘要（嵌入 prompt）
# ══════════════════════════════════════════════════════════════

_BASE_ADAPTER_INTERFACE = """\
# adapters/base_adapter.py — 必须继承的接口（只读，勿修改）

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional
import numpy as np
from enum import Enum

class RobotType(Enum):
    DRONE = "drone"
    GROUND_VEHICLE = "ground_vehicle"
    ARM = "arm"
    SENSOR = "sensor"

@dataclass
class SensorData:
    timestamp: float
    frame_id: str = "base_link"

@dataclass
class LidarData(SensorData):
    ranges: np.ndarray = None   # [N] distance array
    angles: np.ndarray = None   # [N] angle array

@dataclass
class CameraFrame(SensorData):
    image: np.ndarray = None    # HxWx3
    width: int = 0
    height: int = 0

@dataclass
class IMUData(SensorData):
    accel: np.ndarray = None    # [x, y, z] m/s²
    gyro: np.ndarray = None     # [roll, pitch, yaw] rad/s

@dataclass
class GPSData(SensorData):
    latitude: float = 0.0
    longitude: float = 0.0
    altitude: float = 0.0

class BaseAdapter(ABC):
    def __init__(self, robot_id: str, robot_type: RobotType):
        self.robot_id = robot_id
        self.robot_type = robot_type
        self.is_connected = False
        self.state = {}

    @abstractmethod
    def connect(self) -> bool: ...

    @abstractmethod
    def disconnect(self) -> bool: ...

    @abstractmethod
    def get_sensor_data(self) -> Dict[str, SensorData]: ...

    @abstractmethod
    def execute_command(self, command: str, params: Dict[str, Any]) -> bool: ...

    @abstractmethod
    def get_status(self) -> Dict[str, Any]: ...

    def is_healthy(self) -> bool:
        return len(self.get_status().get("errors", [])) == 0

    def get_capabilities(self) -> list[str]:
        return []
"""

# ══════════════════════════════════════════════════════════════
#  Prompt 模板
# ══════════════════════════════════════════════════════════════

_GENERATE_SYSTEM = """\
你是 AerialClaw 机器人中间件的 Adapter 代码生成专家。

CRITICAL: 只输出纯 Python 代码，不要包含任何解释、注释说明或 Markdown 代码块。
CRITICAL: 生成的类必须继承 BaseAdapter，实现全部 5 个抽象方法。
CRITICAL: 文件顶部必须包含必要的 import，包括 from adapters.base_adapter import BaseAdapter, RobotType。
CRITICAL: 类名格式为 {DeviceType}Adapter（驼峰命名）。

要求：
- connect() 使用设备提供的 API/协议建立连接，返回 bool
- disconnect() 安全断连，返回 bool
- get_sensor_data() 返回 Dict[str, SensorData]，key 为传感器类型
- execute_command() 转换 AerialClaw 指令到设备原生 API 调用，返回 bool
- get_status() 返回包含 battery/position/state/errors 的字典
- get_capabilities() 返回该设备支持的指令列表
"""

_FIX_SYSTEM = """\
你是 Python 代码调试专家。

CRITICAL: 只输出修复后的完整 Python 代码，不要包含任何解释或 Markdown 代码块。
CRITICAL: 保持原有类结构和接口不变，只修复导致错误的部分。
"""


# ══════════════════════════════════════════════════════════════
#  AdapterGenerator
# ══════════════════════════════════════════════════════════════


class AdapterGenerator:
    """
    LLM 驱动的 Adapter 代码生成器。

    流程：generate → test_in_sandbox → auto_fix → deploy
    """

    def __init__(self, llm_client, sandbox=None) -> None:
        """
        Args:
            llm_client: LLMClient 实例
            sandbox: Sandbox 实例，None 时自动检测最安全可用沙箱
        """
        self._llm = llm_client
        self._sandbox = sandbox or get_sandbox("auto")
        logger.info("代码生成器初始化 | 沙箱类型: %s", self._sandbox.name)

    # ── 生成 ──────────────────────────────────────────────

    def generate(self, device_info: DeviceInfo, api_docs: str = "") -> str:
        """
        调用 LLM 生成设备 Adapter 代码。

        Args:
            device_info: 设备信息
            api_docs: 设备 API/SDK 文档（可选）

        Returns:
            生成的 Python 源码字符串

        Raises:
            LLMResponseError: LLM 返回内容不包含有效代码
        """
        logger.info("生成 Adapter 代码: %s (%s)", device_info.device_id, device_info.device_type)

        user_prompt = self._build_generate_prompt(device_info, api_docs)
        messages = [
            {"role": "system", "content": _GENERATE_SYSTEM},
            {"role": "user", "content": user_prompt},
        ]

        raw = self._llm.chat(messages)
        code = self._strip_code_block(raw)

        if "class " not in code or "BaseAdapter" not in code:
            raise LLMResponseError(
                "LLM 未生成有效的 Adapter 类代码",
                fix_hint="检查 LLM 是否理解了 BaseAdapter 接口要求",
            )

        logger.debug("代码生成完成 (%d 行)", code.count("\n"))
        return code

    # ── 沙箱测试 ──────────────────────────────────────────

    def test_in_sandbox(self, code: str) -> SandboxResult:
        """
        在沙箱中做语法 + 基础实例化测试。

        Args:
            code: 要测试的 Python 源码

        Returns:
            SandboxResult
        """
        test_harness = textwrap.dedent("""\
            import sys, ast

            # 语法检查
            try:
                ast.parse(code_under_test)
            except SyntaxError as e:
                print(f"SYNTAX_ERROR: {e}", file=sys.stderr)
                sys.exit(1)

            print("SYNTAX_OK")
        """)

        # 将待测代码注入测试 harness
        escaped = code.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        full_code = f'code_under_test = """{escaped}"""\n' + test_harness

        logger.debug("沙箱测试开始 [%s]", self._sandbox.name)
        result = self._sandbox.execute(full_code, timeout=15)

        if result.success:
            logger.info("沙箱测试通过 (%.2fs)", result.execution_time)
        else:
            logger.warning("沙箱测试失败: %s", result.stderr[:200])

        return result

    # ── 自动修复 ──────────────────────────────────────────

    def auto_fix(self, code: str, error: str, max_retries: int = 3) -> str:
        """
        LLM 读取错误信息自动修复代码。

        Args:
            code: 有问题的 Python 源码
            error: 错误信息（stderr 或异常 traceback）
            max_retries: 最大重试次数

        Returns:
            修复后的代码（若所有重试均失败，返回最后一次修复结果）
        """
        current_code = code
        for attempt in range(1, max_retries + 1):
            logger.info("自动修复 (第 %d/%d 次)...", attempt, max_retries)

            messages = [
                {"role": "system", "content": _FIX_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        f"以下 Python 代码执行出错，请修复：\n\n"
                        f"错误信息:\n{error}\n\n"
                        f"原始代码:\n{current_code}"
                    ),
                },
            ]

            raw = self._llm.chat(messages)
            fixed_code = self._strip_code_block(raw)

            result = self.test_in_sandbox(fixed_code)
            if result.success:
                logger.info("自动修复成功 (第 %d 次)", attempt)
                return fixed_code

            # 用新错误继续下一轮修复
            error = result.stderr
            current_code = fixed_code

        logger.warning("自动修复 %d 次后仍未通过沙箱测试", max_retries)
        return current_code

    # ── 部署 ──────────────────────────────────────────────

    def deploy(self, code: str, target_path: str) -> None:
        """
        将生成的 Adapter 代码写入目标文件。

        Args:
            code: Python 源码
            target_path: 目标文件路径（绝对路径或相对路径）

        Raises:
            OSError: 文件写入失败
        """
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(code, encoding="utf-8")
        logger.info("Adapter 已部署: %s (%d 字节)", path, len(code.encode()))

    # ── 完整流程 ──────────────────────────────────────────

    def generate_and_deploy(
        self,
        device_info: DeviceInfo,
        target_path: str,
        api_docs: str = "",
        auto_fix: bool = True,
        max_retries: int = 3,
    ) -> str:
        """
        一键完成：生成 → 测试 → 修复 → 部署。

        Args:
            device_info: 设备信息
            target_path: 部署目标路径
            api_docs: 设备 API 文档
            auto_fix: 测试失败时是否自动修复
            max_retries: 自动修复最大次数

        Returns:
            最终部署的代码
        """
        code = self.generate(device_info, api_docs)
        result = self.test_in_sandbox(code)

        if not result.success and auto_fix:
            code = self.auto_fix(code, result.stderr, max_retries=max_retries)
        elif not result.success:
            raise SandboxExecutionError(
                f"生成的 Adapter 代码沙箱测试失败: {result.stderr[:300]}",
                fix_hint="启用 auto_fix=True 或手动检查生成代码",
            )

        self.deploy(code, target_path)
        return code

    # ── 内部工具 ──────────────────────────────────────────

    def _build_generate_prompt(self, info: DeviceInfo, api_docs: str) -> str:
        import json
        metadata_str = json.dumps(info.metadata, ensure_ascii=False, indent=2) if info.metadata else "{}"
        parts = [
            f"设备 ID: {info.device_id}",
            f"设备类型: {info.device_type}",
            f"能力列表: {', '.join(info.capabilities)}",
            f"传感器: {', '.join(info.sensors)}",
            f"通信协议: {info.protocol}",
            f"元数据:\n{metadata_str}",
            "",
            "BaseAdapter 接口定义（你的类必须继承并实现以下接口）:",
            _BASE_ADAPTER_INTERFACE,
        ]
        if api_docs.strip():
            parts += ["", "设备 API 文档:", api_docs]
        parts += ["", "请生成完整的 Adapter 类代码。"]
        return "\n".join(parts)

    @staticmethod
    def _strip_code_block(raw: str) -> str:
        """去掉 LLM 输出中的 Markdown 代码块标记"""
        import re
        # 优先提取 ```python ... ``` 或 ``` ... ``` 块内的内容
        match = re.search(r"```(?:python)?\s*\n([\s\S]+?)\n```", raw)
        if match:
            return match.group(1).strip()
        # 去掉所有 ``` 标记
        cleaned = re.sub(r"```(?:python)?", "", raw).replace("```", "")
        return cleaned.strip()
