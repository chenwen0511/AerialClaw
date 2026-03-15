"""
core/transport.py — AerialClaw 通信抽象层

为所有设备通信提供统一接口，支持：
  - WiFiTransport    : TCP/UDP over WiFi
  - SerialTransport  : 串口通信 (USB/UART)
  - WebSocketTransport: WebSocket（最常用）
  - MockTransport    : 沙箱/测试用，无真实 I/O

使用方式：
    transport = WebSocketTransport("ws://192.168.1.1:8765", token="xxx")
    await transport.connect()
    await transport.send(b"hello")
    data = await transport.receive(timeout=3.0)
    await transport.disconnect()
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from collections import deque
from typing import Optional

from core.errors import AdapterConnectionError, AdapterTimeoutError
from core.logger import get_logger

logger = get_logger(__name__)


# ══════════════════════════════════════════════════════════════
#  抽象基类
# ══════════════════════════════════════════════════════════════


class Transport(ABC):
    """设备通信抽象基类。所有具体 Transport 必须继承并实现全部抽象方法。"""

    @abstractmethod
    async def connect(self) -> bool:
        """
        建立连接。

        Returns:
            True 表示连接成功。

        Raises:
            AdapterConnectionError: 连接失败。
        """
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接，释放资源。"""
        ...

    @abstractmethod
    async def send(self, data: bytes) -> bool:
        """
        发送原始字节。

        Args:
            data: 待发送字节。

        Returns:
            True 表示发送成功。

        Raises:
            AdapterConnectionError: 未连接时调用。
            AdapterTimeoutError: 发送超时。
        """
        ...

    @abstractmethod
    async def receive(self, timeout: float = 5.0) -> Optional[bytes]:
        """
        接收一条消息。

        Args:
            timeout: 等待超时（秒）。

        Returns:
            收到的字节，超时返回 None。

        Raises:
            AdapterConnectionError: 未连接时调用。
        """
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """返回当前连接状态。"""
        ...

    def __repr__(self) -> str:
        status = "connected" if self.is_connected() else "disconnected"
        return f"<{self.__class__.__name__} [{status}]>"


# ══════════════════════════════════════════════════════════════
#  WiFiTransport — TCP/UDP over WiFi
# ══════════════════════════════════════════════════════════════


class WiFiTransport(Transport):
    """
    TCP/UDP over WiFi 通信。

    Args:
        host:     目标主机 IP 或域名。
        port:     目标端口。
        protocol: 'tcp'（默认）或 'udp'。
        timeout:  连接/发送超时（秒），默认 5.0。
    """

    def __init__(
        self,
        host: str,
        port: int,
        protocol: str = "tcp",
        timeout: float = 5.0,
    ) -> None:
        if protocol not in ("tcp", "udp"):
            raise ValueError(f"不支持的协议: {protocol}，仅支持 'tcp' / 'udp'")
        self._host = host
        self._port = port
        self._protocol = protocol
        self._timeout = timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False

    # ── 生命周期 ─────────────────────────────────────────────

    async def connect(self) -> bool:
        """建立 TCP 连接（UDP 仅记录目标地址，不实际握手）。"""
        if self._connected:
            return True
        try:
            if self._protocol == "tcp":
                self._reader, self._writer = await asyncio.wait_for(
                    asyncio.open_connection(self._host, self._port),
                    timeout=self._timeout,
                )
            # UDP 不需要握手，send 时直接发
            self._connected = True
            logger.info(
                "WiFiTransport 已连接 [%s] %s:%s",
                self._protocol.upper(), self._host, self._port,
            )
            return True
        except asyncio.TimeoutError as e:
            raise AdapterTimeoutError(
                f"WiFi 连接超时: {self._host}:{self._port}",
                fix_hint="检查目标设备 IP 和端口，确认防火墙未拦截",
            ) from e
        except OSError as e:
            raise AdapterConnectionError(
                f"WiFi 连接失败: {self._host}:{self._port} — {e}",
                fix_hint="确认设备已开机，且与本机在同一网络",
            ) from e

    async def disconnect(self) -> None:
        """关闭 TCP 连接。"""
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception as e:
                logger.warning("WiFiTransport 断开时异常: %s", e)
            finally:
                self._reader = None
                self._writer = None
        logger.info("WiFiTransport 已断开 %s:%s", self._host, self._port)

    # ── I/O ──────────────────────────────────────────────────

    async def send(self, data: bytes) -> bool:
        """通过 TCP 发送字节流（UDP 暂不支持）。"""
        self._assert_connected()
        try:
            if self._protocol == "tcp" and self._writer:
                self._writer.write(data)
                await asyncio.wait_for(self._writer.drain(), timeout=self._timeout)
                return True
            logger.warning("WiFiTransport UDP send 尚未实现")
            return False
        except asyncio.TimeoutError as e:
            raise AdapterTimeoutError(
                "WiFi 发送超时",
                fix_hint="网络拥塞或设备无响应",
            ) from e
        except OSError as e:
            self._connected = False
            raise AdapterConnectionError(
                f"WiFi 发送失败: {e}",
                fix_hint="连接已断开，请重新 connect()",
            ) from e

    async def receive(self, timeout: float = 5.0) -> Optional[bytes]:
        """从 TCP 流读取最多 4096 字节。"""
        self._assert_connected()
        if self._protocol != "tcp" or self._reader is None:
            return None
        try:
            data = await asyncio.wait_for(
                self._reader.read(4096), timeout=timeout
            )
            return data if data else None
        except asyncio.TimeoutError:
            return None
        except OSError as e:
            self._connected = False
            logger.error("WiFiTransport 接收错误: %s", e)
            return None

    def is_connected(self) -> bool:
        return self._connected

    # ── 内部 ─────────────────────────────────────────────────

    def _assert_connected(self) -> None:
        if not self._connected:
            raise AdapterConnectionError(
                "WiFiTransport 未连接，请先调用 connect()",
                fix_hint="await transport.connect()",
            )

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<WiFiTransport [{status}] {self._protocol.upper()} {self._host}:{self._port}>"


# ══════════════════════════════════════════════════════════════
#  SerialTransport — 串口通信 (USB/UART)
# ══════════════════════════════════════════════════════════════


class SerialTransport(Transport):
    """
    串口通信（USB / UART）。

    依赖：pyserial-asyncio（可选，未安装时 connect() 抛 AdapterConnectionError）

    Args:
        port:     串口设备路径，如 '/dev/ttyUSB0' 或 'COM3'。
        baudrate: 波特率，默认 115200。
        timeout:  读写超时（秒），默认 2.0。
    """

    def __init__(
        self,
        port: str,
        baudrate: int = 115200,
        timeout: float = 2.0,
    ) -> None:
        self._port = port
        self._baudrate = baudrate
        self._timeout = timeout
        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._connected = False

    # ── 生命周期 ─────────────────────────────────────────────

    async def connect(self) -> bool:
        """打开串口。需要 pyserial-asyncio 包。"""
        if self._connected:
            return True
        try:
            import serial_asyncio  # type: ignore
        except ImportError as e:
            raise AdapterConnectionError(
                "缺少 pyserial-asyncio 依赖",
                fix_hint="pip install pyserial-asyncio",
            ) from e
        try:
            self._reader, self._writer = await serial_asyncio.open_serial_connection(
                url=self._port, baudrate=self._baudrate
            )
            self._connected = True
            logger.info(
                "SerialTransport 已连接 %s @ %s baud",
                self._port, self._baudrate,
            )
            return True
        except Exception as e:
            raise AdapterConnectionError(
                f"串口连接失败: {self._port} — {e}",
                fix_hint="确认串口路径正确，设备已接入，驱动已安装",
            ) from e

    async def disconnect(self) -> None:
        """关闭串口。"""
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
            except Exception as e:
                logger.warning("SerialTransport 断开时异常: %s", e)
            finally:
                self._reader = None
                self._writer = None
        logger.info("SerialTransport 已断开 %s", self._port)

    # ── I/O ──────────────────────────────────────────────────

    async def send(self, data: bytes) -> bool:
        """向串口写入字节。"""
        self._assert_connected()
        try:
            self._writer.write(data)  # type: ignore[union-attr]
            await asyncio.wait_for(
                self._writer.drain(), timeout=self._timeout  # type: ignore[union-attr]
            )
            return True
        except asyncio.TimeoutError as e:
            raise AdapterTimeoutError(
                "串口发送超时",
                fix_hint="检查波特率是否匹配设备配置",
            ) from e
        except Exception as e:
            self._connected = False
            raise AdapterConnectionError(
                f"串口发送失败: {e}",
                fix_hint="串口可能已断开",
            ) from e

    async def receive(self, timeout: float = 5.0) -> Optional[bytes]:
        """从串口读取最多 1024 字节。"""
        self._assert_connected()
        if self._reader is None:
            return None
        try:
            data = await asyncio.wait_for(
                self._reader.read(1024), timeout=timeout
            )
            return data if data else None
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            self._connected = False
            logger.error("SerialTransport 接收错误: %s", e)
            return None

    def is_connected(self) -> bool:
        return self._connected

    def _assert_connected(self) -> None:
        if not self._connected:
            raise AdapterConnectionError(
                "SerialTransport 未连接，请先调用 connect()",
                fix_hint="await transport.connect()",
            )

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<SerialTransport [{status}] {self._port} @ {self._baudrate}>"


# ══════════════════════════════════════════════════════════════
#  WebSocketTransport — WebSocket 通信（最常用）
# ══════════════════════════════════════════════════════════════


class WebSocketTransport(Transport):
    """
    WebSocket 通信。AerialClaw 标准设备协议首选传输层。

    依赖：websockets >= 11.0

    Args:
        url:   WebSocket 地址，如 'ws://192.168.1.1:8765'。
        token: 认证令牌，连接时作为 Authorization header 发送。
        ping_interval: 心跳间隔（秒），默认 20.0，None 禁用。
        ping_timeout:  心跳超时（秒），默认 10.0。
    """

    def __init__(
        self,
        url: str,
        token: str = "",
        ping_interval: Optional[float] = 20.0,
        ping_timeout: Optional[float] = 10.0,
    ) -> None:
        self._url = url
        self._token = token
        self._ping_interval = ping_interval
        self._ping_timeout = ping_timeout
        self._ws = None  # websockets.WebSocketClientProtocol
        self._connected = False
        self._recv_queue: deque[bytes] = deque(maxlen=256)
        self._recv_event = asyncio.Event()

    # ── 生命周期 ─────────────────────────────────────────────

    async def connect(self) -> bool:
        """建立 WebSocket 连接。"""
        if self._connected:
            return True
        try:
            import websockets  # type: ignore
        except ImportError as e:
            raise AdapterConnectionError(
                "缺少 websockets 依赖",
                fix_hint="pip install websockets",
            ) from e
        try:
            headers = {}
            if self._token:
                headers["Authorization"] = f"Bearer {self._token}"
            self._ws = await websockets.connect(
                self._url,
                additional_headers=headers,
                ping_interval=self._ping_interval,
                ping_timeout=self._ping_timeout,
            )
            self._connected = True
            logger.info("WebSocketTransport 已连接 %s", self._url)
            return True
        except Exception as e:
            raise AdapterConnectionError(
                f"WebSocket 连接失败: {self._url} — {e}",
                fix_hint="确认服务端已启动，URL 格式为 ws:// 或 wss://",
            ) from e

    async def disconnect(self) -> None:
        """关闭 WebSocket 连接。"""
        self._connected = False
        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.warning("WebSocketTransport 断开时异常: %s", e)
            finally:
                self._ws = None
        logger.info("WebSocketTransport 已断开 %s", self._url)

    # ── I/O ──────────────────────────────────────────────────

    async def send(self, data: bytes) -> bool:
        """通过 WebSocket 发送字节。"""
        self._assert_connected()
        try:
            await self._ws.send(data)  # type: ignore[union-attr]
            return True
        except Exception as e:
            self._connected = False
            raise AdapterConnectionError(
                f"WebSocket 发送失败: {e}",
                fix_hint="连接已断开，请重新 connect()",
            ) from e

    async def receive(self, timeout: float = 5.0) -> Optional[bytes]:
        """
        接收一条 WebSocket 消息。

        优先从内部队列取（由后台 _recv_loop 填充）；
        若队列为空则直接等待。
        """
        self._assert_connected()
        if self._recv_queue:
            return self._recv_queue.popleft()
        try:
            msg = await asyncio.wait_for(
                self._ws.recv(), timeout=timeout  # type: ignore[union-attr]
            )
            if isinstance(msg, str):
                return msg.encode()
            return msg
        except asyncio.TimeoutError:
            return None
        except Exception as e:
            self._connected = False
            logger.error("WebSocketTransport 接收错误: %s", e)
            return None

    def is_connected(self) -> bool:
        return self._connected

    def _assert_connected(self) -> None:
        if not self._connected:
            raise AdapterConnectionError(
                "WebSocketTransport 未连接，请先调用 connect()",
                fix_hint="await transport.connect()",
            )

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<WebSocketTransport [{status}] {self._url}>"


# ══════════════════════════════════════════════════════════════
#  MockTransport — 沙箱/测试专用
# ══════════════════════════════════════════════════════════════


class MockTransport(Transport):
    """
    Mock Transport，用于沙箱测试和单元测试。

    不做任何真实 I/O：
    - send() 将数据追加到 sent_messages 列表
    - receive() 从 inject_messages 队列取数据（可提前注入）
    - 支持模拟断连场景（force_disconnect=True）

    Args:
        inject_messages: 预注入的接收消息列表。
        force_disconnect: 设为 True 时，send/receive 均抛 AdapterConnectionError。
    """

    def __init__(
        self,
        inject_messages: Optional[list[bytes]] = None,
        force_disconnect: bool = False,
    ) -> None:
        self._connected = False
        self._force_disconnect = force_disconnect
        self.sent_messages: list[bytes] = []
        self._recv_queue: deque[bytes] = deque(inject_messages or [])

    async def connect(self) -> bool:
        if self._force_disconnect:
            raise AdapterConnectionError(
                "MockTransport 模拟连接失败",
                fix_hint="设置 force_disconnect=False 以允许连接",
            )
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def send(self, data: bytes) -> bool:
        if self._force_disconnect or not self._connected:
            raise AdapterConnectionError("MockTransport 未连接")
        self.sent_messages.append(data)
        return True

    async def receive(self, timeout: float = 5.0) -> Optional[bytes]:
        if self._force_disconnect or not self._connected:
            raise AdapterConnectionError("MockTransport 未连接")
        if self._recv_queue:
            return self._recv_queue.popleft()
        await asyncio.sleep(min(timeout, 0.01))  # 模拟等待
        return None

    def inject(self, data: bytes) -> None:
        """运行时注入一条待接收消息。"""
        self._recv_queue.append(data)

    def is_connected(self) -> bool:
        return self._connected

    def __repr__(self) -> str:
        status = "connected" if self._connected else "disconnected"
        return f"<MockTransport [{status}] sent={len(self.sent_messages)} queued={len(self._recv_queue)}>"
