"""微信驱动层（WeChat Driver）

职责：
"像人一样操作微信，但不理解'聊天'含义"

Controller 是纯驱动层，只负责UI操作，不关心消息状态、对话上下文等业务逻辑。

主要接口：
- open_chat(contact): 打开聊天窗口
- send_text(contact, text): 发送文本消息
- read_new_messages(contact, anchor_hash): 读取消息（直接读取，不判断首次/非首次）
- has_new_message(): 检测是否有新消息（使用视觉指纹方法）

设计原则：
1. **纯驱动**：只做UI操作，不做业务判断
   - 不维护消息状态（锚点、去重等）
   - 不区分首次/非首次调用
   - 不关心消息顺序和上下文
2. **简洁直接**：接口简单明了，参数最少
3. **错误处理**：将底层错误转换为可解释的错误码和异常
4. **可观测**：记录详细日志，便于调试

架构分层：
- **第1层：WeChat Driver（本模块）**
  - 负责：UI操作（点击、输入、截图、定位）
  - 不负责：消息状态管理、轮询、去重
  
- **第2层：Message Channel（message_channel.py）**
  - 负责：消息事件流管理（轮询、去重、锚点、筛选）
  - 使用本模块的接口实现业务逻辑
  
- **第3层：AI Conversation Engine（未来）**
  - 负责：LLM对话、上下文管理、回复策略

依赖模块：
- flows: 业务流程编排（打开聊天、发送消息、读取消息）
- element_locator: 元素定位和新消息检测（视觉指纹）
- screen: 窗口和截图管理
- actions: 基础操作（点击、输入等）
- config: 配置管理
- models: 数据模型

使用示例：
```python
from wechat import WeChatController, WeChatMessageChannel

# 创建驱动层
controller = WeChatController()

# 直接使用驱动层（不推荐，需要自己管理状态）
controller.open_chat("联系人")
controller.send_text("联系人", "消息内容")
messages = controller.read_new_messages("联系人", anchor_hash="...")

# 推荐：使用消息通道层（自动管理状态）
channel = WeChatMessageChannel(controller)
events = channel.poll("联系人")  # 自动处理轮询、去重、锚点
```
"""

import logging
from enum import Enum
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path

# 支持相对导入（作为模块）和绝对导入（直接运行）
try:
    from .flows import send_text_to_contact, open_chat, send_message, read_new_messages, send_file_to_contact
    from .element_locator import has_new_message, save_chat_state, clear_chat_state, get_current_chat_hash
    from .screen import get_wechat_hwnd, get_dpi_scale, WindowNotFoundError, DPIError, ScreenshotError
    from .actions import ActionError
    from .locator import LocateError
    from .models import WeChatConfig, Message, FlowResult, TaskType
    from .config import WeChatAutomationConfig, ConfigValidationError
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from flows import send_text_to_contact, open_chat, send_message, read_new_messages, send_file_to_contact
    from element_locator import has_new_message, save_chat_state, clear_chat_state, get_current_chat_hash
    from screen import get_wechat_hwnd, get_dpi_scale, WindowNotFoundError, DPIError, ScreenshotError
    from actions import ActionError
    from locator import LocateError
    from models import WeChatConfig, Message, FlowResult, TaskType
    from config import WeChatAutomationConfig, ConfigValidationError

logger = logging.getLogger(__name__)


class ErrorCode(Enum):
    """错误码枚举"""
    SUCCESS = "SUCCESS"
    WINDOW_NOT_FOUND = "WINDOW_NOT_FOUND"
    DPI_ERROR = "DPI_ERROR"
    TEMPLATE_MISSING = "TEMPLATE_MISSING"
    TIMEOUT = "TIMEOUT"
    ACTION_FAILED = "ACTION_FAILED"
    LOCATE_FAILED = "LOCATE_FAILED"
    SCREENSHOT_FAILED = "SCREENSHOT_FAILED"
    CONFIG_INVALID = "CONFIG_INVALID"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"


class WeChatControllerError(Exception):
    """微信控制器基础异常"""
    def __init__(self, error_code: ErrorCode, message: str, debug_path: Optional[str] = None):
        self.error_code = error_code
        self.message = message
        self.debug_path = debug_path
        super().__init__(self.message)


class WeChatNotReadyError(WeChatControllerError):
    """微信未准备就绪异常"""
    pass


class ContactNotFoundError(WeChatControllerError):
    """联系人未找到异常"""
    pass


class SendMessageError(WeChatControllerError):
    """发送消息失败异常"""
    pass


class ReadMessageError(WeChatControllerError):
    """读取消息失败异常"""
    pass


@dataclass
class ControllerResult:
    """控制器操作结果
    
    属性：
        success: 是否成功
        error_code: 错误码（如果失败）
        error_message: 错误信息（如果失败）
        debug_path: 调试截图路径（如果失败）
        data: 返回数据（消息列表、联系人信息等）
        execution_time: 执行时间（秒）
    """
    success: bool
    error_code: Optional[ErrorCode] = None
    error_message: Optional[str] = None
    debug_path: Optional[str] = None
    data: Optional[Any] = None
    execution_time: float = 0.0


class WeChatController:
    """微信自动化控制器（驱动层）
    
    职责：
    - 像人一样操作微信，但不理解"聊天"含义
    - 只负责UI操作：打开聊天、发送消息、读取消息
    - 不负责消息状态管理、轮询、去重等逻辑
    
    这些逻辑应该由 MessageChannel 层处理。
    """
    
    def __init__(self, config: Optional[WeChatConfig] = None):
        """
        初始化控制器
        
        Args:
            config: 配置对象，None则使用默认配置
        """
        self.config = config or WeChatConfig()
        self._hwnd = None
        logger.info("WeChatController 初始化完成（驱动层）")
    
    def _map_error_to_code(self, error: Exception) -> tuple[ErrorCode, str]:
        """
        将底层异常映射为错误码和错误信息
        
        Args:
            error: 底层异常
        
        Returns:
            (错误码, 错误信息)
        """
        if isinstance(error, WindowNotFoundError):
            return (ErrorCode.WINDOW_NOT_FOUND, f"微信窗口未找到: {str(error)}")
        elif isinstance(error, DPIError):
            return (ErrorCode.DPI_ERROR, f"DPI设置错误: {str(error)}")
        elif isinstance(error, ScreenshotError):
            return (ErrorCode.SCREENSHOT_FAILED, f"截图失败: {str(error)}")
        elif isinstance(error, ActionError):
            return (ErrorCode.ACTION_FAILED, f"操作失败: {str(error)}")
        elif isinstance(error, LocateError):
            return (ErrorCode.LOCATE_FAILED, f"定位失败: {str(error)}")
        elif "timeout" in str(error).lower() or "超时" in str(error):
            return (ErrorCode.TIMEOUT, f"操作超时: {str(error)}")
        elif "模板" in str(error) or "template" in str(error).lower():
            return (ErrorCode.TEMPLATE_MISSING, f"模板缺失: {str(error)}")
        else:
            return (ErrorCode.UNKNOWN_ERROR, f"未知错误: {str(error)}")
    
    def _ensure_ready(self) -> None:
        """
        确保微信准备就绪
        
        Raises:
            WeChatNotReadyError: 微信未准备就绪
        """
        try:
            # 检查窗口是否存在
            self._hwnd = get_wechat_hwnd()
            
            # 获取 DPI 缩放（仅记录，不强制 100%；截图与坐标已按物理像素自适应）
            dpi_scale = get_dpi_scale()
            if abs(dpi_scale - 100.0) > 0.1:
                logger.debug(f"DPI 缩放 {dpi_scale}%，使用自适应模式")
            
            # 配置自检：硬失败（FAIL FAST），未通过则抛 ConfigValidationError
            WeChatAutomationConfig.validate_config(strict=False)
        
        except ConfigValidationError as e:
            raise WeChatNotReadyError(ErrorCode.CONFIG_INVALID, f"配置验证失败: {e}")
        except WindowNotFoundError as e:
            raise WeChatNotReadyError(ErrorCode.WINDOW_NOT_FOUND, f"微信窗口未找到: {str(e)}")
        except DPIError as e:
            raise WeChatNotReadyError(ErrorCode.DPI_ERROR, f"DPI设置错误: {str(e)}")
        except Exception as e:
            error_code, error_msg = self._map_error_to_code(e)
            raise WeChatNotReadyError(error_code, error_msg)
    
    def send_text(self, contact: str, text: str) -> ControllerResult:
        """
        发送文本消息（驱动层方法）
        
        直接执行发送操作，不关心消息状态、上下文等业务逻辑。
        如果需要消息状态管理，请使用 MessageChannel 层。
        
        Args:
            contact: 联系人名称
            text: 消息内容
        
        Returns:
            控制器操作结果
        
        Raises:
            WeChatNotReadyError: 微信未准备就绪
            SendMessageError: 发送失败
        """
        try:
            # 确保微信准备就绪
            self._ensure_ready()
            
            logger.info(f"发送消息: {contact} -> {text[:20]}...")
            
            # 调用流程
            flow_result = send_text_to_contact(contact, text, self.config)
            
            if flow_result.success:
                return ControllerResult(
                    success=True,
                    error_code=ErrorCode.SUCCESS,
                    data={"contact": contact, "message": text},
                    execution_time=flow_result.execution_time
                )
            else:
                # 从流程结果中提取错误信息
                error_code, error_msg = self._map_error_to_code(
                    Exception(flow_result.error_message or "发送消息失败")
                )
                
                return ControllerResult(
                    success=False,
                    error_code=error_code,
                    error_message=error_msg,
                    debug_path=flow_result.screenshot_path,
                    execution_time=flow_result.execution_time
                )
        
        except WeChatNotReadyError:
            raise
        except Exception as e:
            error_code, error_msg = self._map_error_to_code(e)
            logger.error(f"发送消息失败: {error_msg}")
            raise SendMessageError(error_code, error_msg)
    
    def open_chat(self, contact: str) -> ControllerResult:
        """
        打开聊天窗口（驱动层方法）
        
        直接执行打开操作，不关心当前状态、是否需要打开等业务判断。
        
        Args:
            contact: 联系人名称
        
        Returns:
            控制器操作结果
        
        Raises:
            WeChatNotReadyError: 微信未准备就绪
            ContactNotFoundError: 联系人未找到
        """
        try:
            # 确保微信准备就绪
            self._ensure_ready()
            
            logger.info(f"打开聊天窗口: {contact}")
            
            # 调用流程
            flow_result = open_chat(contact, self.config)
            
            if flow_result.success:
                return ControllerResult(
                    success=True,
                    error_code=ErrorCode.SUCCESS,
                    data={"contact": contact},
                    execution_time=flow_result.execution_time
                )
            else:
                # 从流程结果中提取错误信息
                error_code, error_msg = self._map_error_to_code(
                    Exception(flow_result.error_message or "打开聊天窗口失败")
                )
                
                return ControllerResult(
                    success=False,
                    error_code=error_code,
                    error_message=error_msg,
                    debug_path=flow_result.screenshot_path,
                    execution_time=flow_result.execution_time
                )
        
        except WeChatNotReadyError:
            raise
        except Exception as e:
            error_code, error_msg = self._map_error_to_code(e)
            logger.error(f"打开聊天窗口失败: {error_msg}")
            raise ContactNotFoundError(error_code, error_msg)
    
    def read_new_messages(
        self,
        contact: Optional[str] = None,
        anchor_hash: Optional[str] = None
    ) -> List[Message]:
        """
        读取新消息（纯驱动层方法）
        
        直接读取当前聊天窗口的消息，不判断首次/非首次，不维护状态。
        状态管理（锚点、去重等）应该由 MessageChannel 层处理。
        
        Args:
            contact: 联系人名称，如果指定则先打开聊天窗口
            anchor_hash: 锚点hash（可选），用于停止读取（匹配到锚点停止）
        
        Returns:
            消息列表（Message对象），从下到上（新到旧）
        
        Raises:
            WeChatNotReadyError: 微信未准备就绪
            ReadMessageError: 读取失败
        """
        try:
            # 确保微信准备就绪
            self._ensure_ready()
            
            logger.info(f"读取消息: {contact or '当前窗口'}")
            
            # 如果指定了联系人，先打开聊天窗口
            if contact:
                logger.debug(f"打开聊天窗口: {contact}")
                open_result = open_chat(contact, self.config)
                if not open_result.success:
                    error_code, error_msg = self._map_error_to_code(
                        Exception(open_result.error_message or "打开聊天窗口失败")
                    )
                    raise ReadMessageError(error_code, error_msg)
            
            # 读取消息（使用锚点停止条件）
            logger.debug(f"读取消息，锚点: {anchor_hash[:16] if anchor_hash else 'None'}...")
            flow_result = read_new_messages(
                contact,
                self.config,
                anchor_hash=anchor_hash
            )
            
            if flow_result.success:
                messages = flow_result.data.get("messages", []) if flow_result.data else []
                logger.info(f"成功读取 {len(messages)} 条消息")
                return messages
            else:
                error_code, error_msg = self._map_error_to_code(
                    Exception(flow_result.error_message or "读取消息失败")
                )
                raise ReadMessageError(error_code, error_msg)
        
        except WeChatNotReadyError:
            raise
        except ReadMessageError:
            raise
        except Exception as e:
            error_code, error_msg = self._map_error_to_code(e)
            logger.error(f"读取消息失败: {error_msg}")
            raise ReadMessageError(error_code, error_msg)
    
    def has_new_message(self, contact: Optional[str] = None, hash_threshold: int = 8) -> bool:
        """
        检测是否有新消息（驱动层方法，使用视觉指纹）
        
        使用感知哈希（pHash）比较聊天区域的变化，判断是否有新消息。
        按 contact 单独维护状态，避免多联系人混用导致漏检/误检。
        
        Args:
            contact: 联系人名称，用于按联系人区分状态；不传则使用默认状态
            hash_threshold: 哈希差异阈值（pHash建议8-12，默认8）
        
        Returns:
            是否有新消息（True表示有新消息，False表示没有）
        
        Note:
            首次调用会保存初始状态并返回False，后续调用会比较变化。
        """
        try:
            self._ensure_ready()
            return has_new_message(contact_name=contact, hash_threshold=hash_threshold)
        except Exception as e:
            logger.error(f"检测新消息失败: {e}")
            return False
    
    def save_chat_state(self, contact: Optional[str] = None) -> bool:
        """
        保存当前聊天窗口的视觉基线（与信息锚点绑定：仅在锚点更新/初始化成功后由 message_channel 调用）。
        """
        try:
            self._ensure_ready()
            return save_chat_state(contact_name=contact)
        except Exception as e:
            logger.warning(f"保存聊天状态失败: {e}")
            return False
    
    def clear_chat_state(self, contact: Optional[str] = None) -> bool:
        """
        清除指定联系人的视觉基线（锚点重置或初始化失败时调用，避免视觉状态与锚点不一致）。
        """
        try:
            return clear_chat_state(contact_name=contact)
        except Exception as e:
            logger.warning(f"清除聊天状态失败: {e}")
            return False
    
    def get_current_chat_hash(self, contact: Optional[str] = None) -> Optional[str]:
        """
        获取当前聊天区域的感知哈希（不修改状态，用于轮询前与已保存的 UI hash 比较）。
        """
        try:
            self._ensure_ready()
            return get_current_chat_hash(contact_name=contact)
        except Exception as e:
            logger.debug(f"获取当前聊天区 hash 失败: {e}")
            return None
    
    def is_wechat_running(self) -> bool:
        """
        检查微信是否运行
        
        Returns:
            是否运行
        """
        try:
            get_wechat_hwnd()
            return True
        except WindowNotFoundError:
            return False
        except Exception:
            return False
    
    def ensure_wechat_ready(self) -> bool:
        """
        确保微信准备就绪
        
        Returns:
            是否准备就绪
        
        Raises:
            WeChatNotReadyError: 微信未准备就绪
        """
        try:
            self._ensure_ready()
            return True
        except WeChatNotReadyError as e:
            logger.error(f"微信未准备就绪: {e.message}")
            raise
    
    def send_file(self, contact: str, file_path: str) -> ControllerResult:
        """
        发送文件/图片消息（驱动层方法）
        
        统一支持图片和普通文件，通过剪贴板复制粘贴发送。
        如果需要消息状态管理，请使用 MessageChannel 层。
        
        Args:
            contact: 联系人名称
            file_path: 文件路径
        
        Returns:
            控制器操作结果
        
        Raises:
            WeChatNotReadyError: 微信未准备就绪
            SendMessageError: 发送失败
        """
        try:
            # 确保微信准备就绪
            self._ensure_ready()
            
            logger.info(f"发送文件: {contact} -> {file_path}")
            
            # 调用流程
            flow_result = send_file_to_contact(contact, file_path, self.config)
            
            if flow_result.success:
                return ControllerResult(
                    success=True,
                    error_code=ErrorCode.SUCCESS,
                    data={"contact": contact, "file_path": file_path},
                    execution_time=flow_result.execution_time
                )
            else:
                # 从流程结果中提取错误信息
                error_code, error_msg = self._map_error_to_code(
                    Exception(flow_result.error_message or "发送文件失败")
                )
                
                return ControllerResult(
                    success=False,
                    error_code=error_code,
                    error_message=error_msg,
                    debug_path=flow_result.screenshot_path,
                    execution_time=flow_result.execution_time
                )
        
        except WeChatNotReadyError:
            raise
        except Exception as e:
            error_code, error_msg = self._map_error_to_code(e)
            logger.error(f"发送文件失败: {error_msg}")
            raise SendMessageError(error_code, error_msg)
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取控制器状态
        
        Returns:
            状态信息字典
        """
        status = {
            "wechat_running": self.is_wechat_running(),
            "hwnd": self._hwnd,
            "dpi_scale": None,
            "config_valid": False,
        }
        
        try:
            if self.is_wechat_running():
                status["dpi_scale"] = get_dpi_scale()
                is_valid, error = WeChatAutomationConfig.validate()
                status["config_valid"] = is_valid
                if not is_valid:
                    status["config_error"] = error
        except Exception as e:
            status["error"] = str(e)
        
        return status
