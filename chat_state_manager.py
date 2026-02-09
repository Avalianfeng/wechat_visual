"""聊天状态管理模块

用于管理每个联系人的聊天状态（hash和头像y位置），支持多联系人并发管理。

核心功能：
- 为每个联系人单独维护聊天区域的hash和头像y位置
- 支持保存和获取特定联系人的状态
- 支持清除特定联系人或所有联系人的状态

使用方式：
```python
from wechat.chat_state_manager import ChatStateManager

manager = ChatStateManager()

# 保存联系人状态
manager.save_state("联系人名称", chat_hash="abc123", avatar_y_positions=[100, 200, 300])

# 获取联系人状态
state = manager.get_state("联系人名称")

# 检查是否有新消息
has_new = manager.has_new_message("联系人名称", current_hash="abc456", current_avatar_y_positions=[100, 200, 350])
```
"""

import logging
from typing import Optional, List, Dict
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class ChatState:
    """单个联系人的聊天状态"""
    chat_hash: Optional[str] = None
    avatar_y_positions: List[int] = field(default_factory=list)


class ChatStateManager:
    """聊天状态管理器
    
    为每个联系人单独维护聊天状态，包括：
    - chat_hash: 聊天区域的感知哈希
    - avatar_y_positions: 头像y位置列表
    """
    
    def __init__(self):
        """初始化状态管理器"""
        # 存储每个联系人的状态：{contact_name: ChatState}
        self._states: Dict[str, ChatState] = {}
        logger.debug("[ChatStateManager] 初始化聊天状态管理器")
    
    def _get_contact_key(self, contact_name: Optional[str] = None) -> str:
        """
        获取联系人键名
        
        Args:
            contact_name: 联系人名称，如果为None则使用默认键
        
        Returns:
            联系人键名
        """
        if contact_name is None:
            return "__default__"
        return str(contact_name)
    
    def save_state(
        self,
        contact_name: Optional[str] = None,
        chat_hash: Optional[str] = None,
        avatar_y_positions: Optional[List[int]] = None
    ) -> bool:
        """
        保存联系人的聊天状态
        
        Args:
            contact_name: 联系人名称，如果为None则保存为默认状态
            chat_hash: 聊天区域的感知哈希
            avatar_y_positions: 头像y位置列表
        
        Returns:
            是否成功保存
        """
        key = self._get_contact_key(contact_name)
        
        # 获取或创建状态对象
        if key not in self._states:
            self._states[key] = ChatState()
        
        state = self._states[key]
        
        # 更新状态
        if chat_hash is not None:
            state.chat_hash = chat_hash
            logger.debug(f"[ChatStateManager] 保存联系人 '{contact_name or '默认'}' 的hash: {chat_hash[:16]}...")
        
        if avatar_y_positions is not None:
            state.avatar_y_positions = list(avatar_y_positions)  # 创建副本
            logger.debug(f"[ChatStateManager] 保存联系人 '{contact_name or '默认'}' 的头像y位置: {avatar_y_positions}")
        
        return True
    
    def get_state(self, contact_name: Optional[str] = None) -> Optional[ChatState]:
        """
        获取联系人的聊天状态
        
        Args:
            contact_name: 联系人名称，如果为None则获取默认状态
        
        Returns:
            聊天状态对象，如果不存在则返回None
        """
        key = self._get_contact_key(contact_name)
        return self._states.get(key)
    
    def get_chat_hash(self, contact_name: Optional[str] = None) -> Optional[str]:
        """
        获取联系人的聊天区域hash
        
        Args:
            contact_name: 联系人名称，如果为None则获取默认状态
        
        Returns:
            聊天区域hash，如果不存在则返回None
        """
        state = self.get_state(contact_name)
        return state.chat_hash if state else None
    
    def get_avatar_y_positions(self, contact_name: Optional[str] = None) -> List[int]:
        """
        获取联系人的头像y位置列表
        
        Args:
            contact_name: 联系人名称，如果为None则获取默认状态
        
        Returns:
            头像y位置列表，如果不存在则返回空列表
        """
        state = self.get_state(contact_name)
        return list(state.avatar_y_positions) if state and state.avatar_y_positions else []
    
    def has_new_message(
        self,
        contact_name: Optional[str] = None,
        current_hash: Optional[str] = None,
        current_avatar_y_positions: Optional[List[int]] = None,
        hash_threshold: int = 8
    ) -> bool:
        """
        判断联系人是否有新消息
        
        方案：
        1. 使用感知哈希（pHash）比较聊天区域的变化
        2. 如果hash变化超过阈值，再检查头像y位置是否变化
        
        Args:
            contact_name: 联系人名称，如果为None则使用默认状态
            current_hash: 当前聊天区域的感知哈希
            current_avatar_y_positions: 当前头像y位置列表
            hash_threshold: 哈希差异阈值（pHash建议8-12）
        
        Returns:
            是否有新消息
        """
        if current_hash is None:
            logger.warning(f"[ChatStateManager] 未提供current_hash，无法判断新消息")
            return False
        
        state = self.get_state(contact_name)
        
        # 无视觉基线（仅随信息锚点更新/清除）：跳过视觉判断，直接尝试读取（以信息锚点为准）
        if state is None or state.chat_hash is None:
            logger.info(
                f"[ChatStateManager] 联系人 '{contact_name or '默认'}' 无视觉基线，跳过视觉判断，直接尝试读取（以信息锚点为准）"
            )
            return True
        
        # 计算哈希差异（汉明距离）
        try:
            import imagehash
            last_hash = imagehash.hex_to_hash(state.chat_hash)
            current_hash_obj = imagehash.hex_to_hash(current_hash)
            hash_diff = current_hash_obj - last_hash
            
            # 如果hash差异超过阈值，视为聊天区域有变化 => 有新消息（避免同一人连续发多条时头像不变导致漏检）
            if hash_diff >= hash_threshold:
                logger.info(
                    f"[ChatStateManager] 联系人 '{contact_name or '默认'}' 视觉变化: hash差异={hash_diff} >= 阈值{hash_threshold}，判定为新消息"
                )
                self.save_state(
                    contact_name=contact_name,
                    chat_hash=current_hash,
                    avatar_y_positions=current_avatar_y_positions or []
                )
                return True
            else:
                logger.info(
                    f"[ChatStateManager] 联系人 '{contact_name or '默认'}' 视觉未变化: hash差异={hash_diff} < 阈值{hash_threshold}，跳过读取"
                )
                return False
        except ImportError:
            logger.warning("[ChatStateManager] imagehash未安装，无法使用视觉指纹检测新消息")
            return False
        except Exception as e:
            logger.error(f"[ChatStateManager] 判断新消息失败: {e}")
            return False
    
    def clear_state(self, contact_name: Optional[str] = None) -> bool:
        """
        清除联系人的聊天状态
        
        Args:
            contact_name: 联系人名称，如果为None则清除默认状态
        
        Returns:
            是否成功清除
        """
        key = self._get_contact_key(contact_name)
        if key in self._states:
            del self._states[key]
            logger.debug(f"[ChatStateManager] 清除联系人 '{contact_name or '默认'}' 的状态")
            return True
        return False
    
    def clear_all_states(self) -> int:
        """
        清除所有联系人的聊天状态
        
        Returns:
            清除的联系人数量
        """
        count = len(self._states)
        self._states.clear()
        logger.info(f"[ChatStateManager] 清除所有联系人状态，共 {count} 个")
        return count
    
    def get_all_contacts(self) -> List[str]:
        """
        获取所有已保存状态的联系人列表
        
        Returns:
            联系人名称列表（不包括默认键）
        """
        contacts = [name for name in self._states.keys() if name != "__default__"]
        logger.debug(f"[ChatStateManager] 获取所有联系人: {len(contacts)} 个")
        return contacts
    
    def has_state(self, contact_name: Optional[str] = None) -> bool:
        """
        检查联系人是否有保存的状态
        
        Args:
            contact_name: 联系人名称，如果为None则检查默认状态
        
        Returns:
            是否有保存的状态
        """
        key = self._get_contact_key(contact_name)
        return key in self._states


# 全局单例实例（向后兼容）
_global_manager: Optional[ChatStateManager] = None


def get_global_manager() -> ChatStateManager:
    """
    获取全局状态管理器实例（单例模式）
    
    Returns:
        全局ChatStateManager实例
    """
    global _global_manager
    if _global_manager is None:
        _global_manager = ChatStateManager()
    return _global_manager
