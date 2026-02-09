"""数据模型定义

定义微信自动化相关的数据结构，包括任务、消息、定位结果等。

数据模型：
- WeChatConfig: 微信窗口和运行环境配置
- Message: 消息结构（发送者、内容、时间戳等）
- LocateResult: 定位结果（坐标、置信度、定位方法）
- FlowResult: 流程执行结果（成功/失败、错误信息、执行时间）

注意事项：
1. 所有模型应使用 dataclass 或 Pydantic 定义，便于序列化
2. 时间戳统一使用 UTC 时间，格式为 ISO 8601
3. 坐标系统一使用窗口内相对坐标（左上角为原点）
4. 置信度范围：0.0-1.0，0.8以上认为可靠
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class TaskType(Enum):
    """任务类型枚举"""
    SEND_MESSAGE = "send_message"
    READ_MESSAGES = "read_messages"
    SEARCH_CONTACT = "search_contact"
    OPEN_CHAT = "open_chat"
    REFRESH_CHAT_LIST = "refresh_chat_list"


class LocateMethod(Enum):
    """定位方法枚举"""
    TEMPLATE_MATCH = "template_match"
    OCR_KEYWORD = "ocr_keyword"
    COLOR_MATCH = "color_match"
    COMBINED = "combined"


@dataclass
class WeChatConfig:
    """微信窗口和运行环境配置
    
    属性：
        window_position: 窗口位置 (x, y)，左上角坐标
        window_size: 窗口大小 (width, height)
        window_title: 窗口标题，用于查找窗口
        dpi_scale: DPI缩放比例，必须为100
        display_resolution: 显示器分辨率 (width, height)
        language: 微信界面语言，必须为简体中文
        input_method: 输入法策略（clipboard/direct）
    """
    window_position: tuple[int, int] = (0, 0)
    window_size: tuple[int, int] = (1200, 800)
    window_title: str = "微信"
    dpi_scale: int = 100
    display_resolution: tuple[int, int] = (1920, 1080)
    language: str = "zh_CN"
    input_method: str = "clipboard"


@dataclass
class Message:
    """消息结构
    
    属性：
        sender: 发送者名称
        content: 消息内容
        timestamp: 时间戳
        message_type: 消息类型（text/image/file等）
        is_sent: 是否为发送的消息（True）或接收的消息（False）
    """
    sender: str
    content: str
    timestamp: datetime
    message_type: str = "text"
    is_sent: bool = False


@dataclass
class LocateResult:
    """定位结果
    
    属性：
        success: 是否定位成功
        x: X坐标
        y: Y坐标
        confidence: 置信度（0.0-1.0）
        method: 定位方法
        region: 定位区域 (x, y, width, height)
        error_message: 错误信息（如果失败）
    """
    success: bool
    x: Optional[int] = None
    y: Optional[int] = None
    confidence: float = 0.0
    method: Optional[LocateMethod] = None
    region: Optional[tuple[int, int, int, int]] = None
    error_message: Optional[str] = None


@dataclass
class ContactLocateResult:
    """带联系人标识的定位结果
    
    属性：
        locate_result: 定位结果
        contact_name: 联系人名称
        contact_id: 联系人ID（可选）
    """
    locate_result: LocateResult
    contact_name: str
    contact_id: Optional[str] = None


@dataclass
class FlowResult:
    """流程执行结果
    
    属性：
        success: 是否执行成功
        task_type: 任务类型
        execution_time: 执行时间（秒）
        error_message: 错误信息（如果失败）
        data: 返回数据（消息列表、联系人列表等）
        screenshot_path: 调试截图路径（如果失败）
    """
    success: bool
    task_type: TaskType
    execution_time: float
    error_message: Optional[str] = None
    data: Optional[Any] = None
    screenshot_path: Optional[str] = None
