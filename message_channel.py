"""消息通道层

将"微信 UI 行为"抽象成"消息事件流"。

职责：
- 消息顺序保证
- 消息去重
- 上下文窗口管理
- 锚点管理（判断"这条消息是不是已经处理过"）
- 轮询机制

设计原则：
- 不关心微信UI细节（由Controller处理）
- 不关心AI对话逻辑（由Conversation Engine处理）
- 只关心消息事件流的抽象和管理
"""

import json
import logging
import hashlib
from pathlib import Path
from typing import Optional, List, Dict, Set
from dataclasses import dataclass
from datetime import datetime, timezone

# 支持相对导入（作为模块）和绝对导入（独立目录运行）
try:
    from .models import Message
    from .message_reader import MessageReader, RawMessage
except ImportError:
    from models import Message
    from message_reader import MessageReader, RawMessage

try:
    from .config import WeChatAutomationConfig
except ImportError:
    from config import WeChatAutomationConfig

logger = logging.getLogger(__name__)


@dataclass
class MessageEvent:
    """消息事件
    
    属性：
        contact: 联系人名称
        role: 角色（"user"表示对方发送的消息，"assistant"表示我们发送的消息）
        content: 消息内容
        timestamp: 时间戳
        hash: 消息hash（用于去重和锚点匹配）
    """
    contact: str
    role: str  # "user" or "assistant"
    content: str
    timestamp: datetime
    hash: str


class WeChatMessageChannel:
    """微信消息通道
    
    负责：
    - 轮询新消息
    - 消息去重
    - 锚点管理（判断是否已读）
    - 消息筛选和排序
    """
    
    def __init__(self, wechat_controller):
        """
        初始化消息通道
        
        Args:
            wechat_controller: WeChatController实例（驱动层）
        """
        self.wechat = wechat_controller
        # 锚点与去重均按联系人区分，互不污染
        # 为每个联系人维护锚点hash（最后一条已读消息的hash）；按次调用时从文件加载
        self._anchor_hashes: Dict[str, Optional[str]] = self._load_anchor_state()
        # 已处理的消息hash集合（仅当次进程内轮询去重用，不持久化；跨进程去重依赖锚点与 _filter）。
        # 禁止单独依赖 _seen_hashes 做跨进程/跨次调用去重；连续 CLI 行为由锚点文件与 test_message_channel_robustness 覆盖。
        self._seen_hashes: Dict[str, Set[str]] = {}
        # 为每个联系人维护独立的消息读取器实例
        self._readers: Dict[str, MessageReader] = {}
        # 首次锚点生成失败的联系人：不再自动重试，避免错位；需显式 reset_anchor(contact) 后再读
        self._anchor_init_failed: Set[str] = set()
        logger.info("WeChatMessageChannel 初始化完成")

    def _anchor_state_path(self) -> Path:
        """锚点状态文件路径"""
        WeChatAutomationConfig.ensure_directories()
        return WeChatAutomationConfig.ANCHOR_STATE_FILE

    def _load_anchor_state(self) -> Dict[str, Optional[str]]:
        """从文件加载各联系人的锚点 hash（按次调用读取时用）。文件为 JSON 对象，键为联系人名，值为锚点 hash；不同联系人状态互不污染。"""
        path = self._anchor_state_path()
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return {k: (v if v else None) for k, v in data.items()}
        except Exception as e:
            logger.warning(f"加载锚点状态失败: {e}，将使用空锚点")
            return {}

    def _save_anchor_state(self) -> None:
        """将当前锚点状态写入文件（只保存非 None 的锚点）"""
        path = self._anchor_state_path()
        try:
            data = {k: v for k, v in self._anchor_hashes.items() if v is not None}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存锚点状态失败: {e}")

    def _visual_state_path(self) -> Path:
        """视觉状态文件路径（按联系人保存 UI hash，用于轮询时先比较再 OCR）"""
        WeChatAutomationConfig.ensure_directories()
        return WeChatAutomationConfig.VISUAL_STATE_FILE

    def _load_visual_state(self) -> Dict[str, str]:
        """从文件加载各联系人的 UI hash；键为联系人名，值为 hash 字符串。"""
        path = self._visual_state_path()
        if not path.exists():
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            return {k: str(v) for k, v in data.items() if v}
        except Exception as e:
            logger.warning(f"加载视觉状态失败: {e}，将使用空状态")
            return {}

    def _save_visual_state(self, contact: str, ui_hash: str) -> None:
        """将指定联系人的 UI hash 写入文件（合并到现有状态）。"""
        path = self._visual_state_path()
        try:
            data = self._load_visual_state()
            data[contact] = ui_hash
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"保存视觉状态失败: {e}")

    def _clear_visual_state(self, contact: str) -> None:
        """清除指定联系人的视觉状态（与 reset_anchor 同步，避免使用过期基线）。"""
        path = self._visual_state_path()
        try:
            data = self._load_visual_state()
            data.pop(contact, None)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"清除视觉状态失败: {e}")
    
    def poll(self, contact: str, update_anchor: bool = True) -> List[MessageEvent]:
        """
        轮询新消息
        
        核心逻辑：
        0. 根据联系人加载已保存的 UI hash，与当前聊天区 hash 比较；未变化则直接返回无信息。
        1. 若发生变化，调用阿里云 OCR 判断当前联系人是否为目标；若是则跳过 open_chat，否则先 open_chat(contact) 再继续。
        2. 无锚点时初始化锚点，保存视觉状态，返回空。
        3. 读取快照（MessageReader），读取后再次校验联系人，筛选新消息；若 update_anchor 则更新锚点并保存视觉状态。
        
        Args:
            contact: 联系人名称
            update_anchor: 是否将本轮读取结果写回锚点文件；False 表示仅读取、不更新锚点（如 CLI 隐式 contact 时）
        
        Returns:
            新消息事件列表（MessageEvent对象）
        """
        logger.info(f"轮询新消息: {contact} (update_anchor={update_anchor})")
        contact_stripped = contact.strip()

        # 步骤0: 已保存的 UI hash 与当前 hash 比较，未变化则直接返回无信息
        visual_state = self._load_visual_state()
        saved_hash = visual_state.get(contact)
        current_hash = self.wechat.get_current_chat_hash(contact)
        if saved_hash is not None and current_hash is not None and saved_hash == current_hash:
            logger.info(f"[MessageChannel] UI hash 未变化，直接返回无信息")
            return []
        logger.info(f"[MessageChannel] UI 有变化或尚无基线，继续流程")

        # 步骤1: 用阿里云 OCR 判断当前联系人；若已是目标则跳过 open_chat，否则先打开对应聊天
        try:
            try:
                from .element_locator import get_contact_name
            except ImportError:
                from element_locator import get_contact_name
            current_contact = get_contact_name(prefer_aliyun=True)
            if current_contact:
                current_contact = current_contact.strip()
                if current_contact == contact_stripped:
                    logger.info(f"[MessageChannel] ✓ 当前已是目标联系人: {contact}，跳过 open_chat")
                else:
                    logger.info(f"[MessageChannel] ⚠ 当前联系人={current_contact}，目标={contact}，调用 open_chat({contact})")
                    open_result = self.wechat.open_chat(contact)
                    if not open_result.success:
                        logger.error(f"[MessageChannel] ✗ 打开聊天窗口失败: {open_result.error_message}")
                        return []
                    logger.info(f"[MessageChannel] ✓ 已切换到: {contact}")
            else:
                logger.info(f"[MessageChannel] ⚠ 无法识别当前联系人，尝试 open_chat({contact})")
                open_result = self.wechat.open_chat(contact)
                if not open_result.success:
                    logger.error(f"[MessageChannel] ✗ 打开聊天窗口失败: {open_result.error_message}")
                    return []
                logger.info(f"[MessageChannel] ✓ 已打开聊天: {contact}")
        except Exception as e:
            logger.error(f"[MessageChannel] ✗ 检查/打开聊天窗口失败: {e}")
            try:
                open_result = self.wechat.open_chat(contact)
                if not open_result.success:
                    logger.error(f"[MessageChannel] ✗ 打开聊天窗口失败: {open_result.error_message}")
                    return []
            except Exception as e2:
                logger.error(f"[MessageChannel] ✗ 打开聊天窗口失败: {e2}")
                return []

        # 步骤1.5: 在确保当前窗口已切到目标联系人后，再次检测 UI hash 是否相对上次有变化
        # 场景：用户手动切走→UI变化→我们切回目标联系人，但聊天内容其实没变，此时不需要再读一次消息。
        current_hash_after = self.wechat.get_current_chat_hash(contact)
        if saved_hash is not None and current_hash_after is not None and saved_hash == current_hash_after:
            logger.info(
                "[MessageChannel] open_chat 校正后 UI hash 与已保存基线一致，"
                "本轮不再读取消息，直接返回无信息"
            )
            return []

        # 步骤2: 检查是否首次调用（没有锚点）
        anchor_val = self._anchor_hashes.get(contact)
        has_anchor = anchor_val is not None
        if has_anchor:
            logger.info(f"[MessageChannel] 步骤2: 已有锚点 (hash={anchor_val[:16]}...)")
        else:
            logger.info(f"[MessageChannel] 步骤2: 无锚点，需首次初始化")

        if not has_anchor:
            if contact in self._anchor_init_failed:
                logger.warning(f"[MessageChannel] 首次锚点已失败过，不再自动重试；请显式 reset_anchor({contact}) 后再读")
                return []
            logger.info(f"[MessageChannel] 首次调用，初始化锚点: {contact}")
            anchor_hash = self._init_anchor(contact)
            if anchor_hash:
                self._anchor_hashes[contact] = anchor_hash
                self._save_anchor_state()
                self.wechat.save_chat_state(contact)
                h = self.wechat.get_current_chat_hash(contact)
                if h:
                    self._save_visual_state(contact, h)
                logger.info(f"[MessageChannel] 已初始化锚点: {anchor_hash[:16]}...，本轮返回空（下次 poll 再比较新消息）")
            else:
                self._anchor_init_failed.add(contact)
                self.wechat.clear_chat_state(contact)
                logger.warning(f"[MessageChannel] 首次锚点生成失败，已记录；请确认 UI 稳定后 reset_anchor 再读")
            return []

        # 步骤3: 读取快照（UI 已变化，不再调用 has_new_message）
        logger.info(f"[MessageChannel] 步骤3: 读取快照（MessageReader.read_until）")
        anchor_hash = anchor_val
        raw_messages = self._read_snapshot(contact, anchor_hash)
        logger.info(f"[MessageChannel] 步骤3结果: 读取到 {len(raw_messages)} 条原始消息")
        if not raw_messages:
            logger.info(f"[MessageChannel] 读取到 0 条消息，返回空")
            return []

        # 步骤3.5: 读取后再次校验当前联系人；若已切换则丢弃本轮，不更新锚点
        try:
            try:
                from .element_locator import get_contact_name as _get_contact_name
            except ImportError:
                from element_locator import get_contact_name as _get_contact_name
            again = _get_contact_name()
            again = again.strip() if again else ""
            if again != contact_stripped:
                logger.warning(f"[MessageChannel] 读取后联系人已切换（预期={contact}, 当前={again}），丢弃本轮读取")
                return []
        except Exception as e:
            logger.warning(f"[MessageChannel] 读取后校验联系人失败: {e}，丢弃本轮读取")
            return []

        # 步骤4: 筛选新消息（与锚点比较，去重）
        logger.info(f"[MessageChannel] 步骤4: 筛选新消息（与锚点比较、去重）")
        new_events = self._filter_new_messages_from_raw(contact, raw_messages, anchor_hash)
        logger.info(f"[MessageChannel] 步骤4结果: 筛选后新消息数 = {len(new_events)}")

        # 步骤5: 若 update_anchor 则更新锚点、已处理 hash；完成流程后保存视觉状态（无论是否有新消息）
        if new_events and update_anchor:
            new_anchor_hash = new_events[0].hash
            self._anchor_hashes[contact] = new_anchor_hash
            self._save_anchor_state()
            self.wechat.save_chat_state(contact)
            logger.info(f"已更新锚点: {new_anchor_hash[:16]}...")
            if contact not in self._seen_hashes:
                self._seen_hashes[contact] = set()
            for event in new_events:
                self._seen_hashes[contact].add(event.hash)
        h = self.wechat.get_current_chat_hash(contact)
        if h:
            self._save_visual_state(contact, h)

        new_events = list(reversed(new_events))
        logger.info(f"[MessageChannel] poll 完成: 返回 {len(new_events)} 条新消息（已按先发→后发排序）")
        return new_events
    
    def _init_anchor(self, contact: str) -> Optional[str]:
        """
        初始化锚点（获取当前最下面的消息作为锚点）
        
        使用 MessageReader 读取当前最下面的一条消息作为锚点。
        
        Args:
            contact: 联系人名称
        
        Returns:
            锚点hash，如果失败返回None
        """
        try:
            # 使用 MessageReader 读取当前最下面的消息作为锚点（本工具只做传输，不做记忆管理）
            if contact not in self._readers:
                self._readers[contact] = MessageReader(contact_name=contact)
            
            reader = self._readers[contact]
            
            # 重置读取器（重新定位头像）
            reader.reset()
            
            # 只读取第一条消息（最下面的，最新的）
            raw_message = reader.read_next()
            
            if raw_message:
                anchor_hash = raw_message.hash
                logger.info(f"成功获取初始锚点（当前消息）: {anchor_hash[:16]}... (消息: {raw_message.content[:30]}...)")
                return anchor_hash
            else:
                logger.warning("未找到消息，无法设置锚点")
                return None
        
        except Exception as e:
            logger.error(f"初始化锚点失败: {e}")
            return None
    
    def _read_snapshot(
        self,
        contact: str,
        anchor_hash: Optional[str]
    ) -> List[RawMessage]:
        """
        读取快照（使用MessageReader）
        
        Args:
            contact: 联系人名称
            anchor_hash: 锚点hash（用于停止读取）
        
        Returns:
            原始消息列表（RawMessage对象）
        """
        # 获取或创建消息读取器
        if contact not in self._readers:
            self._readers[contact] = MessageReader(contact_name=contact)
        
        reader = self._readers[contact]
        
        try:
            # 重置读取器（重新定位头像）
            reader.reset()
            
            # 读取直到遇到锚点
            raw_messages = reader.read_until(anchor_hash)
            
            return raw_messages
        
        except Exception as e:
            logger.error(f"读取快照失败: {e}")
            return []
    
    def _filter_new_messages_from_raw(
        self,
        contact: str,
        raw_messages: List[RawMessage],
        anchor_hash: Optional[str]
    ) -> List[MessageEvent]:
        """
        筛选新消息（从RawMessage转换为MessageEvent，去重）
        
        Args:
            contact: 联系人名称
            raw_messages: 原始消息列表（RawMessage对象）
            anchor_hash: 锚点hash
        
        Returns:
            新消息事件列表（MessageEvent对象）
        """
        new_events = []
        
        # 初始化已处理hash集合
        if contact not in self._seen_hashes:
            self._seen_hashes[contact] = set()
        
        # 预处理锚点：如果输入的是文本，先计算hash
        anchor_hash_to_compare = None
        if anchor_hash:
            # 检查是否是hash格式（32位hex字符串）
            is_hash_format = len(anchor_hash) == 32 and all(
                c in '0123456789abcdef' for c in anchor_hash.lower()
            )
            if is_hash_format:
                anchor_hash_to_compare = anchor_hash
            else:
                # 不是hash格式，当作文本处理，计算hash
                anchor_hash_to_compare = hashlib.md5(
                    anchor_hash.strip().encode('utf-8')
                ).hexdigest()
        
        # 遍历消息（从下到上，新到旧）
        for raw_msg in raw_messages:
            # 检查是否匹配锚点（MessageReader已经处理了，这里主要是去重检查）
            if anchor_hash_to_compare and raw_msg.hash == anchor_hash_to_compare:
                logger.debug(f"消息匹配锚点，跳过: {raw_msg.hash[:16]}...")
                continue
            
            # 检查是否已处理过（去重）
            if raw_msg.hash in self._seen_hashes[contact]:
                logger.debug(f"消息已处理过，跳过: {raw_msg.hash[:16]}...")
                continue
            
            # 创建消息事件
            event = MessageEvent(
                contact=contact,
                role="user",  # 从对方接收的消息
                content=raw_msg.content,
                timestamp=datetime.now(timezone.utc),  # 无法获取真实时间戳，使用当前时间
                hash=raw_msg.hash
            )
            new_events.append(event)
            logger.debug(f"新消息事件: {event.content[:30]}... (hash: {event.hash[:16]}...)")
        
        logger.info(f"筛选完成: 共 {len(new_events)} 条新消息")
        return new_events

    def read_direct(self, contact: str) -> List[MessageEvent]:
        """
        直接读当前可见页的新消息（不做 UI hash 预检，但用信息锚点做停止条件）。

        - 读取时：从底部开始，用已有锚点（文本信息 hash）做停止条件，只读到锚点为止（新消息）。
        - 无锚点时：从底部读满当前页，相当于首次或全量。
        - 读完后：自动更新该联系人的画面区域 hash 与信息锚点，便于下次只读更新部分。

        调用方需保证已打开该联系人聊天窗口（如先 open_chat(contact)）。
        """
        contact_stripped = contact.strip()
        anchor_hash = self._anchor_hashes.get(contact_stripped)
        if anchor_hash:
            logger.info(f"[MessageChannel] read_direct 使用锚点停止: {contact}, anchor={anchor_hash[:16]}...")
        else:
            logger.info(f"[MessageChannel] read_direct 无锚点，读满当前页: {contact}")

        raw_messages = self._read_snapshot(contact_stripped, anchor_hash=anchor_hash)
        events = [
            MessageEvent(
                contact=contact_stripped,
                role="user",
                content=raw.content,
                timestamp=datetime.now(timezone.utc),
                hash=raw.hash,
            )
            for raw in raw_messages
        ]
        events = list(reversed(events))

        # 读完后更新信息锚点（最新一条的 hash）与画面 hash
        if raw_messages:
            new_anchor = raw_messages[0].hash
            self._anchor_hashes[contact_stripped] = new_anchor
            self._save_anchor_state()
            if contact_stripped not in self._seen_hashes:
                self._seen_hashes[contact_stripped] = set()
            for raw in raw_messages:
                self._seen_hashes[contact_stripped].add(raw.hash)
            logger.info(f"[MessageChannel] read_direct 已更新锚点: {new_anchor[:16]}...")
        try:
            self.wechat.save_chat_state(contact_stripped)
            h = self.wechat.get_current_chat_hash(contact_stripped)
            if h:
                self._save_visual_state(contact_stripped, h)
                logger.info(f"[MessageChannel] read_direct 已更新画面 hash: {contact}, {h[:16]}...")
        except Exception as e:
            logger.warning(f"[MessageChannel] read_direct 更新画面状态失败: {e}")

        logger.info(f"[MessageChannel] read_direct 完成: {contact}, 共 {len(events)} 条")
        return events
    
    
    def send_message(self, contact: str, text: str) -> bool:
        """
        发送消息（通过Controller）
        
        Args:
            contact: 联系人名称
            text: 消息内容
        
        Returns:
            是否发送成功
        """
        result = self.wechat.send_text(contact, text)
        if result.success:
            # 记录发送的消息hash（用于去重）
            message_hash = hashlib.md5(text.strip().encode('utf-8')).hexdigest()
            if contact not in self._seen_hashes:
                self._seen_hashes[contact] = set()
            self._seen_hashes[contact].add(message_hash)

            # 发送成功后，自动刷新该联系人的 UI hash（视觉基线），
            # 等价于对当前窗口做一次轻量级的 update-hash：
            try:
                h = self.wechat.get_current_chat_hash(contact)
                if h:
                    self._save_visual_state(contact, h)
                    logger.info(
                        f"[MessageChannel] 已在发送后更新 UI hash: contact={contact}, hash={h[:16]}..."
                    )
            except Exception as e:
                # 刷新视觉 hash 失败不影响发送结果，只做告警日志
                logger.warning(f"[MessageChannel] 发送后更新 UI hash 失败: {e}")

            logger.info(f"消息已发送: {contact} -> {text[:30]}...")
            return True
        else:
            logger.error(f"消息发送失败: {result.error_message}")
            return False
    
    def send_file(self, contact: str, file_path: str) -> bool:
        """
        发送文件/图片消息（通过Controller，统一复制粘贴）
        
        Args:
            contact: 联系人名称
            file_path: 文件路径
        
        Returns:
            是否发送成功
        """
        result = self.wechat.send_file(contact, file_path)
        if result.success:
            # 发送成功后，自动刷新该联系人的 UI hash（视觉基线）
            try:
                h = self.wechat.get_current_chat_hash(contact)
                if h:
                    self._save_visual_state(contact, h)
                    logger.info(
                        f"[MessageChannel] 已在发送文件后更新 UI hash: contact={contact}, hash={h[:16]}..."
                    )
            except Exception as e:
                # 刷新视觉 hash 失败不影响发送结果，只做告警日志
                logger.warning(f"[MessageChannel] 发送文件后更新 UI hash 失败: {e}")

            logger.info(f"文件已发送: {contact} -> {file_path}")
            return True
        else:
            logger.error(f"文件发送失败: {result.error_message}")
            return False
    
    def get_anchor_hash(self, contact: str) -> Optional[str]:
        """
        获取指定联系人的锚点hash
        
        Args:
            contact: 联系人名称
        
        Returns:
            锚点hash，如果不存在返回None
        """
        return self._anchor_hashes.get(contact)
    
    def reset_anchor(self, contact: str):
        """
        重置指定联系人的锚点（用于重新开始读取）；同时清除该联系人的视觉状态基线。
        
        Args:
            contact: 联系人名称
        """
        if contact in self._anchor_hashes:
            del self._anchor_hashes[contact]
        if contact in self._seen_hashes:
            del self._seen_hashes[contact]
        if contact in self._readers:
            del self._readers[contact]
        self._anchor_init_failed.discard(contact)
        self.wechat.clear_chat_state(contact)
        self._clear_visual_state(contact)
        self._save_anchor_state()
        logger.info(f"已重置锚点: {contact}")
