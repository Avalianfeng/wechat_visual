"""消息读取器

实现"每次只复制一个"的消息读取机制。

设计：
- 维护当前读取状态（头像列表、当前索引）
- 每次 read_next() 只复制一条消息
- 支持 read_until() 读取直到遇到锚点

重要假设（系统级前提，非 reader 内部逻辑）：
- reset() 调用前，调用方已确保 UI 位于目标联系人聊天窗口。
- reader 不负责验证「当前窗口联系人」与预期是否一致；若不一致，读取结果可能错位。
"""

import logging
import hashlib
from typing import Optional, List
from dataclasses import dataclass
from datetime import datetime

# 支持相对导入（作为模块）和绝对导入（独立目录运行）
try:
    from .models import Message
    from .screen import get_wechat_hwnd, capture_window
    from .actions import copy_text_at, human_delay, activate_window
    from .element_locator import locate_all_elements, locate_all_contact_avatars_in_chat, get_contact_name
except ImportError:
    from models import Message
    from screen import get_wechat_hwnd, capture_window
    from actions import copy_text_at, human_delay, activate_window
    from element_locator import locate_all_elements, locate_all_contact_avatars_in_chat, get_contact_name

logger = logging.getLogger(__name__)


@dataclass
class RawMessage:
    """原始消息（读取器返回的格式）
    
    属性：
        content: 消息内容
        hash: 消息hash
        position: 气泡位置 (x, y)
        avatar_index: 头像索引（从下到上，0是最下面的）
    """
    content: str
    hash: str
    position: tuple[int, int]
    avatar_index: int


class MessageReader:
    """消息读取器
    
    实现"每次只复制一个"的读取机制。
    维护读取状态，支持增量读取。
    """
    
    def __init__(self, contact_name: Optional[str] = None):
        """
        初始化消息读取器
        
        Args:
            contact_name: 联系人名称（用于日志）
        """
        self.contact_name = contact_name
        self._hwnd = None
        self._avatars: List = []  # 头像列表（LocateResult对象），从下到上排序
        self._current_index: int = 0  # 当前读取索引（从0开始，0是最下面的）
        self._initialized: bool = False
    
    def reset(self):
        """
        开始一次新的读取会话
        
        先获取当前窗口联系人名，再只定位该联系人在聊天区域的头像（不全局匹配所有模板），
        重置索引，准备从底部开始读取。
        """
        logger.info(f"重置消息读取器: {self.contact_name or '当前窗口'}")
        
        try:
            # 获取窗口句柄
            self._hwnd = get_wechat_hwnd()
            
            # 激活窗口
            if not activate_window(self._hwnd):
                raise Exception("激活窗口失败")
            human_delay(0.2, 0.3)
            
            # 先获取当前聊天窗口的联系人名字，再只选择该联系人的头像进行定位（不全局匹配所有联系人模板）
            current_contact = get_contact_name()
            if current_contact:
                current_contact = current_contact.strip()
                logger.info(f"当前聊天窗口联系人: {current_contact}")
            
            screenshot = capture_window(self._hwnd)
            
            # 优先：用「当前联系人」在聊天区域的头像（先取联系人名，再只匹配该联系人头像）
            if current_contact:
                all_in_chat = locate_all_contact_avatars_in_chat(screenshot=screenshot, enabled_contacts_only=False)
                current_avatars = [c.locate_result for c in all_in_chat if c.contact_name == current_contact and getattr(c.locate_result, "success", False)]
                if current_avatars:
                    self._avatars = sorted(current_avatars, key=lambda r: r.y if r.y is not None else 0, reverse=True)
                    self.contact_name = current_contact  # 与当前窗口一致
                    logger.info(f"使用当前联系人头像定位: {current_contact}，找到 {len(self._avatars)} 个聊天头像")
                else:
                    current_contact = None  # 未找到则回退
            else:
                current_contact = None
            
            # 回退：无当前联系人名或未匹配到该联系人头像时，用 locate_all_elements（单模板 + 分布判断）
            if not current_contact or not getattr(self, "_avatars", None) or len(self._avatars) == 0:
                contact_name_for_fallback = current_contact or self.contact_name
                contact_id = None
                if contact_name_for_fallback:
                    try:
                        try:
                            from .contact_mapper import ContactUserMapper
                        except ImportError:
                            from contact_mapper import ContactUserMapper
                        contact_mapper = ContactUserMapper()
                        contact_id = contact_mapper.get_contact_id(contact_name_for_fallback)
                    except Exception as e:
                        logger.debug(f"获取contact_id失败: {e}，将使用contact_name定位头像")
                logger.info(f"定位聊天区域中的头像（回退）: {contact_name_for_fallback or '当前窗口'}")
                positions = locate_all_elements(screenshot, contact_name=contact_name_for_fallback, contact_id=contact_id)
                profile_photo_in_chat = positions.get("profile_photo_in_chat")
                if not profile_photo_in_chat or not isinstance(profile_photo_in_chat, list) or len(profile_photo_in_chat) == 0:
                    logger.error(f"未找到聊天区域中的头像，可能不在聊天界面或没有消息 (联系人: {contact_name_for_fallback or '未知'})")
                    raise Exception("未找到聊天区域中的头像，可能不在聊天界面或没有消息")
                self._avatars = [r for r in profile_photo_in_chat if r.success]
                self._avatars.sort(key=lambda r: r.y if r.y is not None else 0, reverse=True)
            
            # 重置索引
            self._current_index = 0
            self._initialized = True
            
            logger.info(f"重置完成: 找到 {len(self._avatars)} 个聊天头像，准备从底部开始读取")
            if len(self._avatars) > 0:
                logger.debug(f"头像y坐标列表（从下到上，新到旧）: {[r.y for r in self._avatars[:5]]}...")
        
        except Exception as e:
            logger.error(f"重置消息读取器失败: {e}")
            self._initialized = False
            raise
    
    def read_next(self) -> Optional[RawMessage]:
        """
        从当前画面中，按顺序读下一条（从底部开始）
        
        每次只复制一条消息，更新索引。
        
        Returns:
            RawMessage对象，如果读完当前页返回None
        """
        if not self._initialized:
            raise Exception("读取器未初始化，请先调用 reset()")
        
        # 检查是否还有消息可读
        if self._current_index >= len(self._avatars):
            logger.debug("已读完当前页所有消息")
            return None
        
        # 获取当前头像
        avatar_result = self._avatars[self._current_index]
        
        # 计算气泡位置（头像中心向右移动65px）
        bubble_x = avatar_result.x + 65
        bubble_y = avatar_result.y
        
        logger.debug(f"读取消息 {self._current_index + 1}/{len(self._avatars)}: 头像位置=({avatar_result.x}, {avatar_result.y}), 气泡位置=({bubble_x}, {bubble_y})")
        
        # 双击气泡复制文本
        try:
            text = copy_text_at(bubble_x, bubble_y, self._hwnd, double_click=True)
            
            if not text or not text.strip():
                logger.warning(f"消息 {self._current_index + 1} 复制失败或为空，跳过")
                # 跳过这条消息，继续下一条
                self._current_index += 1
                return self.read_next()  # 递归读取下一条
            
            # 计算消息hash
            message_hash = hashlib.md5(text.strip().encode('utf-8')).hexdigest()
            
            # 创建RawMessage对象
            raw_message = RawMessage(
                content=text.strip(),
                hash=message_hash,
                position=(bubble_x, bubble_y),
                avatar_index=self._current_index
            )
            
            logger.debug(f"成功读取消息 {self._current_index + 1}/{len(self._avatars)}: {text[:30]}... (hash: {message_hash[:16]}...)")
            
            # 更新索引
            self._current_index += 1
            
            # 每条消息之间稍作延迟
            human_delay(0.1, 0.15)
            
            return raw_message
        
        except Exception as e:
            logger.error(f"读取消息失败: {e}")
            # 跳过这条消息，继续下一条
            self._current_index += 1
            return self.read_next()  # 递归读取下一条
    
    def read_until(self, anchor_hash: Optional[str]) -> List[RawMessage]:
        """
        一直读，直到遇到 anchor
        
        从当前位置开始读取，直到：
        1. 匹配到锚点hash（停止）
        2. 读完当前页（停止）
        
        Args:
            anchor_hash: 锚点hash（可选），匹配到则停止
        
        Returns:
            读取到的消息列表（RawMessage对象），从下到上（新到旧）
        """
        if not self._initialized:
            raise Exception("读取器未初始化，请先调用 reset()")
        
        messages = []
        
        # 预处理锚点：如果输入的是文本，先计算hash
        anchor_hash_to_compare = None
        if anchor_hash:
            # 检查是否是hash格式（32位hex字符串）
            is_hash_format = len(anchor_hash) == 32 and all(
                c in '0123456789abcdef' for c in anchor_hash.lower()
            )
            if is_hash_format:
                anchor_hash_to_compare = anchor_hash
                logger.debug(f"锚点hash: {anchor_hash[:16]}...")
            else:
                # 不是hash格式，当作文本处理，计算hash
                anchor_hash_to_compare = hashlib.md5(
                    anchor_hash.strip().encode('utf-8')
                ).hexdigest()
                logger.debug(f"锚点文本: {anchor_hash[:30]}... -> hash: {anchor_hash_to_compare[:16]}...")
        
        # 从当前位置开始读取
        while True:
            raw_message = self.read_next()
            
            if raw_message is None:
                # 读完当前页
                logger.debug("已读完当前页，停止读取")
                break
            
            # 检查是否匹配锚点
            if anchor_hash_to_compare and raw_message.hash == anchor_hash_to_compare:
                logger.info(f"匹配到锚点，停止读取（消息: {raw_message.content[:30]}...）")
                break
            
            # 添加到消息列表
            messages.append(raw_message)
        
        logger.info(f"读取完成: 共 {len(messages)} 条消息")
        return messages
    
    def get_current_index(self) -> int:
        """
        获取当前读取索引
        
        Returns:
            当前索引（0是最下面的）
        """
        return self._current_index
    
    def get_total_count(self) -> int:
        """
        获取当前页总消息数
        
        Returns:
            总消息数
        """
        return len(self._avatars) if self._initialized else 0
    
    def is_finished(self) -> bool:
        """
        检查是否已读完当前页
        
        Returns:
            是否已读完
        """
        if not self._initialized:
            return True
        return self._current_index >= len(self._avatars)
