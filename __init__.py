"""微信自动化模块

提供微信窗口自动化操作功能，包括消息发送、接收、联系人管理等。

主要模块：
- controller: 对外接口层，提供高级API
- screen: 屏幕操作，截图和DPI处理
- locator: 定位服务，模板匹配和OCR定位
- actions: 基础操作，点击、输入、粘贴等
- flows: 流程编排，业务逻辑组合
- models: 数据模型定义
- config: 配置管理

使用示例：
    from wechat import WeChatController
    
    controller = WeChatController()
    controller.send_text("联系人名称", "消息内容")
    messages = controller.read_new_messages()
"""

# 导出配置类与校验异常（Phase 1：硬失败）
from .config import WeChatAutomationConfig, ConfigValidationError

# 导出数据模型
from .models import (
    WeChatConfig,
    TaskType,
    Message,
    LocateResult,
    LocateMethod,
    FlowResult,
)

# 导出屏幕操作函数（常用）
from .screen import (
    get_wechat_hwnd,
    get_window_client_bbox,
    capture_window,
    get_dpi_scale,
    window_to_screen_coords,
)

# 导出基础操作函数
from .actions import (
    activate_window,
    click,
    hotkey,
    paste_text,
    type_text,
    human_delay,
    wait,
    scroll,
)

# 导出定位服务函数
from .locator import (
    match_template,
    match_all_templates,
    ocr_region,
    validate_location,
)

# 导出控制器
from .controller import (
    WeChatController,
    ControllerResult,
    ErrorCode,
    WeChatControllerError,
    WeChatNotReadyError,
    ContactNotFoundError,
    SendMessageError,
    ReadMessageError,
)

# 导出消息通道
from .message_channel import (
    WeChatMessageChannel,
    MessageEvent,
)

__all__ = [
    # 配置
    'WeChatAutomationConfig',
    'ConfigValidationError',
    # 数据模型
    'WeChatConfig',
    'TaskType',
    'Message',
    'LocateResult',
    'LocateMethod',
    'FlowResult',
    # 屏幕操作
    'get_wechat_hwnd',
    'get_window_client_bbox',
    'capture_window',
    'get_dpi_scale',
    'window_to_screen_coords',
    # 基础操作
    'activate_window',
    'click',
    'hotkey',
    'paste_text',
    'type_text',
    'human_delay',
    'wait',
    'scroll',
    # 定位服务
    'match_template',
    'match_all_templates',
    'ocr_region',
    'validate_location',
    # 控制器
    'WeChatController',
    'ControllerResult',
    'ErrorCode',
    'WeChatControllerError',
    'WeChatNotReadyError',
    'ContactNotFoundError',
    'SendMessageError',
    'ReadMessageError',
    # 消息通道
    'WeChatMessageChannel',
    'MessageEvent',
]
