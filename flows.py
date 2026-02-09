"""微信交互流程模块

组合基础操作，实现完整的微信交互业务流程。

核心流程：
- open_chat(): 打开指定聊天窗口
- send_message(): 发送消息
- read_new_messages(): 读取新消息

注意事项：
1. 所有定位相关的逻辑已移除，应使用 element_locator 模块获取元素位置
2. 流程执行应记录详细日志
3. 关键步骤应保存截图用于调试
4. 流程应支持重试机制

依赖模块：
- screen: 屏幕操作
- actions: 基础操作
- element_locator: 元素定位（新增）
- models: 数据模型
"""

import hashlib
import time
import logging
from typing import Optional, Union, List, Any
from datetime import datetime, timezone
from collections import deque

# 支持相对导入（作为模块）和绝对导入（直接运行/独立目录）
try:
    from .models import Message, FlowResult, TaskType, WeChatConfig
except ImportError:
    from models import Message, FlowResult, TaskType, WeChatConfig

# 支持相对导入（作为模块）和绝对导入（直接运行）
try:
    from .screen import get_wechat_hwnd, capture_window
    from .actions import (
        activate_window,
        click,
        hotkey,
        paste_text,
        human_delay,
        wait,
        copy_text_at,
        scroll_chat_area_up,
    )
    import pyperclip
    from .element_locator import (
        locate_all_elements,
        locate_all_contact_avatars_in_list,
        get_contact_name,
        save_chat_state,
    )
    from .contact_mapper import ContactUserMapper
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from screen import get_wechat_hwnd, capture_window
    from actions import (
        activate_window,
        click,
        hotkey,
        paste_text,
        human_delay,
        wait,
        copy_text_at,
        scroll_chat_area_up,
    )
    from element_locator import (
        locate_all_elements,
        locate_all_contact_avatars_in_list,
        get_contact_name,
        save_chat_state,
    )
    from contact_mapper import ContactUserMapper

logger = logging.getLogger(__name__)


def _first_locate_result(val: Any) -> Any:
    """从 positions 的值中取单个 LocateResult（可能是 list 或单个）。"""
    if val is None:
        return None
    if isinstance(val, list):
        for r in val:
            if getattr(r, "success", False):
                return r
        return val[0] if val else None
    return val


def open_chat(contact_name: str, config: Optional[WeChatConfig] = None, require_red_point: bool = False) -> FlowResult:
    """
    打开指定联系人的聊天窗口
    
    流程步骤：
    1. 激活微信窗口
    2. 判断当前联系人是否是目标联系人
    3. 如果是，直接返回成功
    4. 如果不是，定位 profile_photo_in_list 并点击
    5. 如果找不到 profile_photo_in_list，直接失败
    
    Args:
        contact_name: 联系人名称
        config: 配置对象，None则使用默认配置
        require_red_point: 是否要求必须检测到红点才允许点击（默认False）。
            - False：允许在“无红点”的情况下也切换联系人（适合 CLI/机器人按次调用模式）。
            - True：仅当检测到红点时才允许点击联系人列表（更保守的安全措施）。
    
    Returns:
        流程执行结果
    """
    start_time = time.time()
    task_type = TaskType.OPEN_CHAT
    
    try:
        # 获取窗口句柄
        try:
            hwnd = get_wechat_hwnd()
            logger.debug(f"获取到窗口句柄: {hwnd}")
        except Exception as e:
            raise Exception(f"获取微信窗口句柄失败: {str(e)}，请确保微信已打开")
        
        logger.info(f"开始打开聊天窗口: {contact_name}")
        
        # 步骤1: 激活窗口
        if not activate_window(None):
            logger.warning("首次激活窗口失败，尝试重新获取句柄")
            hwnd = get_wechat_hwnd()
            if not activate_window(hwnd):
                raise Exception("激活窗口失败，请确保微信窗口可见且未被其他程序遮挡")
        human_delay(0.2, 0.3)
        
        # 步骤2: 判断当前联系人是否是目标联系人
        logger.info(f"[open_chat] 检查当前联系人，目标联系人: {contact_name}")
        current_contact = get_contact_name()
        if current_contact:
            current_contact = current_contact.strip()
            logger.info(f"[open_chat] 当前联系人: '{current_contact}'")
            if current_contact == contact_name.strip():
                logger.info(f"[open_chat] ✓ 当前已经是目标联系人: {contact_name}，无需操作，跳过切换")
                execution_time = time.time() - start_time
                return FlowResult(
                    success=True,
                    task_type=task_type,
                    execution_time=execution_time,
                    data={"contact_name": contact_name, "skipped": True}
                )
            else:
                logger.info(f"[open_chat] ⚠ 当前联系人 '{current_contact}' 与目标联系人 '{contact_name}' 不同，需要切换")
        else:
            logger.info(f"[open_chat] ⚠ 无法获取当前联系人名字，可能不在聊天界面，将尝试切换到 {contact_name}")
        
        # 步骤3: 定位 profile_photo_in_list
        logger.info(f"定位联系人列表中的头像: {contact_name}")
        screenshot = capture_window(hwnd)
        
        # 获取 contact_id（用于定位特定联系人的头像模板）
        # 注意：不要在函数内再次 import ContactUserMapper，否则会把它变成“局部变量”，影响后续回退分支的类型/绑定分析
        contact_id = None
        try:
            contact_mapper = ContactUserMapper()
            contact_id = contact_mapper.get_contact_id(contact_name)
        except Exception as e:
            logger.debug(f"获取contact_id失败: {e}，将使用contact_name定位头像")
        
        positions = locate_all_elements(screenshot, contact_name=contact_name, contact_id=contact_id)
        
        # 可选安全措施：如果 require_red_point=True，只有检测到红点后才允许点击联系人列表
        if require_red_point:
            red_point_result = _first_locate_result(positions.get("new_message_red_point"))
            if not red_point_result or not getattr(red_point_result, "success", False):
                logger.warning(
                    f"[open_chat] ⚠ 未检测到红点（require_red_point=True），将不点击联系人列表。"
                    f" 当前联系人: {current_contact or '未知'}, 目标联系人: {contact_name}"
                )
                raise Exception("未检测到红点，按 require_red_point=True 配置禁止切换联系人")
            rp_x, rp_y = getattr(red_point_result, "x", None), getattr(red_point_result, "y", None)
            rp_conf = getattr(red_point_result, "confidence", 0.0)
            logger.info(f"[open_chat] ✓ 检测到红点: ({rp_x}, {rp_y}), 置信度={rp_conf:.3f}，允许点击联系人列表")
        else:
            logger.debug(f"[open_chat] require_red_point=False，跳过红点检查（允许非红点场景下的切换）")
        
        profile_photo_result = _first_locate_result(positions.get("profile_photo_in_list"))
        # 回退：如果 locate_all_elements 没找到列表头像，用“一次性定位所有联系人头像”再按目标联系人过滤一次
        # 该逻辑与 test_element_locator.py 的联系人头像测试路径一致，通常更稳健
        if (not profile_photo_result) or (not getattr(profile_photo_result, "success", False)):
            try:
                mapper_for_fallback = ContactUserMapper()
                all_contacts_in_list = locate_all_contact_avatars_in_list(
                    screenshot=screenshot,
                    threshold=0.7,
                    contact_mapper=mapper_for_fallback,
                    enabled_contacts_only=False,
                )
                candidates = [
                    c for c in all_contacts_in_list
                    if c.contact_name == contact_name and getattr(c.locate_result, "success", False)
                ]
                if candidates:
                    # 取置信度最高的一个
                    candidates.sort(key=lambda c: getattr(c.locate_result, "confidence", 0.0), reverse=True)
                    profile_photo_result = candidates[0].locate_result
                    logger.info(
                        "[open_chat] 回退成功：通过 locate_all_contact_avatars_in_list 定位到联系人头像: %s (conf=%.3f)",
                        contact_name,
                        getattr(profile_photo_result, "confidence", 0.0),
                    )
            except Exception as e:
                logger.debug(f"[open_chat] 回退定位联系人头像失败: {e}")
        if not profile_photo_result or not getattr(profile_photo_result, "success", False):
            logger.error(f"未找到联系人 '{contact_name}' 的头像，可能不在联系人列表中")
            raise Exception(f"未找到联系人 '{contact_name}' 的头像，可能不在联系人列表中")
        
        pp_x, pp_y = getattr(profile_photo_result, "x", None), getattr(profile_photo_result, "y", None)
        if pp_x is None or pp_y is None:
            raise Exception("联系人头像位置无效（x 或 y 为空）")
        # 步骤4: 点击头像（默认允许无红点切换）
        logger.debug(f"点击联系人头像，位置: ({pp_x}, {pp_y})")
        if not click(pp_x, pp_y, hwnd):
            raise Exception("点击联系人头像失败")
        human_delay(0.5, 0.7)
        
        execution_time = time.time() - start_time
        logger.info(f"成功打开聊天窗口: {contact_name}，耗时: {execution_time:.2f}秒")
        
        return FlowResult(
            success=True,
            task_type=task_type,
            execution_time=execution_time,
            data={"contact_name": contact_name}
        )
    
    except Exception as e:
        execution_time = time.time() - start_time
        error_msg = f"打开聊天窗口失败: {str(e)}"
        logger.error(error_msg)
        
        return FlowResult(
            success=False,
            task_type=task_type,
            execution_time=execution_time,
            error_message=error_msg
        )


def open_chat_via_search(contact_name: str, config: Optional[WeChatConfig] = None) -> FlowResult:
    """
    保险打开聊天窗口：通过顶部搜索框搜索联系人并打开。

    典型交互：
    1) 点击搜索框
    2) 输入联系人名称
    3) 回车

    说明：
    - 该函数是“新流程”，不修改/不依赖 open_chat 的列表头像点击路径。
    - 适用于：联系人不在当前可视列表、列表头像定位不稳定、机器人后台按次调用希望更稳健时。
    """
    start_time = time.time()
    task_type = TaskType.OPEN_CHAT

    contact_name = (contact_name or "").strip()
    if not contact_name:
        return FlowResult(
            success=False,
            task_type=task_type,
            execution_time=0.0,
            error_message="contact_name 不能为空",
        )

    try:
        # 获取窗口句柄
        try:
            hwnd = get_wechat_hwnd()
            logger.debug(f"获取到窗口句柄: {hwnd}")
        except Exception as e:
            raise Exception(f"获取微信窗口句柄失败: {str(e)}，请确保微信已打开")

        logger.info(f"开始通过搜索框打开聊天窗口: {contact_name}")

        # 激活窗口
        if not activate_window(None):
            logger.warning("首次激活窗口失败，尝试重新获取句柄")
            hwnd = get_wechat_hwnd()
            if not activate_window(hwnd):
                raise Exception("激活窗口失败，请确保微信窗口可见且未被其他程序遮挡")
        human_delay(0.2, 0.3)

        # 定位搜索框
        screenshot = capture_window(hwnd)
        positions = locate_all_elements(screenshot)
        search_bar_result = _first_locate_result(positions.get("search_bar"))
        if not search_bar_result or not getattr(search_bar_result, "success", False):
            raise Exception("未找到搜索框（search_bar），可能不在主界面")
        sb_x, sb_y = getattr(search_bar_result, "x", None), getattr(search_bar_result, "y", None)
        if sb_x is None or sb_y is None:
            raise Exception("搜索框位置无效（x 或 y 为空）")

        # 点击搜索框并输入联系人名
        logger.debug(f"点击搜索框，位置: ({sb_x}, {sb_y})")
        if not click(sb_x, sb_y, hwnd):
            raise Exception("点击搜索框失败")
        human_delay(0.15, 0.25)

        # 清空并输入（用剪贴板更稳定）
        hotkey("ctrl", "a", hwnd=hwnd)
        human_delay(0.05, 0.1)
        hotkey("delete", hwnd=hwnd)
        human_delay(0.05, 0.1)

        if not paste_text(contact_name, hwnd):
            raise Exception("输入联系人名称失败（paste_text 失败）")
        human_delay(0.15, 0.25)

        # 回车打开
        if not hotkey("enter", hwnd=hwnd):
            raise Exception("按 Enter 失败（无法执行搜索打开）")
        human_delay(0.6, 0.9)

        # 校验是否切到目标聊天窗口（OCR 识别）
        current_contact = get_contact_name()
        if current_contact:
            current_contact = current_contact.strip()
        if current_contact != contact_name:
            logger.warning(
                "通过搜索打开后联系人不一致：current=%r, target=%r（可能是搜索结果未命中或 UI 未稳定）",
                current_contact,
                contact_name,
            )

        execution_time = time.time() - start_time
        return FlowResult(
            success=True,
            task_type=task_type,
            execution_time=execution_time,
            data={
                "contact_name": contact_name,
                "current_contact": current_contact,
                "opened": (current_contact == contact_name),
                "method": "search_bar",
            },
        )

    except Exception as e:
        execution_time = time.time() - start_time
        error_msg = f"通过搜索框打开聊天窗口失败: {str(e)}"
        logger.error(error_msg)
        return FlowResult(
            success=False,
            task_type=task_type,
            execution_time=execution_time,
            error_message=error_msg,
        )


def send_message(text: str, config: Optional[WeChatConfig] = None) -> FlowResult:
    """
    发送消息
    
    流程步骤：
    1. 确保窗口在前台
    2. 定位输入框（使用 element_locator 获取 input_box_anchor）
    3. 点击输入框
    4. 清空输入框（Ctrl+A + Delete）
    5. 输入消息内容（使用剪贴板粘贴）
    6. 按 Enter 发送消息
    
    Args:
        text: 消息内容
        config: 配置对象，None则使用默认配置
    
    Returns:
        流程执行结果
    """
    start_time = time.time()
    task_type = TaskType.SEND_MESSAGE
    
    try:
        # 获取窗口句柄
        try:
            hwnd = get_wechat_hwnd()
            logger.debug(f"获取到窗口句柄: {hwnd}")
        except Exception as e:
            raise Exception(f"获取微信窗口句柄失败: {str(e)}，请确保微信已打开")
        
        logger.info(f"开始发送消息: {text[:20]}...")
        
        # 步骤1: 确保窗口在前台
        if not activate_window(None):
            logger.warning("首次激活窗口失败，尝试重新获取句柄")
            hwnd = get_wechat_hwnd()
            if not activate_window(hwnd):
                raise Exception("激活窗口失败，请确保微信窗口可见且未被其他程序遮挡")
        human_delay(0.2, 0.3)
        
        # 步骤2: 定位输入框（使用 element_locator）
        logger.debug("定位输入框")
        screenshot = capture_window(hwnd)
        positions = locate_all_elements(screenshot)
        
        input_box_result = _first_locate_result(positions.get("input_box_anchor"))
        if not input_box_result or not getattr(input_box_result, "success", False):
            raise Exception("未找到输入框，可能不在聊天界面")
        ib_x, ib_y = getattr(input_box_result, "x", None), getattr(input_box_result, "y", None)
        if ib_x is None or ib_y is None:
            raise Exception("输入框位置无效（x 或 y 为空）")
        # 步骤3: 点击输入框
        logger.debug(f"点击输入框，位置: ({ib_x}, {ib_y})")
        if not click(ib_x, ib_y, hwnd):
            raise Exception("点击输入框失败")
        human_delay(0.3, 0.4)
        
        # 步骤4: 清空输入框
        logger.debug("清空输入框")
        if not hotkey('ctrl', 'a', hwnd=hwnd):
            raise Exception("按 Ctrl+A 失败")
        human_delay(0.1, 0.15)
        if not hotkey('delete', hwnd=hwnd):
            raise Exception("按 Delete 失败")
        human_delay(0.1, 0.15)
        
        # 步骤5: 输入消息内容
        logger.debug(f"输入消息内容: {text[:20]}...")
        if not paste_text(text, hwnd):
            raise Exception("粘贴消息内容失败")
        human_delay(0.3, 0.4)
        
        # 步骤6: 按 Enter 发送消息
        logger.debug("按 Enter 发送消息")
        if not hotkey('enter', hwnd=hwnd):
            raise Exception("按 Enter 失败")
        human_delay(0.3, 0.4)
        
        # 步骤7: 保存聊天状态（用于后续判断新消息）
        logger.debug("保存聊天状态")
        try:
            save_chat_state()
        except Exception as e:
            logger.warning(f"保存聊天状态失败: {e}，不影响消息发送")
        
        execution_time = time.time() - start_time
        logger.info(f"成功发送消息，耗时: {execution_time:.2f}秒")
        
        return FlowResult(
            success=True,
            task_type=task_type,
            execution_time=execution_time,
            data={"message": text}
        )
    
    except Exception as e:
        execution_time = time.time() - start_time
        error_msg = f"发送消息失败: {str(e)}"
        logger.error(error_msg)
        
        return FlowResult(
            success=False,
            task_type=task_type,
            execution_time=execution_time,
            error_message=error_msg
        )


def send_text_to_contact(contact_name: str, text: str, config: Optional[WeChatConfig] = None) -> FlowResult:
    """
    向指定联系人发送文本消息（组合流程）
    
    流程步骤：
    1. 打开聊天窗口
    2. 发送消息
    
    Args:
        contact_name: 联系人名称
        text: 消息内容
        config: 配置对象，None则使用默认配置
    
    Returns:
        流程执行结果
    """
    start_time = time.time()
    task_type = TaskType.SEND_MESSAGE
    
    try:
        logger.info(f"开始向 {contact_name} 发送消息: {text[:20]}...")
        
        # 步骤1: 打开聊天窗口
        open_result = open_chat(contact_name, config)
        if not open_result.success:
            raise Exception(f"打开聊天窗口失败: {open_result.error_message}")
        
        # 步骤2: 发送消息
        send_result = send_message(text, config)
        if not send_result.success:
            raise Exception(f"发送消息失败: {send_result.error_message}")
        
        execution_time = time.time() - start_time
        logger.info(f"成功向 {contact_name} 发送消息，总耗时: {execution_time:.2f}秒")
        
        return FlowResult(
            success=True,
            task_type=task_type,
            execution_time=execution_time,
            data={
                "contact_name": contact_name,
                "message": text,
                "open_chat_time": open_result.execution_time,
                "send_message_time": send_result.execution_time
            }
        )
    
    except Exception as e:
        execution_time = time.time() - start_time
        error_msg = f"向 {contact_name} 发送消息失败: {str(e)}"
        logger.error(error_msg)
        
        return FlowResult(
            success=False,
            task_type=task_type,
            execution_time=execution_time,
            error_message=error_msg
        )


def read_new_messages(
    contact_name: Optional[str] = None,
    config: Optional[WeChatConfig] = None,
    anchor_hash: Optional[str] = None,
    last_message_hash: Optional[str] = None,  # 兼容旧接口
    seen_fingerprints: Optional[deque] = None,  # 兼容旧接口
    max_scan_count: int = 5,  # 已废弃，保留兼容性
    max_pages: int = 5,  # 已废弃，保留兼容性
) -> FlowResult:
    """
    读取当前聊天窗口的新消息
    
    流程步骤：
    1. 优先从短期记忆获取锚点（如果提供了contact_name且anchor_hash为None）
    2. 如果没有短期记忆，使用提供的anchor_hash或当前最下面的消息作为锚点
    3. 激活微信窗口
    4. 定位聊天区域中的头像（profile_photo_in_chat）
    5. 从头像中心向右移动65px获取信息气泡内部的位置
    6. 双击气泡实现文字内容全选，然后复制
    7. 从下到上（新到旧）依次获取所有消息
    8. 每获取一个都与锚点比较，匹配到锚点就停止
    9. 如果当前页全部读完也停止
    
    锚点获取优先级：
    1. 如果提供了anchor_hash参数，直接使用
    2. 如果提供了contact_name且anchor_hash为None，优先从短期记忆获取最新一条消息作为锚点
    3. 如果没有短期记忆，使用当前最下面的消息作为锚点（首次调用时）
    
    Args:
        contact_name: 联系人名称（可选，用于日志和从短期记忆获取锚点）
        config: 配置对象，None则使用默认配置
        anchor_hash: 锚点消息的hash值（可选，如果为None且提供了contact_name，则从短期记忆获取）
        last_message_hash: 兼容旧接口，等同于anchor_hash
        seen_fingerprints: 已废弃，保留兼容性
        max_scan_count: 已废弃，保留兼容性
        max_pages: 已废弃，保留兼容性
    
    Returns:
        流程执行结果（data字段包含消息列表和新的锚点hash）
    """
    start_time = time.time()
    task_type = TaskType.READ_MESSAGES
    
    # 兼容旧接口：如果提供了last_message_hash，使用它作为anchor_hash
    if anchor_hash is None and last_message_hash is not None:
        anchor_hash = last_message_hash
    
    try:
        # 获取窗口句柄
        try:
            hwnd = get_wechat_hwnd()
            logger.debug(f"获取到窗口句柄: {hwnd}")
        except Exception as e:
            raise Exception(f"获取微信窗口句柄失败: {str(e)}，请确保微信已打开")
        
        logger.info(f"开始读取新消息: {contact_name or '当前窗口'}")
        
        # 预处理锚点：如果输入的是文本，先计算hash
        anchor_hash_to_compare = None
        if anchor_hash:
            # 检查是否是hash格式（32位hex字符串），如果不是则说明是文本
            is_hash_format = len(anchor_hash) == 32 and all(c in '0123456789abcdef' for c in anchor_hash.lower())
            if is_hash_format:
                anchor_hash_to_compare = anchor_hash
                logger.debug(f"锚点hash: {anchor_hash[:16]}...")
            else:
                # 不是hash格式，当作文本处理，计算hash
                anchor_hash_to_compare = hashlib.md5(anchor_hash.strip().encode('utf-8')).hexdigest()
                logger.debug(f"锚点文本: {anchor_hash[:30]}... -> hash: {anchor_hash_to_compare[:16]}...")
        
        # 步骤1: 激活窗口
        if not activate_window(None):
            logger.warning("首次激活窗口失败，尝试重新获取句柄")
            hwnd = get_wechat_hwnd()
            if not activate_window(hwnd):
                raise Exception("激活窗口失败，请确保微信窗口可见且未被其他程序遮挡")
        human_delay(0.2, 0.3)
        
        # 步骤2: 定位聊天区域中的头像
        logger.info(f"定位聊天区域中的头像: {contact_name or '当前窗口'}")
        screenshot = capture_window(hwnd)
        
        # 获取contact_id（用于定位特定联系人的头像模板）
        contact_id = None
        if contact_name:
            try:
                from .contact_mapper import ContactUserMapper
                contact_mapper = ContactUserMapper()
                contact_id = contact_mapper.get_contact_id(contact_name)
            except Exception as e:
                logger.debug(f"获取contact_id失败: {e}，将使用contact_name定位头像")
        
        positions = locate_all_elements(screenshot, contact_name=contact_name, contact_id=contact_id)
        
        profile_photo_in_chat = positions.get("profile_photo_in_chat")
        if not profile_photo_in_chat or not isinstance(profile_photo_in_chat, list) or len(profile_photo_in_chat) == 0:
            logger.error(f"未找到聊天区域中的头像，可能不在聊天界面或没有消息 (联系人: {contact_name or '未知'})")
            raise Exception("未找到聊天区域中的头像，可能不在聊天界面或没有消息")
        
        # 步骤3: 从头像位置计算气泡位置（向右移动65px）
        # 按y坐标从大到小排序（从下到上，新到旧）
        chat_avatars = [r for r in profile_photo_in_chat if getattr(r, "success", False)]
        chat_avatars.sort(key=lambda r: r.y if r.y is not None else 0, reverse=True)
        
        logger.info(f"找到 {len(chat_avatars)} 个聊天头像，开始从下到上读取消息（新到旧）")
        if len(chat_avatars) > 0:
            logger.debug(f"头像y坐标列表（从下到上，新到旧）: {[r.y for r in chat_avatars[:5]]}...")
        
        # 记录最下面的头像位置（用于确定锚点）
        bottom_avatar = chat_avatars[0] if chat_avatars else None
        bottom_bubble_x = (bottom_avatar.x + 65) if (bottom_avatar and bottom_avatar.x is not None) else None
        bottom_bubble_y = bottom_avatar.y if bottom_avatar else None
        
        messages = []
        anchor_matched = False
        bottom_message_hash = None  # 最下面消息的hash（用于锚点）
        bottom_message_text = None  # 最下面消息的文本（用于锚点）
        
        # 步骤4: 依次获取每条消息
        for i, avatar_result in enumerate(chat_avatars):
            # 计算气泡位置（头像中心向右移动65px）
            ax, ay = avatar_result.x, avatar_result.y
            if ax is None or ay is None:
                logger.warning(f"消息 {i+1} 头像位置无效，跳过")
                continue
            bubble_x = ax + 65
            bubble_y = ay
            
            logger.debug(f"处理消息 {i+1}/{len(chat_avatars)}: 头像位置=({ax}, {ay}), 气泡位置=({bubble_x}, {bubble_y})")
            
            # 双击气泡复制文本
            text = copy_text_at(bubble_x, bubble_y, hwnd, double_click=True)
            
            if not text or not text.strip():
                logger.warning(f"消息 {i+1} 复制失败或为空，跳过")
                # 如果是最下面的消息（第一条）复制失败，记录位置以便重试
                if i == 0:
                    logger.warning(f"最下面的消息复制失败，将在最后重试")
                continue
            
            # 计算消息hash（用于锚点匹配）
            message_hash = hashlib.md5(text.strip().encode('utf-8')).hexdigest()
            
            # 记录最下面消息的hash（第一条成功读取的消息）
            if i == 0 or bottom_message_hash is None:
                bottom_message_hash = message_hash
                bottom_message_text = text.strip()
                logger.debug(f"记录最下面消息的hash: {message_hash[:16]}... (内容: {text[:30]}...)")
            
            # 检查是否匹配锚点
            if anchor_hash_to_compare and message_hash == anchor_hash_to_compare:
                logger.info(f"匹配到锚点，停止读取（消息 {i+1}）")
                logger.info(f"匹配的消息内容: {text[:50]}...")
                anchor_matched = True
                break
            
            # 创建消息对象
            # 注意：这里无法确定发送者，暂时使用contact_name或"未知"
            message = Message(
                sender=contact_name or "未知",
                content=text.strip(),
                timestamp=datetime.now(timezone.utc),  # 无法获取真实时间戳，使用当前时间
                message_type="text",
                is_sent=False  # 无法确定，暂时设为False
            )
            messages.append({
                "message": message,
                "hash": message_hash,
                "position": (bubble_x, bubble_y)
            })
            
            logger.info(f"成功读取消息 {i+1}/{len(chat_avatars)} (y={bubble_y}, 从下到上): {text[:30]}... (hash: {message_hash[:16]}...)")
            human_delay(0.1, 0.15)  # 每条消息之间稍作延迟
        
        # 如果最下面的消息复制失败，尝试重试
        if bottom_message_hash is None and bottom_bubble_x is not None and bottom_bubble_y is not None and isinstance(bottom_bubble_y, int):
            logger.warning("最下面的消息复制失败，尝试重试...")
            human_delay(0.3, 0.5)  # 等待一下再重试
            retry_text = copy_text_at(bottom_bubble_x, bottom_bubble_y, hwnd, double_click=True)
            if retry_text and retry_text.strip():
                bottom_message_hash = hashlib.md5(retry_text.strip().encode('utf-8')).hexdigest()
                bottom_message_text = retry_text.strip()
                logger.info(f"重试成功，最下面消息: {retry_text[:30]}... (hash: {bottom_message_hash[:16]}...)")
            else:
                logger.error("重试仍然失败，无法获取最下面消息的hash")
        
        # 确定新的锚点（最下面的消息，即第一条消息，因为是从下到上读取）
        # 如果有新消息，使用最下面消息的hash作为新锚点（最下面的，最新的）
        # 如果没有新消息，保持原有锚点（避免下次又认为是首次调用）
        new_anchor_hash = None
        if bottom_message_hash:
            # 使用最下面消息的hash作为锚点
            new_anchor_hash = bottom_message_hash
            anchor_message = bottom_message_text[:30] if bottom_message_text else "未知"
            logger.info(f"新的锚点hash: {new_anchor_hash[:16]}... (最下面的消息: {anchor_message}...)")
        elif messages:
            # 如果没有记录最下面消息的hash，使用第一条成功读取的消息
            new_anchor_hash = messages[0]["hash"]
            anchor_message = messages[0]["message"].content if hasattr(messages[0]["message"], "content") else str(messages[0]["message"])
            logger.warning(f"使用第一条成功读取的消息作为锚点: {new_anchor_hash[:16]}... (内容: {anchor_message[:30]}...)")
        elif anchor_hash:
            # 没有新消息，但保持原有锚点
            new_anchor_hash = anchor_hash
            logger.debug(f"没有新消息，保持原有锚点hash: {anchor_hash[:16]}...")
        
        execution_time = time.time() - start_time
        logger.info(f"成功读取消息，找到 {len(messages)} 条新消息，耗时: {execution_time:.2f}秒")
        if anchor_matched:
            logger.info("已匹配到锚点，停止读取")
        
        return FlowResult(
            success=True,
            task_type=task_type,
            execution_time=execution_time,
            data={
                "messages": [m["message"] for m in messages],
                "count": len(messages),
                "anchor_hash": new_anchor_hash,
                "anchor_matched": anchor_matched
            }
        )
    
    except Exception as e:
        execution_time = time.time() - start_time
        error_msg = f"读取新消息失败: {str(e)}"
        logger.error(error_msg)
        
        return FlowResult(
            success=False,
            task_type=task_type,
            execution_time=execution_time,
            error_message=error_msg
        )


def get_initial_anchor(
    contact_name: Optional[str] = None,
    config: Optional[WeChatConfig] = None,
) -> FlowResult:
    """
    首次启动时获取当前最下面的消息作为锚点。
    
    首次锚点生成规则（不变量）：
    - 必须在 UI 稳定态下调用（若 UI 仍在滚动/未稳定，「最下一条」可能不是最终态）。
    - 必须成功读取 ≥1 条消息才能生成锚点。
    - 若读取失败 → 不生成锚点；调用方（如 message_channel）禁止 fallback 到「下一次再生成」，
      否则极端情况下首次锚点偏移会导致后续读取全部错位（由 message_channel._anchor_init_failed 保证）。
    
    流程步骤：
    1. 确保打开的是对应联系人的聊天窗口（如果不是，先打开）
    2. 激活微信窗口
    3. 定位聊天区域中的头像（profile_photo_in_chat）
    4. 找到最下面的头像（y坐标最大）
    5. 从头像中心向右移动65px获取信息气泡内部的位置
    6. 双击气泡复制文本
    7. 计算消息hash作为锚点
    
    Args:
        contact_name: 联系人名称（必须提供，用于确保打开正确的聊天窗口）
        config: 配置对象，None则使用默认配置
    
    Returns:
        流程执行结果（data字段包含anchor_hash和source字段，source为"current_message"）；失败时不写入锚点。
    """
    start_time = time.time()
    task_type = TaskType.READ_MESSAGES
    
    try:
        if not contact_name:
            raise Exception("contact_name 必须提供，用于确保打开正确的聊天窗口")
        
        # 获取窗口句柄
        try:
            hwnd = get_wechat_hwnd()
            logger.debug(f"获取到窗口句柄: {hwnd}")
        except Exception as e:
            raise Exception(f"获取微信窗口句柄失败: {str(e)}，请确保微信已打开")
        
        logger.info(f"开始获取初始锚点: {contact_name} (使用当前最下面的消息)")
        
        # 步骤1: 确保打开的是对应联系人的聊天窗口（如果没有短期记忆，才需要执行）
        logger.debug("检查当前聊天窗口是否是目标联系人")
        current_contact = get_contact_name()
        if not current_contact or current_contact.strip() != contact_name.strip():
            logger.info(f"当前聊天窗口不是目标联系人（当前: {current_contact or '未知'}），先打开聊天窗口")
            open_result = open_chat(contact_name, config)
            if not open_result.success:
                raise Exception(f"打开聊天窗口失败: {open_result.error_message}")
            human_delay(0.5, 0.7)  # 等待聊天窗口打开
        else:
            logger.debug(f"当前已经是目标联系人: {contact_name}，无需打开")
        
        # 步骤2: 激活窗口
        if not activate_window(None):
            logger.warning("首次激活窗口失败，尝试重新获取句柄")
            hwnd = get_wechat_hwnd()
            if not activate_window(hwnd):
                raise Exception("激活窗口失败，请确保微信窗口可见且未被其他程序遮挡")
        else:
            # 确保 hwnd 已定义
            if 'hwnd' not in locals():
                hwnd = get_wechat_hwnd()
        human_delay(0.2, 0.3)
        
        # 步骤3: 定位聊天区域中的头像
        logger.info(f"定位聊天区域中的头像: {contact_name or '当前窗口'}")
        screenshot = capture_window(hwnd)
        
        # 获取contact_id（用于定位特定联系人的头像模板）
        contact_id = None
        if contact_name:
            try:
                from .contact_mapper import ContactUserMapper
                contact_mapper = ContactUserMapper()
                contact_id = contact_mapper.get_contact_id(contact_name)
            except Exception as e:
                logger.debug(f"获取contact_id失败: {e}，将使用contact_name定位头像")
        
        positions = locate_all_elements(screenshot, contact_name=contact_name, contact_id=contact_id)
        
        profile_photo_in_chat = positions.get("profile_photo_in_chat")
        if not profile_photo_in_chat or not isinstance(profile_photo_in_chat, list) or len(profile_photo_in_chat) == 0:
            logger.error(f"未找到聊天区域中的头像，可能不在聊天界面或没有消息 (联系人: {contact_name or '未知'})")
            raise Exception("未找到聊天区域中的头像，可能不在聊天界面或没有消息")
        
        # 步骤4: 找到最下面的头像（y坐标最大）
        chat_avatars = [r for r in profile_photo_in_chat if r.success]
        if not chat_avatars:
            raise Exception("未找到有效的聊天头像")
        
        # 按y坐标从大到小排序（从下到上，新到旧），取第一个（最下面的，最新的）
        chat_avatars.sort(key=lambda r: r.y if r.y is not None else 0, reverse=True)
        bottom_avatar = chat_avatars[0]
        
        logger.info(f"找到 {len(chat_avatars)} 个聊天头像")
        logger.info(f"最下面的头像位置（y最大，最新）: ({bottom_avatar.x}, {bottom_avatar.y})")
        if len(chat_avatars) > 1:
            logger.debug(f"头像y坐标列表（从下到上）: {[r.y for r in chat_avatars[:5]]}...")
        
        # 步骤5: 计算气泡位置（头像中心向右移动65px）
        ax = bottom_avatar.x if bottom_avatar.x is not None else 0
        ay = bottom_avatar.y if bottom_avatar.y is not None else 0
        bubble_x = ax + 65
        bubble_y = ay

        # 步骤6: 双击气泡复制文本
        text = copy_text_at(bubble_x, bubble_y, hwnd, double_click=True)
        
        if not text or not text.strip():
            raise Exception("无法复制最下面的消息文本，可能消息为空或复制失败")
        
        # 步骤7: 计算消息hash作为锚点
        anchor_hash = hashlib.md5(text.strip().encode('utf-8')).hexdigest()
        
        execution_time = time.time() - start_time
        logger.info(f"成功获取初始锚点，耗时: {execution_time:.2f}秒")
        logger.info(f"锚点消息（最下面的消息，最新的）: {text[:50]}...")
        logger.info(f"锚点hash: {anchor_hash[:16]}...")
        logger.info(f"锚点位置: ({bubble_x}, {bubble_y}), 头像y坐标: {bottom_avatar.y}")
        
        return FlowResult(
            success=True,
            task_type=task_type,
            execution_time=execution_time,
            data={
                "anchor_hash": anchor_hash,
                "anchor_message": text.strip(),
                "position": (bubble_x, bubble_y),
                "source": "current_message"
            }
        )
    
    except Exception as e:
        execution_time = time.time() - start_time
        error_msg = f"获取初始锚点失败: {str(e)}"
        logger.error(error_msg)
        
        return FlowResult(
            success=False,
            task_type=task_type,
            execution_time=execution_time,
            error_message=error_msg,
            data={"anchor_hash": None}
        )