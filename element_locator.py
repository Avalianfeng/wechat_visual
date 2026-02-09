"""微信界面元素定位模块

用于定位微信窗口中的所有UI元素位置，保存位置信息供其他模块使用。

核心功能：
- locate_all_elements(): 定位所有UI元素并返回位置字典（推荐使用此函数获取位置）
- locate_all_contact_avatars_in_list(): 一次性定位联系人列表中所有配置联系人的头像位置（返回带联系人标识的结果列表）
- locate_all_contact_avatars_in_chat(): 一次性定位聊天区域中所有配置联系人的头像位置（返回带联系人标识的结果列表，支持群聊）
- get_contacts_with_new_message_red_point(): 扫描新消息红点，返回存在红点的联系人名称列表（不打开聊天、不读消息）
- get_element_bounds(): 根据元素位置和大小计算边界框
- save_element_positions(): 保存元素位置到JSON文件（用于调试和缓存）
- load_element_positions(): 从JSON文件加载元素位置（用于调试，不推荐作为主要数据源）

使用方式：
1. 推荐方式：直接调用 locate_all_elements() 获取实时位置
   ```python
   from wechat.element_locator import locate_all_elements
   positions = locate_all_elements()
   # positions 是字典，包含所有元素的位置信息
   # profile_photo_in_chat 是数组类型 List[LocateResult]
   # 其他元素是单个 LocateResult
   ```

2. 一次性定位所有联系人头像（列表区域）：
   ```python
   from wechat.element_locator import locate_all_contact_avatars_in_list
   from wechat.models import ContactLocateResult
   
   # 定位所有启用的联系人头像
   results = locate_all_contact_avatars_in_list()
   for contact_result in results:
       print(f"联系人: {contact_result.contact_name}")
       print(f"位置: ({contact_result.locate_result.x}, {contact_result.locate_result.y})")
       print(f"置信度: {contact_result.locate_result.confidence}")
   ```

3. 一次性定位所有联系人头像（聊天区域，支持群聊）：
   ```python
   from wechat.element_locator import locate_all_contact_avatars_in_chat
   from wechat.models import ContactLocateResult
   
   # 定位聊天区域中所有联系人的头像（支持群聊）
   results = locate_all_contact_avatars_in_chat()
   for contact_result in results:
       print(f"联系人: {contact_result.contact_name}")
       print(f"位置: ({contact_result.locate_result.x}, {contact_result.locate_result.y})")
       print(f"置信度: {contact_result.locate_result.confidence}")
   ```

2. JSON文件作用：
   - 主要用于调试：保存定位结果用于分析
   - 缓存作用：可以加载上次的定位结果（但可能不准确，因为窗口位置可能变化）
   - 不推荐作为主要数据源：应该每次调用 locate_all_elements() 获取实时位置
   
3. JSON文件位置：
   - 默认保存在 wechat/debug/element_positions.json（调试目录）

元素大小配置：
- 头像（profile_photo_in_list）：50*50px，在联系人列表中，只有一个
- 头像（profile_photo_in_chat）：50*50px，在聊天区域中，可能有多个（数组）
- 搜索框（search_bar）：180*40px（包含search_bar和search_bar_ing两种状态）
- 输入框（input_box_anchor）：不定（使用sticker_icon和send_button的中点定位）
- 发送按钮（send_button）：30*30px（包含send_button和send_button_default两种状态）
- 其他元素：30*30px

注意事项：
1. 所有坐标使用窗口内相对坐标（左上角为原点）
2. 元素位置为中心点坐标
3. 边界框为 (x, y, width, height) 格式
4. search_bar和send_button会尝试匹配两种状态，只保留一个结果
5. input_box_anchor通过sticker_icon和send_button的中点计算，需要先定位这两个元素
6. profile_photo_in_list和profile_photo_in_chat的定位逻辑：
   - 先在整个窗口中搜索所有头像
   - 根据分布规则判断：
     * 如果存在两个不同的x坐标，左边的是列表中的，右边的是聊天中的
     * 如果有两个y相同的坐标，则y坐标上都是聊天中的
     * 如果只有一个头像，检查是否在搜索框的左下方，如果是则是列表中的
     * 如果没有搜索框，则一定是聊天中的（为单独打开聊天窗口做准备）
"""

import json
import logging
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Union
import cv2
import numpy as np

# 感知哈希库（可选依赖）
try:
    import imagehash
    from PIL import Image
    IMAGEHASH_AVAILABLE = True
except ImportError:
    IMAGEHASH_AVAILABLE = False

# 支持相对导入（作为模块）和绝对导入（直接运行）
try:
    from .screen import get_wechat_hwnd, capture_window, save_screenshot
    from .locator import match_all_templates, put_chinese_text, ocr_region
    from .config import WeChatAutomationConfig
    from .models import LocateResult, LocateMethod, ContactLocateResult
    from .contact_mapper import ContactUserMapper
    from .chat_state_manager import ChatStateManager, get_global_manager
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from screen import get_wechat_hwnd, capture_window, save_screenshot
    from locator import match_all_templates, put_chinese_text, ocr_region
    from config import WeChatAutomationConfig
    from models import LocateResult, LocateMethod, ContactLocateResult
    from contact_mapper import ContactUserMapper
    from chat_state_manager import ChatStateManager, get_global_manager

logger = logging.getLogger(__name__)


def _get_single_result(
    positions: Dict[str, Union[LocateResult, List[LocateResult]]], key: str
) -> Optional[LocateResult]:
    """从 positions 中取单个 LocateResult；若为列表则取首项。"""
    v = positions.get(key)
    if v is None:
        return None
    if isinstance(v, list):
        return v[0] if v else None
    return v


# 元素大小配置（像素）
# 注意：input_box_anchor 的大小根据实际匹配结果确定（不定）
ELEMENT_SIZES = {
    "chat_message_icon": (30, 30),
    "three_point_icon": (30, 30),
    "pin_icon": (30, 30),  # 置顶图标
    "profile_photo_in_list": (50, 50),  # 联系人列表中的头像（只有一个）
    "profile_photo_in_chat": (50, 50),  # 聊天区域中的头像（可能有多个）
    "new_message_red_point": (15, 15),  # 新消息红点（在联系人列表头像右上角）
    "search_bar": (180, 40),  # 包含search_bar和search_bar_ing两种状态
    "sticker_icon": (30, 30),
    "save_icon": (30, 30),
    "file_icon": (30, 30),
    "screencap_icon": (30, 30),
    "tape_icon": (30, 30),  # 微信更新后新增，在截图图标右侧
    "voice_call_icon": (30, 30),
    "video_call_icon": (30, 30),
    "send_button": (30, 30),  # 包含send_button和send_button_default两种状态
    "input_box_anchor": None,  # 大小不定，使用sticker_icon和send_button的中点定位
}

# 元素定位顺序（注意：search_bar_ing和send_button_default不在此列表中，它们会与search_bar和send_button合并）
# 注意：search_bar必须在profile_photo之前，以便在判断头像时使用search_bar的位置
ELEMENT_ORDER = [
    "chat_message_icon",
    "three_point_icon",
    "pin_icon",  # 置顶图标（在区域上半部分20%搜索）
    "search_bar",  # 会尝试匹配search_bar和search_bar_ing，只保留一个（必须在头像之前）
    "profile_photo_in_list",  # 联系人列表中的头像（只有一个）
    "new_message_red_point",  # 新消息红点（在联系人列表头像右上角，依赖profile_photo_in_list）
    "profile_photo_in_chat",  # 聊天区域中的头像（可能有多个，数组）
    "sticker_icon",
    "save_icon",
    "file_icon",
    "screencap_icon",
    "tape_icon",
    "voice_call_icon",
    "video_call_icon",
    "send_button",  # 会尝试匹配send_button和send_button_default，只保留一个
    "input_box_anchor",  # 特殊处理：使用sticker_icon和send_button的中点
]

# 元素对应的模板路径键名
TEMPLATE_KEYS = {
    "chat_message_icon": "topbar_chat_message",
    "three_point_icon": "topbar_three_point",
    "pin_icon": "topbar_pin",  # 置顶图标
    "profile_photo_in_list": "profile_photo",  # 联系人列表中的头像
    "new_message_red_point": "new_message_red_point",  # 新消息红点（在联系人列表头像右上角）
    "profile_photo_in_chat": "profile_photo",  # 聊天区域中的头像（使用相同模板，但定位逻辑不同）
    "search_bar": "search_bar",  # 会尝试匹配search_bar和search_bar_ing
    "sticker_icon": "toolbar_sticker",
    "save_icon": "toolbar_save",
    "file_icon": "toolbar_file",
    "screencap_icon": "toolbar_screencap",
    "tape_icon": "toolbar_tape",
    "voice_call_icon": "toolbar_voice_call",
    "video_call_icon": "toolbar_video_call",
    "send_button": "send_button",  # 会尝试匹配send_button和send_button_default
    "input_box_anchor": None,  # 特殊处理：使用sticker_icon和send_button的中点
}


def get_element_size(element_name: str) -> Tuple[int, int]:
    """
    获取元素大小
    
    Args:
        element_name: 元素名称
    
    Returns:
        (width, height) 元组
    """
    return ELEMENT_SIZES.get(element_name, (30, 30))


def _red_pixel_ratio_in_region(
    screenshot_bgr: np.ndarray,
    search_left: int,
    search_top: int,
    search_right: int,
    search_bottom: int,
) -> Tuple[float, int, int]:
    """
    红点检测核心逻辑：在划定检测区域内统计红色像素面积占比。
    若占比大于配置的 RED_POINT_AREA_RATIO_THRESHOLD（默认 70%）则判定为有红点。

    Args:
        screenshot_bgr: BGR 截图
        search_left, search_top, search_right, search_bottom: 检测区域边界（像素）

    Returns:
        (red_ratio, center_x, center_y): 红色像素占比 [0,1]、红点中心 x/y（整图坐标）
        中心点为红色像素质心；若无红色像素则为区域几何中心。
    """
    if screenshot_bgr is None or len(screenshot_bgr.shape) < 3:
        return 0.0, (search_left + search_right) // 2, (search_top + search_bottom) // 2
    region = screenshot_bgr[search_top:search_bottom, search_left:search_right]
    if region.size == 0:
        return 0.0, (search_left + search_right) // 2, (search_top + search_bottom) // 2
    # OpenCV 读图是 BGR：channel0=B, channel1=G, channel2=R，拆开后变量名与通道一致
    b, g, r = cv2.split(region)
    # 红点判定（基于 R 通道，抗亮度/缩放/抗锯齿）：R>=180 且 R 明显高于 G、B
    red_mask = (r >= 180) & (r - g >= 40) & (r - b >= 40)
    total = region.shape[0] * region.shape[1]
    red_count = int(np.sum(red_mask))
    ratio = red_count / total if total else 0.0
    # 质心（红色像素）
    ys, xs = np.where(red_mask)
    if len(xs) > 0 and len(ys) > 0:
        cx = int(np.mean(xs)) + search_left
        cy = int(np.mean(ys)) + search_top
    else:
        cx = (search_left + search_right) // 2
        cy = (search_top + search_bottom) // 2
    return ratio, cx, cy


def get_element_bounds(
    x: int, 
    y: int, 
    element_name: str, 
    custom_size: Optional[Tuple[int, int]] = None,
    locate_result: Optional[LocateResult] = None
) -> Tuple[int, int, int, int]:
    """
    根据元素中心点坐标和大小计算边界框
    
    Args:
        x: 元素中心点X坐标
        y: 元素中心点Y坐标
        element_name: 元素名称
        custom_size: 自定义大小 (width, height)，如果为None则使用配置中的大小
        locate_result: 定位结果，如果元素大小不定，可以从这里获取region信息
    
    Returns:
        (x, y, width, height) 边界框
    """
    if custom_size:
        width, height = custom_size
    else:
        size = get_element_size(element_name)
        if size is None:
            # 大小不定，尝试从定位结果获取
            if locate_result and locate_result.region:
                _, _, width, height = locate_result.region
            else:
                # 如果都没有，使用默认值
                width, height = 100, 50
        else:
            width, height = size
    
    # 计算左上角坐标
    left = x - width // 2
    top = y - height // 2
    
    return (left, top, width, height)


def locate_all_elements(
    screenshot: Optional[np.ndarray] = None,
    threshold: float = 0.7,
    contact_name: Optional[str] = None,
    contact_id: Optional[str] = None
) -> Dict[str, Union[LocateResult, List[LocateResult]]]:
    """
    定位所有UI元素
    
    Args:
        screenshot: 窗口截图（BGR格式），如果为None则自动截取
        threshold: 模板匹配阈值（0.0-1.0）
        contact_name: 联系人名称（可选，用于获取特定联系人的头像模板）
        contact_id: 联系人ID（可选，用于获取特定联系人的头像模板）
    
    Returns:
        元素位置字典 {element_name: LocateResult 或 List[LocateResult]}
        注意：profile_photo_in_chat 返回 List[LocateResult]，其他元素返回 LocateResult
    """
    config = WeChatAutomationConfig
    
    # 如果没有提供截图，自动截取
    if screenshot is None:
        try:
            hwnd = get_wechat_hwnd()
            screenshot = capture_window(hwnd)
        except Exception as e:
            logger.error(f"获取窗口截图失败: {e}")
            return {}
    
    results = {}
    
    # 按顺序定位每个元素
    for element_name in ELEMENT_ORDER:
        result: LocateResult = LocateResult(success=False, error_message="")  # 各分支会覆盖；保证 result 始终已绑定
        try:
            # 特殊处理：search_bar - 尝试匹配search_bar和search_bar_ing，只保留一个
            if element_name == "search_bar":
                template_paths = []
                # 尝试基础模板
                base_path = config.TEMPLATE_PATHS.get("search_bar")
                if base_path and base_path.exists():
                    template_paths.append(base_path)
                # 尝试ing状态模板
                ing_path = config.TEMPLATE_PATHS.get("search_bar_ing")
                if ing_path and ing_path.exists():
                    template_paths.append(ing_path)
                
                if template_paths:
                    result = match_all_templates(screenshot, template_paths, threshold=threshold)
                else:
                    logger.debug(f"元素 {element_name} 模板不存在，跳过")
                    results[element_name] = LocateResult(
                        success=False,
                        error_message=f"模板文件不存在: search_bar"
                    )
                    continue
            
            # 特殊处理：send_button - 尝试匹配send_button和send_button_default，只保留一个
            elif element_name == "send_button":
                template_paths = []
                # 尝试基础模板
                base_path = config.TEMPLATE_PATHS.get("send_button")
                if base_path and base_path.exists():
                    template_paths.append(base_path)
                # 尝试default状态模板
                default_path = config.TEMPLATE_PATHS.get("send_button_default")
                if default_path and default_path.exists():
                    template_paths.append(default_path)
                
                if template_paths:
                    result = match_all_templates(screenshot, template_paths, threshold=threshold)
                else:
                    logger.debug(f"元素 {element_name} 模板不存在，跳过")
                    results[element_name] = LocateResult(
                        success=False,
                        error_message=f"模板文件不存在: send_button"
                    )
                    continue
            
            # 特殊处理：profile_photo_in_list 和 profile_photo_in_chat - 先找所有头像，再根据分布判断
            elif element_name == "profile_photo_in_list" or element_name == "profile_photo_in_chat":
                # 只在第一次处理时查找所有头像（两个元素会连续处理）
                # 如果已经处理过 profile_photo_in_list，profile_photo_in_chat 应该已经在 results 中了，直接跳过
                if element_name == "profile_photo_in_chat" and "profile_photo_in_chat" in results:
                    logger.debug(f"元素 {element_name} 已在之前处理过，跳过")
                    continue
                
                if element_name == "profile_photo_in_list":
                    # 优先使用联系人特定的头像模板
                    if contact_name or contact_id:
                        template_path = config.get_contact_profile_photo_path(
                            contact_name=contact_name or "",
                            contact_id=contact_id or ""
                        )
                        logger.debug(f"使用联系人特定头像模板: {template_path} (联系人: {contact_name or '未知'}, ID: {contact_id or '未知'})")
                    else:
                        # 向后兼容：使用默认头像
                        template_path = config.get_contact_profile_photo_path()
                        logger.debug(f"使用默认头像模板: {template_path}")
                    
                    if not template_path or not template_path.exists():
                        logger.warning(f"头像模板不存在: {template_path}，跳过定位")
                        results["profile_photo_in_list"] = LocateResult(
                            success=False,
                            error_message=f"头像模板文件不存在: {template_path}"
                        )
                        results["profile_photo_in_chat"] = []
                        continue
                    
                    # 在整个窗口中搜索所有头像
                    template = cv2.imread(str(template_path))
                    if template is None:
                        logger.warning(f"无法加载头像模板: {template_path}")
                        results["profile_photo_in_list"] = LocateResult(
                            success=False,
                            error_message=f"无法加载模板文件"
                        )
                        results["profile_photo_in_chat"] = []
                        continue
                    
                    # 转换为灰度图进行匹配
                    if len(screenshot.shape) == 3:
                        screenshot_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
                    else:
                        screenshot_gray = screenshot
                    
                    if len(template.shape) == 3:
                        template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
                    else:
                        template_gray = template
                    
                    # 模板匹配
                    match_result = cv2.matchTemplate(screenshot_gray, template_gray, cv2.TM_CCOEFF_NORMED)
                    
                    # 找到所有超过阈值的位置
                    locations = np.where(match_result >= threshold)
                    
                    # 收集所有匹配点
                    all_matches = []
                    for pt in zip(*locations[::-1]):  # Switch x and y coordinates
                        confidence = float(match_result[pt[1], pt[0]])
                        # 计算头像中心点
                        avatar_center_x = pt[0] + template_gray.shape[1] // 2
                        avatar_center_y = pt[1] + template_gray.shape[0] // 2
                        
                        all_matches.append({
                            'x': avatar_center_x,
                            'y': avatar_center_y,
                            'confidence': confidence
                        })
                    
                    # 去重：使用NMS（非极大值抑制）算法，避免重复检测
                    # 头像大小是50x50px，所以去重阈值应该至少是头像大小的一半（25px）
                    # 但考虑到可能的检测误差，使用30px作为阈值
                    nms_threshold = 30  # 像素距离阈值
                    
                    logger.debug(f"初始找到 {len(all_matches)} 个匹配点（阈值={threshold}）")
                    
                    # 按置信度从高到低排序
                    all_matches.sort(key=lambda m: m['confidence'], reverse=True)
                    
                    unique_matches = []
                    for match in all_matches:
                        is_duplicate = False
                        for existing in unique_matches:
                            distance = ((match['x'] - existing['x'])**2 + (match['y'] - existing['y'])**2)**0.5
                            if distance < nms_threshold:
                                is_duplicate = True
                                # 如果新匹配的置信度更高，替换旧的
                                if match['confidence'] > existing['confidence']:
                                    unique_matches.remove(existing)
                                    unique_matches.append(match)
                                    logger.debug(f"  替换重复头像: 旧({existing['x']}, {existing['y']}) -> 新({match['x']}, {match['y']}), 距离={distance:.1f}px")
                                else:
                                    logger.debug(f"  跳过重复头像: ({match['x']}, {match['y']}), 距离已有头像({existing['x']}, {existing['y']})={distance:.1f}px")
                                break
                        if not is_duplicate:
                            unique_matches.append(match)
                    
                    logger.debug(f"去重后找到 {len(unique_matches)} 个唯一头像（NMS阈值={nms_threshold}px）")
                    for i, match in enumerate(unique_matches):
                        logger.debug(f"  唯一头像{i+1}: ({match['x']}, {match['y']}), 置信度={match['confidence']:.3f}")
                    
                    # 获取search_bar位置与列表区域边界（左界=search_bar_x - 宽度*0.6，右界=search_bar_x）
                    search_bar_result = results.get("search_bar")
                    search_bar_x = None
                    search_bar_y = None
                    list_left_x = None
                    list_right_x = None
                    if search_bar_result and search_bar_result.success:
                        search_bar_x = search_bar_result.x
                        search_bar_y = search_bar_result.y
                        sb_size = get_element_size("search_bar")
                        sb_w = sb_size[0] if sb_size else 180
                        list_left_x = max(0, int((search_bar_x or 0) - sb_w * 0.6))
                        list_right_x = int(search_bar_x or 0)
                        logger.debug(f"搜索框位置: ({search_bar_x}, {search_bar_y}), 列表区域: x=[{list_left_x}, {list_right_x})")
                    else:
                        logger.debug("未找到搜索框")
                    
                    # 根据分布规则判断
                    list_matches = []
                    chat_matches = []
                    
                    if len(unique_matches) == 0:
                        # 没有找到头像
                        list_result = LocateResult(
                            success=False,
                            error_message="未找到任何头像"
                        )
                        chat_result_list = []
                    else:
                        # 与 _classify_avatar_matches 一致；判为列表的头像必须落在列表区域内
                        list_matches, chat_matches = _classify_avatar_matches(
                            unique_matches,
                            search_bar_x=search_bar_x,
                            search_bar_y=search_bar_y,
                            default_to_list=False,
                            list_right_x=list_right_x,
                            list_left_x=list_left_x,
                        )
                    
                    # 转换为LocateResult（支持包内/独立目录两种运行方式）
                    try:
                        from .models import LocateMethod
                    except ImportError:
                        from models import LocateMethod
                    
                    # profile_photo_in_list: 只取第一个（如果有多个，取置信度最高的）
                    if list_matches:
                        list_matches.sort(key=lambda m: m['confidence'], reverse=True)
                        best_list_match = list_matches[0]
                        list_result = LocateResult(
                            success=True,
                            x=best_list_match['x'],
                            y=best_list_match['y'],
                            confidence=best_list_match['confidence'],
                            method=LocateMethod.TEMPLATE_MATCH,
                            region=None,
                            error_message=None
                        )
                    else:
                        list_result = LocateResult(
                            success=False,
                            error_message="未找到列表中的头像"
                        )
                    
                    # profile_photo_in_chat: 返回所有聊天中的头像
                    logger.debug(f"分类结果: 列表头像={len(list_matches)}个, 聊天头像={len(chat_matches)}个")
                    if list_matches:
                        logger.debug(f"  列表头像位置: {[(m['x'], m['y']) for m in list_matches]}")
                    if chat_matches:
                        logger.debug(f"  聊天头像位置: {[(m['x'], m['y']) for m in chat_matches]}")
                    
                    chat_result_list = []
                    # 按x坐标分组（同一竖线范围内的头像）
                    chat_matches.sort(key=lambda m: m['x'])
                    x_groups = []
                    current_group = []
                    current_x = None
                    
                    for match in chat_matches:
                        if current_x is None or abs(match['x'] - current_x) < 10:
                            current_group.append(match)
                            current_x = match['x']
                        else:
                            if current_group:
                                x_groups.append(current_group)
                            current_group = [match]
                            current_x = match['x']
                    if current_group:
                        x_groups.append(current_group)
                    
                    logger.debug(f"聊天头像按x坐标分组: {len(x_groups)}个组")
                    for i, group in enumerate(x_groups):
                        logger.debug(f"  组{i+1}: {len(group)}个头像, x坐标={group[0]['x']}")
                    
                    # 对每个组内的头像按y坐标排序（从上到下）
                    for group in x_groups:
                        group.sort(key=lambda m: m['y'])
                    
                    # 转换为LocateResult列表
                    for group in x_groups:
                        for match in group:
                            chat_result_list.append(LocateResult(
                                success=True,
                                x=match['x'],
                                y=match['y'],
                                confidence=match['confidence'],
                                method=LocateMethod.TEMPLATE_MATCH,
                                region=None,
                                error_message=None
                            ))
                    
                    results["profile_photo_in_list"] = list_result
                    results["profile_photo_in_chat"] = chat_result_list
                    
                    if list_result.success:
                        logger.debug(f"✓ 定位到列表头像: ({list_result.x}, {list_result.y}), 置信度={list_result.confidence:.3f}")
                    else:
                        logger.debug(f"✗ 未定位到列表头像")
                    
                    logger.debug(f"✓ 最终返回 {len(chat_result_list)} 个聊天区域头像")
                    for i, result in enumerate(chat_result_list):
                        logger.debug(f"  聊天头像{i+1}: ({result.x}, {result.y}), 置信度={result.confidence:.3f}")
                    continue
            
            # 特殊处理：new_message_red_point - 先定位联系人头像，在每块检测区域内用红色像素面积占比判定
            elif element_name == "new_message_red_point":
                # 步骤1: 定位所有联系人列表中的头像
                logger.debug(f"[红点定位] 步骤1: 定位联系人列表中的所有头像...")
                try:
                    try:
                        from .contact_mapper import ContactUserMapper
                    except ImportError:
                        from contact_mapper import ContactUserMapper
                    contact_mapper = ContactUserMapper()
                    contact_avatars = locate_all_contact_avatars_in_list(
                        screenshot=screenshot,
                        threshold=threshold,
                        contact_mapper=contact_mapper,
                        enabled_contacts_only=True,
                    )
                except Exception as e:
                    logger.error(f"[红点定位] 定位联系人头像失败: {e}")
                    results[element_name] = LocateResult(
                        success=False,
                        error_message=f"定位联系人头像失败: {str(e)}"
                    )
                    continue
                
                if not contact_avatars:
                    logger.debug(f"[红点定位] 未找到任何联系人头像，无法定位红点")
                    results[element_name] = LocateResult(
                        success=False,
                        error_message="未找到任何联系人头像"
                    )
                    continue
                
                logger.debug(f"[红点定位] 找到 {len(contact_avatars)} 个联系人头像")
                
                avatar_size = get_element_size("profile_photo_in_list")
                avatar_radius = (avatar_size[0] if avatar_size else 50) // 2
                search_radius = 10
                red_area_ratio_threshold = getattr(config, "RED_POINT_AREA_RATIO_THRESHOLD", 0.7)
                h_img, w_img = screenshot.shape[:2]
                
                all_matches = []
                best_ratio = 0.0
                
                for contact_result in contact_avatars:
                    avatar_x = contact_result.locate_result.x or 0
                    avatar_y = contact_result.locate_result.y or 0
                    contact_name = contact_result.contact_name
                    top_right_x = avatar_x + avatar_radius
                    top_right_y = avatar_y - avatar_radius
                    search_left = max(0, int(top_right_x - search_radius))
                    search_right = min(w_img, int(top_right_x + search_radius))
                    search_top = max(0, int(top_right_y - search_radius))
                    search_bottom = min(h_img, int(top_right_y + search_radius))
                    if search_right <= search_left or search_bottom <= search_top:
                        continue
                    
                    ratio, cx, cy = _red_pixel_ratio_in_region(
                        screenshot, search_left, search_top, search_right, search_bottom
                    )
                    if ratio > best_ratio:
                        best_ratio = ratio
                    if ratio >= red_area_ratio_threshold:
                        all_matches.append({
                            'x': cx,
                            'y': cy,
                            'confidence': float(ratio),
                            'contact_name': contact_name,
                            'avatar_x': avatar_x,
                            'avatar_y': avatar_y,
                        })
                        logger.debug(f"[红点定位] 联系人 {contact_name} 检测区域内红色占比={ratio:.2%} >= {red_area_ratio_threshold:.0%}, 判定有红点: ({cx}, {cy})")
                    else:
                        logger.debug(f"[红点定位] 联系人 {contact_name} 红色占比={ratio:.2%} < {red_area_ratio_threshold:.0%}")
                
                if len(all_matches) == 0:
                    logger.debug(f"[红点定位] ✗ 未定位到红点（检查了 {len(contact_avatars)} 个头像），最高红色占比={best_ratio:.2%}")
                    results[element_name] = LocateResult(
                        success=False,
                        confidence=best_ratio,
                        error_message=f"未找到红点（红色占比阈值 {red_area_ratio_threshold:.0%}），最高占比: {best_ratio:.2%}"
                    )
                    continue
                
                if len(all_matches) > 1:
                    all_matches.sort(key=lambda m: m['confidence'], reverse=True)
                selected_match = all_matches[0]
                logger.debug(f"[红点定位] 找到 {len(all_matches)} 个红点，取最高占比: 联系人={selected_match['contact_name']}, 位置=({selected_match['x']}, {selected_match['y']}), 占比={selected_match['confidence']:.2%}")
                
                try:
                    from .models import LocateMethod as _LM
                except ImportError:
                    from models import LocateMethod as _LM
                rw, rh = get_element_size("new_message_red_point") or (15, 15)
                result = LocateResult(
                    success=True,
                    x=selected_match['x'],
                    y=selected_match['y'],
                    confidence=selected_match['confidence'],
                    method=_LM.TEMPLATE_MATCH,
                    region=(selected_match['x'] - rw // 2, selected_match['y'] - rh // 2, rw, rh),
                    error_message=None
                )
                logger.debug(f"[红点定位] ✓ 红点: ({result.x}, {result.y}), 红色占比={result.confidence:.2%}, 联系人={selected_match['contact_name']}")
                results[element_name] = result
                continue
            
            # 特殊处理：pin_icon - 在区域上半部分20%搜索
            elif element_name == "pin_icon":
                template_key = TEMPLATE_KEYS.get(element_name)
                if template_key:
                    template_path = config.TEMPLATE_PATHS.get(template_key)
                    if template_path and template_path.exists():
                        # 限制搜索区域为上半部分20%
                        h, w = screenshot.shape[:2]
                        search_height = int(h * 0.2)  # 上半部分20%
                        
                        # 裁剪搜索区域
                        search_image = screenshot[0:search_height, 0:w]
                        
                        # 在限制区域内搜索
                        result = match_all_templates(
                            search_image, 
                            [template_path], 
                            threshold=threshold
                        )
                        
                        # 坐标已经是相对于裁剪后图像的，不需要调整（因为是从顶部开始裁剪，Y偏移为0）
                        # match_template返回的坐标是相对于输入图像的，而我们的输入图像是从(0,0)开始的裁剪图像
                        # 所以坐标已经是正确的了
                        if result.success:
                            logger.debug(f"✓ 在区域上半部分20%定位到元素 {element_name}: ({result.x}, {result.y}), 置信度={result.confidence:.3f}")
                        else:
                            logger.debug(f"✗ 在区域上半部分20%未定位到元素 {element_name}, 最佳置信度={result.confidence:.3f}")
                    else:
                        logger.debug(f"元素 {element_name} 模板不存在，跳过")
                        results[element_name] = LocateResult(
                            success=False,
                            error_message=f"模板文件不存在: {template_key}"
                        )
                        continue
                else:
                    logger.warning(f"元素 {element_name} 没有配置模板键名")
                    results[element_name] = LocateResult(
                        success=False,
                        error_message=f"没有配置模板键名"
                    )
                    continue
            
            # 特殊处理：input_box_anchor - 使用sticker_icon和send_button的中点
            elif element_name == "input_box_anchor":
                # 先检查sticker_icon和send_button是否已定位
                sticker_result = results.get("sticker_icon")
                send_result = results.get("send_button")
                
                if sticker_result and sticker_result.success and send_result and send_result.success:
                    # 计算中点
                    input_x = (sticker_result.x + send_result.x) // 2
                    input_y = (sticker_result.y + send_result.y) // 2
                    
                    result = LocateResult(
                        success=True,
                        x=input_x,
                        y=input_y,
                        confidence=min(sticker_result.confidence, send_result.confidence),
                        method=sticker_result.method,
                        region=None,  # 输入框大小不定
                        error_message=None
                    )
                    logger.debug(f"✓ 通过相对位置定位到元素 {element_name}: ({input_x}, {input_y})")
                else:
                    logger.warning(f"✗ 无法定位元素 {element_name}，需要先定位sticker_icon和send_button")
                    results[element_name] = LocateResult(
                        success=False,
                        error_message=f"需要先定位sticker_icon和send_button"
                    )
                    continue
            
            else:
                # 普通元素定位
                template_key = TEMPLATE_KEYS.get(element_name)
                if template_key:
                    template_path = config.TEMPLATE_PATHS.get(template_key)
                    if template_path and template_path.exists():
                        result = match_all_templates(screenshot, [template_path], threshold=threshold)
                    else:
                        logger.debug(f"元素 {element_name} 模板不存在，跳过")
                        results[element_name] = LocateResult(
                            success=False,
                            error_message=f"模板文件不存在: {template_key}"
                        )
                        continue
                else:
                    logger.warning(f"元素 {element_name} 没有配置模板键名")
                    results[element_name] = LocateResult(
                        success=False,
                        error_message=f"没有配置模板键名"
                    )
                    continue
            
            # 普通元素定位结果赋值
            # 注意：profile_photo_in_list 和 profile_photo_in_chat 已经在上面处理过了，不会到这里
            results[element_name] = result
            
            if result.success:
                logger.debug(f"✓ 定位到元素 {element_name}: ({result.x}, {result.y}), 置信度={result.confidence:.3f}")
            else:
                logger.warning(f"✗ 未定位到元素 {element_name}, 最佳置信度={result.confidence:.3f}")
        
        except Exception as e:
            logger.error(f"定位元素 {element_name} 时出错: {e}")
            results[element_name] = LocateResult(
                success=False,
                error_message=str(e)
            )
    
    return results


def _nms_avatar_matches(
    matches: List[Dict],
    nms_threshold: int = 30
) -> List[Dict]:
    """
    对同一联系人的头像匹配结果做 NMS 去重（仅在同一联系人内部去重）。
    每个 match 需包含 'x', 'y', 'confidence'，可选 'contact_name', 'contact_id'。
    """
    if not matches:
        return []
    sorted_matches = sorted(matches, key=lambda m: m.get("confidence", 0.0), reverse=True)
    unique: List[Dict] = []
    for match in sorted_matches:
        is_dup = False
        for existing in unique:
            dx = match["x"] - existing["x"]
            dy = match["y"] - existing["y"]
            if (dx * dx + dy * dy) ** 0.5 < nms_threshold:
                is_dup = True
                break
        if not is_dup:
            unique.append(match)
    return unique


def _classify_avatar_matches(
    matches: List[Dict],
    search_bar_x: Optional[float],
    search_bar_y: Optional[float],
    default_to_list: bool,
    list_right_x: Optional[float] = None,
    list_left_x: Optional[float] = None,
) -> Tuple[List[Dict], List[Dict]]:
    """
    将头像匹配按位置分为「列表区域」与「聊天区域」。
    规则：先按 X 分组；同 X 上不同 y = 聊天列；两个及以上不同 X 时最左列=列表、其余=聊天。
    列表区域确定后：判为「列表中」的头像必须落在 [list_left_x, list_right_x) 且 y > search_bar_y，否则判为不符合、不计入列表。
    list_right_x: 列表区域右界；不传则用 search_bar_x。
    list_left_x: 列表区域左界；与 list_right_x 同时传入时，会对 list_matches 做区域过滤。
    """
    list_matches: List[Dict] = []
    chat_matches: List[Dict] = []
    if not matches:
        return list_matches, chat_matches
    list_right = list_right_x if list_right_x is not None else search_bar_x
    list_left = list_left_x
    # 只有一个：看是否在列表区域（list_left <= x < list_right 且 y > search_bar_y；无 list_left 时用 x < list_right）
    if len(matches) == 1:
        m = matches[0]
        # 若列表区域边界已明确：区域仅用于“二次保证”（减法），不允许因“不在列表区”而推断为聊天区
        if list_left is not None and list_right is not None and search_bar_y is not None:
            in_list = m["x"] < list_right and m["y"] > search_bar_y
            in_list = in_list and m["x"] >= list_left
            if in_list:
                list_matches.append(m)
            # 不在列表区：不回退为 chat，直接清除（不往下传递）
            return list_matches, []
        if list_right is not None and search_bar_y is not None:
            in_list = m["x"] < list_right and m["y"] > search_bar_y
            if in_list:
                list_matches.append(m)
            else:
                chat_matches.append(m)
        else:
            if default_to_list:
                list_matches.append(m)
            else:
                chat_matches.append(m)
        return list_matches, chat_matches
    # 两个及以上：先按 X 分组（10px 容差）
    x_threshold = 10
    by_x: Dict[float, List[Dict]] = {}
    for m in matches:
        x = m["x"]
        key = round(x / x_threshold) * x_threshold
        if key not in by_x:
            by_x[key] = []
        by_x[key].append(m)
    x_keys_sorted = sorted(by_x.keys())
    n_x = len(x_keys_sorted)
    if n_x >= 2:
        # 最左列=列表，其余列=聊天
        left_x_key = x_keys_sorted[0]
        for m in matches:
            key = round(m["x"] / x_threshold) * x_threshold
            if key == left_x_key:
                list_matches.append(m)
            else:
                chat_matches.append(m)
    else:
        # n_x == 1：同 X 上有不同 y，说明是聊天中的
        chat_matches.extend(matches)
    # 列表区域已确定时：判为「列表中」的必须落在 [list_left_x, list_right_x) 且 y > search_bar_y，否则判不符合、不计入列表
    if list_left is not None and list_right is not None and search_bar_y is not None and list_matches:
        in_region: List[Dict] = []
        for m in list_matches:
            if m["x"] >= list_left and m["x"] < list_right and m["y"] > search_bar_y:
                in_region.append(m)
            # 不在列表区：不回退为 chat，直接丢弃（区域只能做减法）
        list_matches = in_region
    return list_matches, chat_matches


def locate_all_contact_avatars_in_list(
    screenshot: Optional[np.ndarray] = None,
    threshold: float = 0.7,
    contact_mapper: Optional[ContactUserMapper] = None,
    enabled_contacts_only: bool = True,
    exclude_contacts: Optional[List[str]] = None,
) -> List[ContactLocateResult]:
    """
    一次性定位联系人列表中所有配置联系人的头像位置
    
    功能：
    - 获取所有配置的联系人（或仅启用的联系人）
    - 使用每个联系人的头像模板进行匹配
    - 将所有匹配结果标记对应的联系人
    - 只返回列表区域的头像（排除聊天区域）
    
    Args:
        screenshot: 窗口截图（BGR格式），如果为None则自动截取
        threshold: 模板匹配阈值（0.0-1.0）
        contact_mapper: 联系人映射器实例，如果为None则创建新实例
        enabled_contacts_only: 是否只定位启用的联系人，如果为False则定位所有配置的联系人
    
    Returns:
        联系人头像定位结果列表 List[ContactLocateResult]，每个结果包含：
        - locate_result: LocateResult（定位结果）
        - contact_name: 联系人名称
        - contact_id: 联系人ID（可选）
    """
    config = WeChatAutomationConfig
    
    # 如果没有提供截图，自动截取
    if screenshot is None:
        try:
            hwnd = get_wechat_hwnd()
            screenshot = capture_window(hwnd)
        except Exception as e:
            logger.error(f"获取窗口截图失败: {e}")
            return []
    
    # 如果没有提供联系人映射器，创建新实例
    if contact_mapper is None:
        contact_mapper = ContactUserMapper()
    
    # 获取联系人列表
    if enabled_contacts_only:
        contacts = contact_mapper.get_enabled_contacts()
        logger.debug(f"定位启用的联系人头像，共 {len(contacts)} 个联系人")
    else:
        contacts = contact_mapper.get_all_contacts()
        logger.debug(f"定位所有配置的联系人头像，共 {len(contacts)} 个联系人")

    # 按需排除指定联系人（例如“我”）
    if exclude_contacts:
        exclude_set = set(c.strip() for c in exclude_contacts if c and c.strip())
        if exclude_set:
            before = len(contacts)
            contacts = [c for c in contacts if c not in exclude_set]
            logger.debug(
                "根据 exclude_contacts 过滤联系人: 原有 %d 个, 排除 %s 后剩余 %d 个",
                before,
                list(exclude_set),
                len(contacts),
            )
    
    if not contacts:
        logger.warning("没有找到配置的联系人")
        return []
    
    # 转换为灰度图
    if len(screenshot.shape) == 3:
        screenshot_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    else:
        screenshot_gray = screenshot
    
    # 先定位搜索框位置（用于判断头像是否在列表中）
    search_bar_result = None
    try:
        search_bar_template_paths = []
        base_path = config.TEMPLATE_PATHS.get("search_bar")
        if base_path and base_path.exists():
            search_bar_template_paths.append(base_path)
        ing_path = config.TEMPLATE_PATHS.get("search_bar_ing")
        if ing_path and ing_path.exists():
            search_bar_template_paths.append(ing_path)
        
        if search_bar_template_paths:
            search_bar_result = match_all_templates(screenshot, search_bar_template_paths, threshold=threshold)
            if search_bar_result.success:
                logger.debug(f"搜索框位置: ({search_bar_result.x}, {search_bar_result.y})")
    except Exception as e:
        logger.debug(f"定位搜索框失败: {e}")
    
    search_bar_x = search_bar_result.x if search_bar_result and search_bar_result.success else None
    search_bar_y = search_bar_result.y if search_bar_result and search_bar_result.success else None
    # 列表区域边界：左界 = search_bar_x - 宽度*0.6，右界 = search_bar_x；判为列表的头像必须落在此区域内
    list_left_x = None
    list_right_x = None
    if search_bar_x is not None:
        sb_size = get_element_size("search_bar")
        sb_w = sb_size[0] if sb_size else 180
        list_left_x = max(0, int(search_bar_x - sb_w * 0.6))
        list_right_x = int(search_bar_x)
    
    # 存储所有匹配结果：{contact_name: List[匹配结果]}
    all_contact_matches: Dict[str, List[Dict]] = {}
    
    # 为每个联系人匹配头像
    for contact_name in contacts:
        contact_id = contact_mapper.get_contact_id(contact_name)
        
        # 获取联系人头像模板路径
        template_path = config.get_contact_profile_photo_path(
            contact_name=contact_name,
            contact_id=contact_id or ""
        )
        
        if not template_path or not template_path.exists():
            logger.debug(f"联系人 '{contact_name}' 的头像模板不存在: {template_path}，跳过")
            continue
        
        # 加载模板
        template = cv2.imread(str(template_path))
        if template is None:
            logger.warning(f"无法加载联系人 '{contact_name}' 的头像模板: {template_path}")
            continue
        
        # 转换为灰度图
        if len(template.shape) == 3:
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        else:
            template_gray = template
        
        # 检查模板尺寸是否小于等于截图尺寸（OpenCV要求）
        template_h, template_w = template_gray.shape[:2]
        screenshot_h, screenshot_w = screenshot_gray.shape[:2]
        
        if template_h > screenshot_h or template_w > screenshot_w:
            logger.warning(
                f"联系人 '{contact_name}' 的头像模板尺寸 ({template_w}x{template_h}) "
                f"大于截图尺寸 ({screenshot_w}x{screenshot_h})，跳过此模板"
            )
            continue
        
        # 模板匹配
        match_result = cv2.matchTemplate(screenshot_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        
        # 找到所有超过阈值的位置
        locations = np.where(match_result >= threshold)
        
        # 收集所有匹配点
        matches = []
        for pt in zip(*locations[::-1]):  # Switch x and y coordinates
            confidence = float(match_result[pt[1], pt[0]])
            # 计算头像中心点
            avatar_center_x = pt[0] + template_gray.shape[1] // 2
            avatar_center_y = pt[1] + template_gray.shape[0] // 2
            
            matches.append({
                'x': avatar_center_x,
                'y': avatar_center_y,
                'confidence': confidence,
                'contact_name': contact_name,
                'contact_id': contact_id
            })
        
        if matches:
            logger.debug(f"联系人 '{contact_name}' 找到 {len(matches)} 个匹配点")
            all_contact_matches[contact_name] = matches
        else:
            logger.debug(f"联系人 '{contact_name}' 未找到匹配的头像")
    
    if not all_contact_matches:
        logger.warning("所有联系人都未找到匹配的头像")
        return []
    
    # 按联系人单独：NMS 去重 + 列表/聊天分类（判为列表的必须落在列表区域内），再汇总列表区域结果
    try:
        from .models import LocateMethod
    except ImportError:
        from models import LocateMethod
    
    nms_threshold = 30
    result_list: List[ContactLocateResult] = []
    for contact_name, matches in all_contact_matches.items():
        unique_c = _nms_avatar_matches(matches, nms_threshold=nms_threshold)
        list_c, chat_c = _classify_avatar_matches(
            unique_c,
            search_bar_x=search_bar_x,
            search_bar_y=search_bar_y,
            default_to_list=True,
            list_right_x=list_right_x,
            list_left_x=list_left_x,
        )
        logger.debug(
            f"联系人 '{contact_name}' 单独统计: 列表头像={len(list_c)} 个, 聊天头像={len(chat_c)} 个"
        )
        for match in list_c:
            locate_result = LocateResult(
                success=True,
                x=match["x"],
                y=match["y"],
                confidence=match["confidence"],
                method=LocateMethod.TEMPLATE_MATCH,
                region=None,
                error_message=None
            )
            result_list.append(ContactLocateResult(
                locate_result=locate_result,
                contact_name=match["contact_name"],
                contact_id=match.get("contact_id")
            ))
            logger.debug(
                f"✓ 定位到联系人 '{match['contact_name']}' 的头像(列表): ({match['x']}, {match['y']}), 置信度={match['confidence']:.3f}"
            )
    
    logger.debug(f"成功定位 {len(result_list)} 个联系人的头像（列表区域，按联系人单独计算）")
    return result_list


def locate_all_contact_avatars_in_chat(
    screenshot: Optional[np.ndarray] = None,
    threshold: float = 0.7,
    contact_mapper: Optional[ContactUserMapper] = None,
    enabled_contacts_only: bool = True,
    exclude_contacts: Optional[List[str]] = None,
) -> List[ContactLocateResult]:
    """
    一次性定位聊天区域中所有配置联系人的头像位置
    
    功能：
    - 获取所有配置的联系人（或仅启用的联系人）
    - 使用每个联系人的头像模板进行匹配
    - 将所有匹配结果标记对应的联系人
    - 只返回聊天区域的头像（排除列表区域）
    
    适用场景：
    - 单聊：定位当前聊天对象的头像
    - 群聊：定位所有群成员的头像（需要预先配置群成员的头像模板）
    
    Args:
        screenshot: 窗口截图（BGR格式），如果为None则自动截取
        threshold: 模板匹配阈值（0.0-1.0）
        contact_mapper: 联系人映射器实例，如果为None则创建新实例
        enabled_contacts_only: 是否只定位启用的联系人，如果为False则定位所有配置的联系人
    
    Returns:
        联系人头像定位结果列表 List[ContactLocateResult]，每个结果包含：
        - locate_result: LocateResult（定位结果）
        - contact_name: 联系人名称
        - contact_id: 联系人ID（可选）
    """
    config = WeChatAutomationConfig
    
    # 如果没有提供截图，自动截取
    if screenshot is None:
        try:
            hwnd = get_wechat_hwnd()
            screenshot = capture_window(hwnd)
        except Exception as e:
            logger.error(f"获取窗口截图失败: {e}")
            return []
    
    # 如果没有提供联系人映射器，创建新实例
    if contact_mapper is None:
        contact_mapper = ContactUserMapper()
    
    # 获取联系人列表
    if enabled_contacts_only:
        contacts = contact_mapper.get_enabled_contacts()
        logger.debug(f"定位聊天区域中启用的联系人头像，共 {len(contacts)} 个联系人")
    else:
        contacts = contact_mapper.get_all_contacts()
        logger.debug(f"定位聊天区域中所有配置的联系人头像，共 {len(contacts)} 个联系人")

    # 按需排除指定联系人（例如“我”）
    if exclude_contacts:
        exclude_set = set(c.strip() for c in exclude_contacts if c and c.strip())
        if exclude_set:
            before = len(contacts)
            contacts = [c for c in contacts if c not in exclude_set]
            logger.debug(
                "根据 exclude_contacts 过滤联系人(聊天区域): 原有 %d 个, 排除 %s 后剩余 %d 个",
                before,
                list(exclude_set),
                len(contacts),
            )
    
    if not contacts:
        logger.warning("没有找到配置的联系人")
        return []
    
    # 转换为灰度图
    if len(screenshot.shape) == 3:
        screenshot_gray = cv2.cvtColor(screenshot, cv2.COLOR_BGR2GRAY)
    else:
        screenshot_gray = screenshot
    
    # 先定位搜索框位置（用于判断头像是否在聊天区域）
    search_bar_result = None
    try:
        search_bar_template_paths = []
        base_path = config.TEMPLATE_PATHS.get("search_bar")
        if base_path and base_path.exists():
            search_bar_template_paths.append(base_path)
        ing_path = config.TEMPLATE_PATHS.get("search_bar_ing")
        if ing_path and ing_path.exists():
            search_bar_template_paths.append(ing_path)
        
        if search_bar_template_paths:
            search_bar_result = match_all_templates(screenshot, search_bar_template_paths, threshold=threshold)
            if search_bar_result.success:
                logger.debug(f"搜索框位置: ({search_bar_result.x}, {search_bar_result.y})")
    except Exception as e:
        logger.debug(f"定位搜索框失败: {e}")
    
    search_bar_x = search_bar_result.x if search_bar_result and search_bar_result.success else None
    search_bar_y = search_bar_result.y if search_bar_result and search_bar_result.success else None
    # 列表区域边界：判为列表的头像必须落在此区域内，否则不计入列表
    list_left_x = None
    list_right_x = None
    if search_bar_x is not None:
        sb_size = get_element_size("search_bar")
        sb_w = sb_size[0] if sb_size else 180
        list_left_x = max(0, int(search_bar_x - sb_w * 0.6))
        list_right_x = int(search_bar_x)
    
    # 存储所有匹配结果：{contact_name: List[匹配结果]}
    all_contact_matches: Dict[str, List[Dict]] = {}
    
    # 为每个联系人匹配头像
    for contact_name in contacts:
        contact_id = contact_mapper.get_contact_id(contact_name)
        
        # 获取联系人头像模板路径
        template_path = config.get_contact_profile_photo_path(
            contact_name=contact_name,
            contact_id=contact_id or ""
        )
        
        if not template_path or not template_path.exists():
            logger.debug(f"联系人 '{contact_name}' 的头像模板不存在: {template_path}，跳过")
            continue
        
        # 加载模板
        template = cv2.imread(str(template_path))
        if template is None:
            logger.warning(f"无法加载联系人 '{contact_name}' 的头像模板: {template_path}")
            continue
        
        # 转换为灰度图
        if len(template.shape) == 3:
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        else:
            template_gray = template
        
        # 检查模板尺寸是否小于等于截图尺寸（OpenCV要求）
        template_h, template_w = template_gray.shape[:2]
        screenshot_h, screenshot_w = screenshot_gray.shape[:2]
        
        if template_h > screenshot_h or template_w > screenshot_w:
            logger.warning(
                f"联系人 '{contact_name}' 的头像模板尺寸 ({template_w}x{template_h}) "
                f"大于截图尺寸 ({screenshot_w}x{screenshot_h})，跳过此模板"
            )
            continue
        
        # 模板匹配
        match_result = cv2.matchTemplate(screenshot_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        
        # 找到所有超过阈值的位置
        locations = np.where(match_result >= threshold)
        
        # 收集所有匹配点
        matches = []
        for pt in zip(*locations[::-1]):  # Switch x and y coordinates
            confidence = float(match_result[pt[1], pt[0]])
            # 计算头像中心点
            avatar_center_x = pt[0] + template_gray.shape[1] // 2
            avatar_center_y = pt[1] + template_gray.shape[0] // 2
            
            matches.append({
                'x': avatar_center_x,
                'y': avatar_center_y,
                'confidence': confidence,
                'contact_name': contact_name,
                'contact_id': contact_id
            })
        
        if matches:
            logger.debug(f"联系人 '{contact_name}' 找到 {len(matches)} 个匹配点")
            all_contact_matches[contact_name] = matches
        else:
            logger.debug(f"联系人 '{contact_name}' 未找到匹配的头像")
    
    if not all_contact_matches:
        logger.warning("所有联系人都未找到匹配的头像")
        return []
    
    # 按联系人单独：NMS 去重 + 列表/聊天分类，再汇总聊天区域结果
    try:
        from .models import LocateMethod
    except ImportError:
        from models import LocateMethod
    
    nms_threshold = 30
    result_list: List[ContactLocateResult] = []
    for contact_name, matches in all_contact_matches.items():
        unique_c = _nms_avatar_matches(matches, nms_threshold=nms_threshold)
        list_c, chat_c = _classify_avatar_matches(
            unique_c,
            search_bar_x=search_bar_x,
            search_bar_y=search_bar_y,
            default_to_list=False,
            list_right_x=list_right_x,
            list_left_x=list_left_x,
        )
        logger.debug(
            f"联系人 '{contact_name}' 单独统计: 列表头像={len(list_c)} 个, 聊天头像={len(chat_c)} 个"
        )
        # 聊天区域按 y 从大到小（从下到上，新到旧）
        chat_c.sort(key=lambda m: m["y"], reverse=True)
        for match in chat_c:
            locate_result = LocateResult(
                success=True,
                x=match["x"],
                y=match["y"],
                confidence=match["confidence"],
                method=LocateMethod.TEMPLATE_MATCH,
                region=None,
                error_message=None
            )
            result_list.append(ContactLocateResult(
                locate_result=locate_result,
                contact_name=match["contact_name"],
                contact_id=match.get("contact_id")
            ))
            logger.debug(
                f"✓ 定位到联系人 '{match['contact_name']}' 的头像(聊天): ({match['x']}, {match['y']}), 置信度={match['confidence']:.3f}"
            )
    
    logger.debug(f"成功定位 {len(result_list)} 个联系人的头像（聊天区域，按联系人单独计算）")
    return result_list


def save_element_positions(
    positions: Dict[str, Union[LocateResult, List[LocateResult]]],
    filepath: Optional[Path] = None
) -> Path:
    """
    保存元素位置到JSON文件
    
    Args:
        positions: 元素位置字典（支持单个LocateResult或LocateResult列表）
        filepath: 保存路径，如果为None则使用配置中的路径
    
    Returns:
        保存的文件路径
    """
    if filepath is None:
        filepath = WeChatAutomationConfig.ELEMENT_POSITIONS_FILE
    
    # 确保目录存在（如果路径包含目录）
    if filepath.parent != filepath:
        filepath.parent.mkdir(parents=True, exist_ok=True)
    
    # 转换为可序列化的格式
    data = {}
    for element_name, result_or_list in positions.items():
        # 检查是否为列表（数组）
        if isinstance(result_or_list, list):
            # 数组类型（如profile_photo_in_chat）
            result_list = []
            for result in result_or_list:
                if result.success:
                    _x, _y = result.x or 0, result.y or 0
                    bounds = get_element_bounds(_x, _y, element_name, locate_result=result)
                    size = get_element_size(element_name)
                    if size is None:
                        if result.region:
                            _, _, width, height = result.region
                            size = (width, height)
                        else:
                            size = bounds[2:]
                    result_list.append({
                        "success": True,
                        "x": int(_x),
                        "y": int(_y),
                        "confidence": float(result.confidence),
                        "bounds": tuple(int(b) for b in bounds),
                        "size": tuple(int(s) for s in size) if isinstance(size, tuple) else size
                    })
            data[element_name] = result_list
        else:
            # 单个结果
            result = result_or_list
            if result.success:
                _x, _y = result.x or 0, result.y or 0
                # 计算边界框（传递定位结果以获取大小）
                bounds = get_element_bounds(_x, _y, element_name, locate_result=result)
                size = get_element_size(element_name)
                # 如果大小不定，使用边界框的大小或定位结果的region
                if size is None:
                    if result.region:
                        _, _, width, height = result.region
                        size = (width, height)
                    else:
                        size = bounds[2:]  # 使用边界框的大小
                data[element_name] = {
                    "success": True,
                    "x": int(_x),
                    "y": int(_y),
                    "confidence": float(result.confidence),
                    "bounds": tuple(int(b) for b in bounds),
                    "size": tuple(int(s) for s in size) if isinstance(size, tuple) else size
                }
            else:
                data[element_name] = {
                    "success": False,
                    "error_message": result.error_message
                }
    
    # 保存到文件
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    logger.info(f"元素位置已保存到: {filepath}")
    return filepath


def load_element_positions(filepath: Optional[Path] = None) -> Dict[str, Dict]:
    """
    从JSON文件加载元素位置
    
    Args:
        filepath: 文件路径，如果为None则使用配置中的路径
    
    Returns:
        元素位置字典
    """
    if filepath is None:
        filepath = WeChatAutomationConfig.ELEMENT_POSITIONS_FILE
    
    if not filepath.exists():
        logger.warning(f"元素位置文件不存在: {filepath}")
        return {}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        logger.info(f"元素位置已从文件加载: {filepath}")
        return data
    except Exception as e:
        logger.error(f"加载元素位置文件失败: {e}")
        return {}


def annotate_all_elements(
    screenshot: np.ndarray,
    positions: Dict[str, Union[LocateResult, List[LocateResult]]],
    save_path: Optional[Path] = None,
    all_contact_avatars: Optional[List[ContactLocateResult]] = None,
    all_contact_avatars_in_chat: Optional[List[ContactLocateResult]] = None
) -> np.ndarray:
    """
    在截图上标注所有元素位置
    
    Args:
        screenshot: 窗口截图（BGR格式）
        positions: 元素位置字典（支持单个LocateResult或LocateResult列表）
        save_path: 保存路径，如果为None则不保存
        all_contact_avatars: 所有联系人的头像定位结果列表（列表区域，可选），用于在图片上标注联系人信息
        all_contact_avatars_in_chat: 所有联系人的头像定位结果列表（聊天区域，可选），用于在图片上标注联系人信息
    
    Returns:
        标注后的图像
    """
    # 调试：检查输入数据的类型
    logger.info(f"开始标注，positions 包含 {len(positions)} 个元素")
    for name, value in positions.items():
        if name == "profile_photo_in_chat":
            logger.info(f"  {name}: type={type(value)}, is_list={isinstance(value, list)}")
            if isinstance(value, list):
                logger.info(f"    数组长度: {len(value)}")
                for i, item in enumerate(value):
                    logger.info(f"      [{i}]: type={type(item)}, success={getattr(item, 'success', None)}, x={getattr(item, 'x', None)}, y={getattr(item, 'y', None)}")
            else:
                logger.warning(f"    ⚠️ profile_photo_in_chat 不是列表！type={type(value)}")
    
    annotated = screenshot.copy()
    h_img, w_img = annotated.shape[:2]
    # 若有 search_bar，绘制列表区域（搜索框左下方）便于检查列表/聊天分界
    list_roi = get_list_area_roi(positions, image_height=h_img)
    if list_roi is not None:
        lx, ly, lw, lh = list_roi
        cv2.rectangle(annotated, (lx, ly), (lx + lw, ly + lh), (0, 255, 255), 2)
        annotated = put_chinese_text(
            annotated,
            "列表区域(搜索框左下方)",
            (lx + 5, ly + 22),
            font_size=12,
            color=(0, 255, 255)
        )
    
    # 绘制红点检查范围：在每个联系人头像右上角画出实际参与红点匹配的矩形区域
    try:
        avatars_for_red_region = all_contact_avatars
        if avatars_for_red_region is None:
            avatars_for_red_region = locate_all_contact_avatars_in_list(screenshot=screenshot)
        avatar_size = get_element_size("profile_photo_in_list")
        avatar_radius = (avatar_size[0] if avatar_size else 50) // 2
        search_radius = 10
        red_region_color = (255, 192, 203)  # 与 new_message_red_point 同色
        first_label = True
        for contact_result in avatars_for_red_region:
            avatar_x = contact_result.locate_result.x or 0
            avatar_y = contact_result.locate_result.y or 0
            top_right_x = avatar_x + avatar_radius
            top_right_y = avatar_y - avatar_radius
            search_left = max(0, int(top_right_x - search_radius))
            search_right = min(w_img, int(top_right_x + search_radius))
            search_top = max(0, int(top_right_y - search_radius))
            search_bottom = min(h_img, int(top_right_y + search_radius))
            if search_right <= search_left or search_bottom <= search_top:
                continue
            cv2.rectangle(annotated, (search_left, search_top), (search_right, search_bottom), red_region_color, 2)
            if first_label:
                annotated = put_chinese_text(
                    annotated,
                    "红点检查范围",
                    (search_left, max(0, search_top - 4)),
                    font_size=10,
                    color=red_region_color
                )
                first_label = False
    except Exception as e:
        logger.debug("绘制红点检查范围时跳过: %s", e)
    
    # 定义颜色映射（按顺序，与ELEMENT_ORDER对应）
    colors = [
        (0, 255, 255),   # 黄色 - chat_message_icon
        (255, 165, 0),   # 橙色 - three_point_icon
        (255, 20, 147),  # 深粉色 - pin_icon
        (0, 255, 0),     # 绿色 - search_bar
        (0, 0, 255),     # 红色 - profile_photo_in_list
        (255, 192, 203), # 粉色 - new_message_red_point
        (255, 0, 0),     # 蓝色 - profile_photo_in_chat
        (255, 0, 255),   # 紫色 - sticker_icon
        (255, 255, 0),   # 青色 - save_icon
        (128, 0, 128),   # 紫色 - file_icon
        (255, 192, 203), # 粉色 - screencap_icon
        (200, 200, 200), # 浅灰 - tape_icon
        (0, 128, 128),   # 青色 - voice_call_icon
        (128, 255, 0),   # 黄绿色 - video_call_icon
        (0, 128, 255),   # 橙色 - send_button
        (255, 255, 255), # 白色 - input_box_anchor
    ]
    
    # 标注每个元素
    for idx, element_name in enumerate(ELEMENT_ORDER):
        result_or_list = positions.get(element_name)
        if result_or_list is None:
            continue
        
        color = colors[idx % len(colors)] if idx < len(colors) else (128, 128, 128)
        
        # 调试：检查数据类型
        logger.debug(f"处理元素 {element_name}: type={type(result_or_list)}, is_list={isinstance(result_or_list, list)}")
        if isinstance(result_or_list, list):
            logger.debug(f"  数组长度: {len(result_or_list)}")
            for i, item in enumerate(result_or_list):
                logger.debug(f"    [{i}]: type={type(item)}, success={getattr(item, 'success', None)}, x={getattr(item, 'x', None)}, y={getattr(item, 'y', None)}")
        
        # 检查是否为数组类型
        # 重要：profile_photo_in_chat 必须是 List[LocateResult]
        # 如果传入的是 Dict 或其他类型，说明数据被降维了，需要报错
        if isinstance(result_or_list, list):
            # 数组类型（如profile_photo_in_chat）
            if not result_or_list:
                # 空数组，标注未找到
                logger.debug(f"元素 {element_name} 是空数组")
                h, w = annotated.shape[:2]
                center_x, center_y = w // 2, h // 2
                label = f"{element_name} (未找到，空数组)"
                annotated = put_chinese_text(
                    annotated,
                    label,
                    (center_x + 25, center_y),
                    font_size=14,
                    color=color
                )
            else:
                # 验证列表中的元素类型
                if not all(isinstance(item, LocateResult) for item in result_or_list):
                    logger.error(f"⚠️ 数组元素 {element_name} 包含非 LocateResult 类型！")
                    logger.error(f"  类型: {[type(item).__name__ for item in result_or_list]}")
                    # 尝试转换（如果是字典）
                    converted_list = []
                    for item in result_or_list:
                        if isinstance(item, dict):
                            logger.warning(f"  检测到字典类型，尝试转换...")
                            # 这里不应该发生，但如果发生了，至少记录错误
                            logger.error(f"  ❌ 数据被降维了！{element_name} 应该是 List[LocateResult]，但收到了字典列表")
                        converted_list.append(item)
                    result_or_list = converted_list
                
                logger.info(f"标注数组元素 {element_name}，共 {len(result_or_list)} 个")
                success_count = 0
                for i, result in enumerate(result_or_list):
                    # 严格类型检查
                    if not isinstance(result, LocateResult):
                        logger.error(f"  ❌ 数组元素 {element_name}[{i}] 不是 LocateResult 类型！type={type(result)}")
                        logger.error(f"     这表示数据被降维了！应该是 List[LocateResult]，但收到了 {type(result)}")
                        continue
                    
                    logger.info(f"  处理数组元素 {element_name}[{i}]: success={result.success}")
                    if hasattr(result, 'x') and hasattr(result, 'y'):
                        logger.info(f"    坐标: x={result.x}, y={result.y}")
                    if result.success:
                        success_count += 1
                        x, y = int(result.x or 0), int(result.y or 0)
                        
                        # 绘制中心点（圆圈）
                        cv2.circle(annotated, (x, y), 10, color, 2)
                        
                        # 绘制十字线
                        cv2.line(annotated, (x - 20, y), (x + 20, y), color, 2)
                        cv2.line(annotated, (x, y - 20), (x, y + 20), color, 2)
                        
                        # 计算边界框
                        size = get_element_size(element_name)
                        if size is None:
                            if result.region:
                                _, _, width, height = result.region
                            else:
                                width, height = 100, 50
                        else:
                            width, height = size
                        left = x - width // 2
                        top = y - height // 2
                        
                        # 绘制边界框
                        cv2.rectangle(annotated, (left, top), (left + width, top + height), color, 2)
                        
                        # 添加标签（与其他元素保持一致）
                        label = f"{element_name}[{i}] ({x},{y})"
                        annotated = put_chinese_text(
                            annotated,
                            label,
                            (x + 25, y - 10),
                            font_size=14,
                            color=color
                        )
                        
                        # 添加置信度
                        conf_label = f"conf={result.confidence:.2f}"
                        annotated = put_chinese_text(
                            annotated,
                            conf_label,
                            (x + 25, y + 5),
                            font_size=12,
                            color=color
                        )
                    else:
                        logger.warning(f"数组元素 {element_name}[{i}] 定位失败: {result.error_message}")
                
                logger.info(f"  成功标注 {success_count}/{len(result_or_list)} 个数组元素")
            continue
        
        # 单个结果类型
        result = result_or_list
        if result.success:
            x, y = int(result.x or 0), int(result.y or 0)
            
            # 特殊处理：input_box_anchor - 显示连接线
            if element_name == "input_box_anchor":
                # 获取sticker_icon和send_button的位置
                sticker_result = _get_single_result(positions, "sticker_icon")
                send_result = _get_single_result(positions, "send_button")
                
                if sticker_result and sticker_result.success and send_result and send_result.success:
                    sx, sy = int(sticker_result.x or 0), int(sticker_result.y or 0)
                    ex, ey = int(send_result.x or 0), int(send_result.y or 0)
                    # 绘制从sticker_icon到input_box_anchor的线
                    cv2.line(annotated, (sx, sy), (x, y), color, 2, cv2.LINE_AA)
                    # 绘制从send_button到input_box_anchor的线
                    cv2.line(annotated, (ex, ey), (x, y), color, 2, cv2.LINE_AA)
                    # 标注中点说明
                    mid_x = (sx + ex) // 2
                    mid_y = (sy + ey) // 2
                    annotated = put_chinese_text(
                        annotated,
                        "中点",
                        (mid_x - 20, mid_y - 25),
                        font_size=12,
                        color=color
                    )
            
            # 特殊处理：new_message_red_point - 显示与头像的关系
            if element_name == "new_message_red_point":
                # 获取profile_photo_in_list的位置
                profile_photo_result = _get_single_result(positions, "profile_photo_in_list")
                if profile_photo_result and profile_photo_result.success:
                    # 绘制从头像右上角到红点的虚线（表示关联关系）
                    avatar_x = int(profile_photo_result.x or 0)
                    avatar_y = int(profile_photo_result.y or 0)
                    avatar_size = get_element_size("profile_photo_in_list")
                    avatar_width, avatar_height = avatar_size
                    # 头像右上角坐标
                    avatar_right = avatar_x + avatar_width // 2
                    avatar_top = avatar_y - avatar_height // 2
                    
                    # 绘制虚线（用多个小线段模拟）
                    # 从头像右上角到红点
                    dx = x - avatar_right
                    dy = y - avatar_top
                    num_segments = 10
                    for i in range(num_segments):
                        if i % 2 == 0:  # 只绘制偶数段，形成虚线效果
                            start_ratio = i / num_segments
                            end_ratio = (i + 1) / num_segments
                            start_x = int(avatar_right + dx * start_ratio)
                            start_y = int(avatar_top + dy * start_ratio)
                            end_x = int(avatar_right + dx * end_ratio)
                            end_y = int(avatar_top + dy * end_ratio)
                            cv2.line(annotated, (start_x, start_y), (end_x, end_y), color, 1, cv2.LINE_AA)
                    
                    # 在头像右上角标注
                    annotated = put_chinese_text(
                        annotated,
                        "头像右上角",
                        (avatar_right - 30, avatar_top - 15),
                        font_size=10,
                        color=(0, 0, 255)  # 红色，与头像颜色一致
                    )
            
            # 绘制中心点（圆圈）
            cv2.circle(annotated, (x, y), 10, color, 2)
            
            # 绘制十字线
            cv2.line(annotated, (x - 20, y), (x + 20, y), color, 2)
            cv2.line(annotated, (x, y - 20), (x, y + 20), color, 2)
            
            # 计算边界框
            size = get_element_size(element_name)
            if size is None:
                # 大小不定，尝试从定位结果获取
                if result.region:
                    _, _, width, height = result.region
                else:
                    width, height = 100, 50  # 默认值
            else:
                width, height = size
            left = x - width // 2
            top = y - height // 2
            
            # 绘制边界框
            cv2.rectangle(annotated, (left, top), (left + width, top + height), color, 2)
            
            # 添加标签
            label = f"{element_name} ({x},{y})"
            if element_name == "input_box_anchor":
                label = f"{element_name} (中点) ({x},{y})"
            annotated = put_chinese_text(
                annotated,
                label,
                (x + 25, y - 10),
                font_size=14,
                color=color
            )
            
            # 添加置信度
            conf_label = f"conf={result.confidence:.2f}"
            annotated = put_chinese_text(
                annotated,
                conf_label,
                (x + 25, y + 5),
                font_size=12,
                color=color
            )
        else:
            # 标注失败的元素（用虚线框在窗口中心）
            h, w = annotated.shape[:2]
            center_x, center_y = w // 2, h // 2
            
            # 绘制虚线（用多个小线段模拟）
            for i in range(0, 40, 5):
                cv2.line(annotated, 
                        (center_x - 20 + i, center_y - 20),
                        (center_x - 20 + i + 3, center_y - 20),
                        color, 1)
                cv2.line(annotated,
                        (center_x + 20 - i, center_y + 20),
                        (center_x + 20 - i - 3, center_y + 20),
                        color, 1)
            
            label = f"{element_name} (未找到)"
            annotated = put_chinese_text(
                annotated,
                label,
                (center_x + 25, center_y),
                font_size=14,
                color=color
            )
    
    # 标注所有联系人的头像位置和名称（如果提供了）
    if all_contact_avatars:
        logger.info(f"标注 {len(all_contact_avatars)} 个联系人的头像信息")
        contact_color = (0, 255, 255)  # 黄色，用于区分联系人头像
        
        for contact_result in all_contact_avatars:
            if not contact_result.locate_result.success:
                continue
            
            x = int(contact_result.locate_result.x or 0)
            y = int(contact_result.locate_result.y or 0)
            confidence = contact_result.locate_result.confidence
            
            # 绘制联系人头像位置（使用不同的颜色和样式）
            # 绘制外圈（更大的圆圈）
            cv2.circle(annotated, (x, y), 30, contact_color, 2)
            
            # 绘制中心点
            cv2.circle(annotated, (x, y), 5, contact_color, -1)
            
            # 计算边界框
            size = get_element_size("profile_photo_in_list")
            width, height = size
            left = x - width // 2
            top = y - height // 2
            
            # 绘制边界框（虚线样式，用多个小线段模拟）
            dash_length = 5
            gap_length = 3
            # 上边
            for i in range(0, width, dash_length + gap_length):
                end_x = min(left + i + dash_length, left + width)
                cv2.line(annotated, (left + i, top), (end_x, top), contact_color, 2)
            # 下边
            for i in range(0, width, dash_length + gap_length):
                end_x = min(left + i + dash_length, left + width)
                cv2.line(annotated, (left + i, top + height), (end_x, top + height), contact_color, 2)
            # 左边
            for i in range(0, height, dash_length + gap_length):
                end_y = min(top + i + dash_length, top + height)
                cv2.line(annotated, (left, top + i), (left, end_y), contact_color, 2)
            # 右边
            for i in range(0, height, dash_length + gap_length):
                end_y = min(top + i + dash_length, top + height)
                cv2.line(annotated, (left + width, top + i), (left + width, end_y), contact_color, 2)
            
            # 添加联系人名称标签（在头像右侧）
            contact_label = f"联系人: {contact_result.contact_name}"
            if contact_result.contact_id:
                contact_label += f" (ID: {contact_result.contact_id})"
            annotated = put_chinese_text(
                annotated,
                contact_label,
                (x + width // 2 + 10, y - 15),
                font_size=16,
                color=contact_color
            )
            
            # 添加位置和置信度信息
            pos_label = f"位置: ({x}, {y})"
            annotated = put_chinese_text(
                annotated,
                pos_label,
                (x + width // 2 + 10, y + 5),
                font_size=14,
                color=contact_color
            )
            
            conf_label = f"置信度: {confidence:.3f}"
            annotated = put_chinese_text(
                annotated,
                conf_label,
                (x + width // 2 + 10, y + 25),
                font_size=14,
                color=contact_color
            )
            
            logger.debug(f"  已标注联系人 '{contact_result.contact_name}' 的头像: ({x}, {y})")
    
    # 标注聊天区域中所有联系人的头像位置和名称（如果提供了）
    if all_contact_avatars_in_chat:
        logger.info(f"标注聊天区域中 {len(all_contact_avatars_in_chat)} 个联系人的头像信息")
        chat_contact_color = (0, 255, 128)  # 青绿色，用于区分聊天区域联系人头像
        
        for contact_result in all_contact_avatars_in_chat:
            if not contact_result.locate_result.success:
                continue
            
            x = int(contact_result.locate_result.x or 0)
            y = int(contact_result.locate_result.y or 0)
            confidence = contact_result.locate_result.confidence
            
            # 绘制聊天区域联系人头像位置（使用不同的颜色和样式）
            # 绘制外圈（更大的圆圈）
            cv2.circle(annotated, (x, y), 30, chat_contact_color, 2)
            
            # 绘制中心点
            cv2.circle(annotated, (x, y), 5, chat_contact_color, -1)
            
            # 计算边界框
            size = get_element_size("profile_photo_in_chat")
            width, height = size
            left = x - width // 2
            top = y - height // 2
            
            # 绘制边界框（实线，区别于列表区域的虚线）
            cv2.rectangle(annotated, (left, top), (left + width, top + height), chat_contact_color, 2)
            
            # 添加联系人名称标签（在头像右侧）
            contact_label = f"聊天: {contact_result.contact_name}"
            if contact_result.contact_id:
                contact_label += f" (ID: {contact_result.contact_id})"
            annotated = put_chinese_text(
                annotated,
                contact_label,
                (x + width // 2 + 10, y - 15),
                font_size=16,
                color=chat_contact_color
            )
            
            # 添加位置和置信度信息
            pos_label = f"位置: ({x}, {y})"
            annotated = put_chinese_text(
                annotated,
                pos_label,
                (x + width // 2 + 10, y + 5),
                font_size=14,
                color=chat_contact_color
            )
            
            conf_label = f"置信度: {confidence:.3f}"
            annotated = put_chinese_text(
                annotated,
                conf_label,
                (x + width // 2 + 10, y + 25),
                font_size=14,
                color=chat_contact_color
            )
            
            logger.debug(f"  已标注聊天区域联系人 '{contact_result.contact_name}' 的头像: ({x}, {y})")
    
    # 绘制 three_point_icon 与 sticker_icon 形成的矩形中点（用于 is_chat_at_bottom 等）
    try:
        r_three = _get_single_result(positions, "three_point_icon")
        r_sticker = _get_single_result(positions, "sticker_icon")
        if r_three and r_three.success and r_sticker and r_sticker.success:
            mid_x = ((r_three.x or 0) + (r_sticker.x or 0)) // 2
            mid_y = ((r_three.y or 0) + (r_sticker.y or 0)) // 2
            mid_color = (0, 255, 255)  # 黄色，便于区分
            cv2.circle(annotated, (mid_x, mid_y), 12, mid_color, 2)
            cv2.line(annotated, (mid_x - 25, mid_y), (mid_x + 25, mid_y), mid_color, 2)
            cv2.line(annotated, (mid_x, mid_y - 25), (mid_x, mid_y + 25), mid_color, 2)
            annotated = put_chinese_text(
                annotated,
                "three_point-sticker 中点",
                (mid_x - 60, mid_y - 35),
                font_size=12,
                color=mid_color
            )
            logger.debug(f"已绘制 three_point-sticker 中点: ({mid_x}, {mid_y})")
        else:
            logger.debug("未同时定位到 three_point_icon 与 sticker_icon，跳过中点绘制")
    except Exception as e:
        logger.debug(f"绘制 three_point-sticker 中点失败: {e}")
    
    # 保存标注后的图像
    if save_path:
        save_screenshot(
            annotated,
            "annotated_all_elements",
            task_id="element_locator",
            step_name="annotate_all",
            error_info=None
        )
        logger.info(f"标注图像已保存")
    
    return annotated


def test_locate_all_elements(
    contact_name: Optional[str] = None,
    contact_id: Optional[str] = None,
    test_all_contacts: bool = False
):
    """
    测试函数：定位所有元素并标注
    
    这个函数会：
    1. 截取微信窗口
    2. 定位所有UI元素
    3. 测试一次性定位所有联系人头像（如果test_all_contacts=True）
    4. 在截图上标注所有元素位置
    5. 保存标注后的图像
    6. 保存元素位置到JSON文件
    
    Args:
        contact_name: 联系人名称（可选，用于测试特定联系人的头像定位）
        contact_id: 联系人ID（可选，用于测试特定联系人的头像定位）
        test_all_contacts: 是否测试一次性定位所有联系人头像功能
    """
    try:
        # 获取窗口句柄
        hwnd = get_wechat_hwnd()
        logger.info(f"获取到窗口句柄: {hwnd}")
        
        # 截取窗口
        screenshot = capture_window(hwnd)
        logger.info(f"窗口截图尺寸: {screenshot.shape}")
        
        # 定位所有元素（如果提供了联系人信息，使用特定联系人的头像模板）
        logger.info("=" * 60)
        logger.info("步骤1: 定位所有UI元素")
        logger.info("=" * 60)
        if contact_name or contact_id:
            logger.info(f"使用特定联系人头像模板: {contact_name or '未知'}, ID: {contact_id or '未知'}")
        else:
            logger.info("使用默认头像模板")
        
        positions = locate_all_elements(
            screenshot, 
            threshold=0.7,
            contact_name=contact_name,
            contact_id=contact_id
        )
        
        # 统计结果（处理数组类型）
        success_count = 0
        total_count = len(positions)
        for result_or_list in positions.values():
            if isinstance(result_or_list, list):
                # 数组类型，统计成功数量
                success_count += sum(1 for r in result_or_list if r.success)
            else:
                # 单个结果
                if result_or_list.success:
                    success_count += 1
        logger.info(f"定位完成: {success_count} 个元素定位成功（共 {total_count} 个元素类型）")
        
        # 显示详细结果
        logger.info("\n详细定位结果:")
        for element_name, result_or_list in positions.items():
            if isinstance(result_or_list, list):
                # 数组类型（如profile_photo_in_chat）
                if result_or_list:
                    success_count_list = sum(1 for r in result_or_list if r.success)
                    logger.info(f"  {element_name}: {success_count_list}/{len(result_or_list)} 个成功")
                    for i, result in enumerate(result_or_list[:5]):  # 只显示前5个
                        if result.success:
                            logger.info(f"    [{i}] ({result.x}, {result.y}), 置信度={result.confidence:.3f}")
                else:
                    logger.info(f"  {element_name}: 未找到（空数组）")
            else:
                # 单个结果
                if result_or_list.success:
                    logger.info(f"  ✓ {element_name}: ({result_or_list.x}, {result_or_list.y}), 置信度={result_or_list.confidence:.3f}")
                else:
                    logger.info(f"  ✗ {element_name}: 定位失败 - {result_or_list.error_message}")
        
        # 测试一次性定位所有联系人头像功能（结果会在标注时使用）
        all_contact_results = None
        all_contact_results_in_chat = None
        if test_all_contacts:
            logger.info("\n" + "=" * 60)
            logger.info("步骤2: 测试一次性定位所有联系人头像")
            logger.info("=" * 60)
            try:
                # 根据环境变量配置的“我”联系人，在测试中排除掉
                try:
                    from .contact_mapper import ContactUserMapper as _TestContactUserMapper
                except ImportError:
                    from contact_mapper import ContactUserMapper as _TestContactUserMapper
                _mapper_for_test = _TestContactUserMapper()
                me_contact = _mapper_for_test.get_me_contact_name()
                exclude_for_test = [me_contact] if me_contact else None

                # 测试列表区域
                all_contact_results = locate_all_contact_avatars_in_list(
                    screenshot=screenshot,
                    threshold=0.7,
                    enabled_contacts_only=True,
                    exclude_contacts=exclude_for_test,
                )
                
                if all_contact_results:
                    logger.info(f"✓ 成功定位 {len(all_contact_results)} 个联系人的头像（列表区域）:")
                    for contact_result in all_contact_results:
                        logger.info(f"  联系人: {contact_result.contact_name}")
                        logger.info(f"    位置: ({contact_result.locate_result.x}, {contact_result.locate_result.y})")
                        logger.info(f"    置信度: {contact_result.locate_result.confidence:.3f}")
                        if contact_result.contact_id:
                            logger.info(f"    联系人ID: {contact_result.contact_id}")
                else:
                    logger.warning("✗ 未找到任何联系人的头像（列表区域）")
                
                # 测试聊天区域
                logger.info("\n测试聊天区域联系人头像定位...")
                all_contact_results_in_chat = locate_all_contact_avatars_in_chat(
                    screenshot=screenshot,
                    threshold=0.7,
                    enabled_contacts_only=True,
                    exclude_contacts=exclude_for_test,
                )
                
                if all_contact_results_in_chat:
                    logger.info(f"✓ 成功定位 {len(all_contact_results_in_chat)} 个联系人的头像（聊天区域）:")
                    for contact_result in all_contact_results_in_chat:
                        logger.info(f"  联系人: {contact_result.contact_name}")
                        logger.info(f"    位置: ({contact_result.locate_result.x}, {contact_result.locate_result.y})")
                        logger.info(f"    置信度: {contact_result.locate_result.confidence:.3f}")
                        if contact_result.contact_id:
                            logger.info(f"    联系人ID: {contact_result.contact_id}")
                else:
                    logger.warning("✗ 未找到任何联系人的头像（聊天区域）")
            except Exception as e:
                logger.error(f"测试一次性定位所有联系人头像失败: {e}")
                import traceback
                traceback.print_exc()
        
        # 标注所有元素
        logger.info("\n" + "=" * 60)
        logger.info("步骤3: 标注所有元素位置")
        logger.info("=" * 60)
        
        # 使用之前获取的所有联系人头像定位结果（如果测试了）
        annotated_image = annotate_all_elements(
            screenshot, 
            positions, 
            save_path=WeChatAutomationConfig.DEBUG_DIR / "annotated_all_elements.png",
            all_contact_avatars=all_contact_results if test_all_contacts else None,
            all_contact_avatars_in_chat=all_contact_results_in_chat if test_all_contacts else None
        )
        
        # 保存位置信息
        logger.info("\n" + "=" * 60)
        logger.info("步骤4: 保存元素位置信息")
        logger.info("=" * 60)
        save_element_positions(positions)
        
        logger.info("\n" + "=" * 60)
        logger.info("测试完成！")
        logger.info("=" * 60)
        return positions
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return {}


def get_contact_name_roi(
    positions: Dict[str, Union[LocateResult, List[LocateResult]]],
    expand_y: int = 10
) -> Optional[Tuple[int, int, int, int]]:
    """
    获取联系人名字区域的ROI（感兴趣区域）
    
    区域定义：
    - 左界：sticker_icon的左界再往左5像素
    - 右界：chat_message_icon的左界
    - 上界：pin_icon的下界
    - 下界：chat_message_icon的下界（可适当扩宽）
    
    Args:
        positions: 元素位置字典
        expand_y: Y方向扩展像素数（下界扩展）
    
    Returns:
        ROI区域 (x, y, width, height)，如果没有打开聊天界面则返回None
    """
    # 检查sticker_icon是否存在（判断是否打开聊天界面）
    sticker_result = _get_single_result(positions, "sticker_icon")
    if not sticker_result or not sticker_result.success:
        logger.debug("未找到sticker_icon，可能没有打开聊天界面")
        return None
    
    # 检查chat_message_icon是否存在
    chat_message_result = _get_single_result(positions, "chat_message_icon")
    if not chat_message_result or not chat_message_result.success:
        logger.warning("未找到chat_message_icon，无法确定联系人名字区域")
        return None
    
    # 检查pin_icon是否存在
    pin_result = _get_single_result(positions, "pin_icon")
    _cm_y = int(chat_message_result.y or 0)
    _st_y = int(sticker_result.y or 0)
    if not pin_result or not pin_result.success:
        logger.warning("未找到pin_icon，使用chat_message_icon的上界作为备选")
        # 如果没有pin_icon，使用chat_message_icon的上界作为备选
        chat_message_size = get_element_size("chat_message_icon")
        chat_message_height = chat_message_size[1]
        roi_top = _cm_y - chat_message_height // 2 - expand_y
    else:
        # 获取pin_icon的下界
        pin_size = get_element_size("pin_icon")
        pin_height = pin_size[1]
        roi_top = int(pin_result.y or 0) + pin_height // 2
    
    # 获取sticker_icon的左界，再往左移5像素
    sticker_size = get_element_size("sticker_icon")
    sticker_width, sticker_height = sticker_size
    sticker_left = int(sticker_result.x or 0) - sticker_width // 2
    roi_left = max(0, sticker_left - 5)  # 左界往左移5像素，不超出窗口
    
    # 获取chat_message_icon的左界和下界
    chat_message_size = get_element_size("chat_message_icon")
    chat_message_width, chat_message_height = chat_message_size
    chat_message_left = int(chat_message_result.x or 0) - chat_message_width // 2
    chat_message_bottom = _cm_y + chat_message_height // 2
    
    # 计算ROI
    roi_x = roi_left
    roi_y = roi_top
    roi_width = chat_message_left - roi_left
    roi_height = (chat_message_bottom - roi_top) + expand_y
    
    # 确保ROI有效
    if roi_width <= 0 or roi_height <= 0:
        logger.warning(f"计算出的ROI无效: x={roi_x}, y={roi_y}, width={roi_width}, height={roi_height}")
        return None
    
    logger.debug(f"联系人名字ROI: x={roi_x}, y={roi_y}, width={roi_width}, height={roi_height}")
    return (roi_x, roi_y, roi_width, roi_height)


def get_contact_name(
    screenshot: Optional[np.ndarray] = None,
    positions: Optional[Dict[str, Union[LocateResult, List[LocateResult]]]] = None,
    contact_name: Optional[str] = None,
    contact_id: Optional[str] = None,
    max_ocr_retries: int = 3,
    prefer_aliyun: bool = False,
) -> Optional[str]:
    """
    获取当前聊天界面联系人的名字
    
    为提高稳定性会进行重试：若首次 OCR 未识别到有效中文，会重新截屏再识别（最多 max_ocr_retries 次），
    避免窗口刚恢复时截图未完全重绘导致识别失败。
    当 prefer_aliyun=True 时强制使用阿里云 OCR（用于轮询时联系人名校验）。
    
    Args:
        screenshot: 窗口截图（BGR格式），如果为None则自动截取
        positions: 元素位置字典，如果为None则自动定位
        contact_name: 可选，用于定位时选用对应头像模板
        contact_id: 可选，用于定位时选用对应头像模板
        max_ocr_retries: OCR 重试次数（每次重试会重新截屏），默认 3
        prefer_aliyun: 为 True 时仅使用阿里云 OCR（不回退 Tesseract）
    
    Returns:
        联系人名字（字符串），如果没有打开聊天界面或识别失败则返回None
    """
    import time
    last_error: Optional[str] = None
    for attempt in range(max_ocr_retries):
        # 首次且调用方已传截图则用传入的；否则或重试时重新截屏
        if attempt == 0 and screenshot is not None:
            shot = screenshot
        else:
            try:
                hwnd = get_wechat_hwnd()
                shot = capture_window(hwnd)
            except Exception as e:
                logger.error(f"获取窗口截图失败: {e}")
                last_error = str(e)
                if attempt < max_ocr_retries - 1:
                    time.sleep(0.3)
                continue
        pos = positions if (positions is not None and attempt == 0) else locate_all_elements(
            shot, contact_name=contact_name, contact_id=contact_id
        )
        roi = get_contact_name_roi(pos)
        if roi is None:
            logger.debug("无法获取联系人名字区域，可能没有打开聊天界面")
            if attempt < max_ocr_retries - 1:
                time.sleep(0.3)
            continue
        try:
            text = ocr_region(shot, roi, save_preprocessed=False, expect_chinese=True, prefer_aliyun=prefer_aliyun)
            if text:
                text = text.strip()
                if text:
                    logger.debug(f"识别到联系人名字: '{text}'")
                    return text
        except Exception as e:
            logger.debug(f"OCR识别异常（尝试 {attempt + 1}/{max_ocr_retries}）: {e}")
            last_error = str(e)
        if attempt < max_ocr_retries - 1:
            time.sleep(0.3)
    logger.warning("OCR未识别到文字（已重试 %d 次）", max_ocr_retries)
    if last_error:
        logger.debug(f"最后错误: {last_error}")
    return None


def get_list_area_roi(
    positions: Dict[str, Union[LocateResult, List[LocateResult]]],
    image_height: Optional[int] = None,
) -> Optional[Tuple[int, int, int, int]]:
    """
    获取联系人列表区域的 ROI（用于标注与调试）。
    列表区域：左界 = search_bar_x - search_bar宽度*0.6（即宽度*1/2*120%），右界 = search_bar_x。
    返回 (x, y, width, height)。
    """
    search_bar_result = _get_single_result(positions, "search_bar")
    if not search_bar_result or not search_bar_result.success:
        return None
    sb_x = int(search_bar_result.x or 0)
    sb_y = int(search_bar_result.y or 0)
    size = get_element_size("search_bar")
    sb_w = size[0] if size else 180
    sb_h = size[1] if size else 40
    # 左界 = search_bar_x - search_bar宽度*0.6，右界 = search_bar_x
    list_left = max(0, sb_x - int(sb_w * 0.6))
    list_right = sb_x
    y_top = sb_y + sb_h // 2
    if image_height is not None and y_top >= image_height:
        return None
    h = (image_height - y_top) if image_height else 800
    width = list_right - list_left
    if h <= 0 or width <= 0:
        return None
    return (list_left, y_top, width, h)


def get_chat_area_roi(
    positions: Dict[str, Union[LocateResult, List[LocateResult]]],
    image_width: Optional[int] = None,
) -> Optional[Tuple[int, int, int, int]]:
    """
    获取聊天消息区域的ROI（感兴趣区域）
    
    区域定义：
    - 左界：sticker_icon的左界
    - 右界：video_call_icon的右界；若未找到 video_call_icon 且提供 image_width，则右界为界面最右（image_width）
    - 下界：sticker_icon的上界
    - 上界：chat_message_icon的下界和sticker_icon的上界的中间y值
    
    Args:
        positions: 元素位置字典
        image_width: 可选，窗口/截图宽度（像素）。当 video_call_icon 未定位到时，用此值作为右界（右边到界面最边缘）。
    
    Returns:
        ROI区域 (x, y, width, height)，如果没有打开聊天界面则返回None
    """
    # 检查sticker_icon是否存在（判断是否打开聊天界面）
    sticker_result = _get_single_result(positions, "sticker_icon")
    if not sticker_result or not sticker_result.success:
        logger.debug("未找到sticker_icon，可能没有打开聊天界面")
        return None
    
    # 检查chat_message_icon是否存在
    chat_message_result = _get_single_result(positions, "chat_message_icon")
    if not chat_message_result or not chat_message_result.success:
        logger.debug("未找到chat_message_icon，无法确定聊天区域上界")
        return None
    
    # 获取sticker_icon的左界和上界
    sticker_size = get_element_size("sticker_icon")
    sticker_width, sticker_height = sticker_size
    sticker_left = int(sticker_result.x or 0) - sticker_width // 2
    sticker_top = int(sticker_result.y or 0) - sticker_height // 2
    
    # 右界：优先 video_call_icon，否则用 image_width（界面最右边缘）
    video_call_result = _get_single_result(positions, "video_call_icon")
    if video_call_result and video_call_result.success:
        video_call_size = get_element_size("video_call_icon")
        video_call_width, video_call_height = video_call_size
        roi_right = int(video_call_result.x or 0) + video_call_width // 2
        logger.debug(f"聊天区域右界: video_call_icon 右界 = {roi_right}")
    elif image_width is not None and image_width > sticker_left:
        roi_right = image_width
        logger.debug(f"未找到video_call_icon，右界使用界面最右边缘: image_width = {roi_right}")
    else:
        logger.debug("未找到video_call_icon且未提供image_width，无法确定聊天区域右界")
        return None
    
    # 获取chat_message_icon的下界
    chat_message_size = get_element_size("chat_message_icon")
    chat_message_width, chat_message_height = chat_message_size
    chat_message_bottom = int(chat_message_result.y or 0) + chat_message_height // 2
    
    # 计算上界：chat_message_icon的下界和sticker_icon的上界的中间y值
    roi_top = (chat_message_bottom + sticker_top) // 2
    
    # 计算ROI
    roi_x = sticker_left
    roi_y = roi_top
    roi_width = roi_right - sticker_left
    roi_height = sticker_top - roi_top
    
    # 确保ROI有效
    if roi_width <= 0 or roi_height <= 0:
        logger.warning(f"计算出的聊天区域ROI无效: x={roi_x}, y={roi_y}, width={roi_width}, height={roi_height}")
        return None
    
    logger.debug(f"聊天区域ROI: x={roi_x}, y={roi_y}, width={roi_width}, height={roi_height}")
    return (roi_x, roi_y, roi_width, roi_height)


def is_chat_at_bottom(hwnd: Optional[int] = None, scroll_amount: int = 3, wait_after_scroll: float = 0.5) -> bool:
    """
    判断当前聊天页面是否已滚动到最下面（内容是否为最新）。
    逻辑：在 three_point_icon 与 sticker_icon 形成的矩形区域内取可操作中点，
    在该位置执行向下滚动，等待 wait_after_scroll 秒后截屏对比；若无变化则认为已在底部。
    
    Args:
        hwnd: 窗口句柄，None 则自动获取微信窗口
        scroll_amount: 滚轮单位数（向下）
        wait_after_scroll: 滚动后等待秒数再截屏对比
    
    Returns:
        True 表示已在最下面（再向下滚动无新内容），False 表示还能向下滚动
    """
    import time
    try:
        try:
            from .screen import get_wechat_hwnd, capture_window, get_window_client_bbox
            from .actions import scroll_at
        except ImportError:
            from screen import get_wechat_hwnd, capture_window, get_window_client_bbox
            from actions import scroll_at
        if hwnd is None:
            hwnd = get_wechat_hwnd()
        before = capture_window(hwnd)
        if before is None or getattr(before, "size", 0) == 0:
            return False
        positions = locate_all_elements(before)
        r1 = _get_single_result(positions, "three_point_icon")
        r2 = _get_single_result(positions, "sticker_icon")
        if not r1 or not r1.success or not r2 or not r2.success:
            logger.debug("is_chat_at_bottom: 未同时定位到 three_point_icon 与 sticker_icon")
            return False
        mid_x = ((r1.x or 0) + (r2.x or 0)) // 2
        mid_y = ((r1.y or 0) + (r2.y or 0)) // 2
        left, top, _w, _h = get_window_client_bbox(hwnd)
        screen_x = left + mid_x
        screen_y = top + mid_y
        scroll_at(screen_x, screen_y, "down", amount=scroll_amount, delay=wait_after_scroll)
        after = capture_window(hwnd)
        if after is None or after.shape != before.shape:
            return False
        if before.tobytes() == after.tobytes():
            logger.debug("is_chat_at_bottom: 滚动前后画面一致，判定为已在底部")
            return True
        logger.debug("is_chat_at_bottom: 滚动后画面有变化，未在底部")
        return False
    except Exception as e:
        logger.warning("is_chat_at_bottom 失败: %s", e)
        return False


# 全局状态管理器（向后兼容，使用全局单例）
_global_state_manager = None


def _get_state_manager() -> ChatStateManager:
    """获取状态管理器实例（使用全局单例）"""
    global _global_state_manager
    if _global_state_manager is None:
        _global_state_manager = get_global_manager()
    return _global_state_manager


def get_current_chat_hash(
    contact_name: Optional[str] = None,
    screenshot: Optional[np.ndarray] = None,
    positions: Optional[Dict[str, Union[LocateResult, List[LocateResult]]]] = None,
) -> Optional[str]:
    """
    获取当前聊天区域的感知哈希（不修改状态，用于轮询前与已保存的 UI hash 比较）。
    
    Args:
        contact_name: 联系人名称（可选），用于定位时选用对应头像模板
        screenshot: 窗口截图（可选），为 None 则自动截取
        positions: 元素位置字典（可选），为 None 则自动定位
    
    Returns:
        当前聊天区 ROI 的 pHash 字符串，若无法计算则返回 None
    """
    if not IMAGEHASH_AVAILABLE:
        return None
    try:
        if screenshot is None:
            hwnd = get_wechat_hwnd()
            screenshot = capture_window(hwnd)
        if positions is None:
            positions = locate_all_elements(screenshot, contact_name=contact_name)
        img_w = screenshot.shape[1] if screenshot is not None and len(screenshot.shape) >= 2 else None
        roi = get_chat_area_roi(positions, image_width=img_w)
        if roi is None:
            return None
        from PIL import Image as _PILImage
        import imagehash as _imagehash
        roi_x, roi_y, roi_width, roi_height = roi
        roi_image = screenshot[roi_y:roi_y + roi_height, roi_x:roi_x + roi_width]
        roi_pil = _PILImage.fromarray(cv2.cvtColor(roi_image, cv2.COLOR_BGR2RGB))
        current_hash = _imagehash.phash(roi_pil)
        return str(current_hash)
    except Exception as e:
        logger.debug("get_current_chat_hash 失败: %s", e)
        return None


def save_chat_state(
    positions: Optional[Dict[str, Union[LocateResult, List[LocateResult]]]] = None,
    screenshot: Optional[np.ndarray] = None,
    contact_name: Optional[str] = None,
    state_manager: Optional[ChatStateManager] = None
) -> bool:
    """
    保存当前聊天状态（用于发送消息后调用）
    
    保存profile_photo_in_chat的y位置信息，用于后续判断是否有新消息。
    现在支持为每个联系人单独维护状态（通过contact_name参数）。
    
    向后兼容：
    - 如果不提供contact_name，使用默认状态（与旧版本行为一致）
    - 如果提供contact_name，为该联系人单独维护状态
    
    Args:
        positions: 元素位置字典，如果为None则自动定位
        screenshot: 窗口截图，如果为None则自动截取
        contact_name: 联系人名称（可选），如果提供则为此联系人单独保存状态
        state_manager: 状态管理器实例（可选），如果为None则使用全局单例
    
    Returns:
        是否成功保存
    
    Example:
        # 为特定联系人保存状态
        save_chat_state(contact_name="策月帘风")
        
        # 使用默认状态（向后兼容）
        save_chat_state()
    """
    try:
        # 获取状态管理器
        manager = state_manager if state_manager is not None else _get_state_manager()
        
        # 如果没有提供截图，自动截取（支持包内/独立目录两种运行方式）
        if screenshot is None:
            try:
                from .screen import get_wechat_hwnd, capture_window
            except ImportError:
                from screen import get_wechat_hwnd, capture_window
            hwnd = get_wechat_hwnd()
            screenshot = capture_window(hwnd)
        
        # 如果没有提供位置信息，自动定位
        if positions is None:
            positions = locate_all_elements(screenshot, contact_name=contact_name)
        
        # 获取聊天区域ROI（无 video_call_icon 时右界用界面最右边缘）
        img_w = screenshot.shape[1] if screenshot is not None and len(screenshot.shape) >= 2 else None
        roi = get_chat_area_roi(positions, image_width=img_w)
        if roi is None:
            logger.warning(f"无法获取聊天区域ROI，无法保存状态 (联系人: {contact_name or '默认'})")
            return False
        
        # 计算聊天区域的感知哈希
        chat_hash = None
        if IMAGEHASH_AVAILABLE:
            from PIL import Image as _PILImage
            import imagehash as _imagehash
            roi_x, roi_y, roi_width, roi_height = roi
            roi_image = screenshot[roi_y:roi_y+roi_height, roi_x:roi_x+roi_width]
            roi_pil = _PILImage.fromarray(cv2.cvtColor(roi_image, cv2.COLOR_BGR2RGB))
            chat_hash = str(_imagehash.phash(roi_pil))
            logger.debug(f"保存联系人 '{contact_name or '默认'}' 的聊天区域hash: {chat_hash[:16]}...")
        
        # 保存头像y位置（仅保留非 None 的 y 坐标）
        profile_photo_in_chat = positions.get("profile_photo_in_chat")
        avatar_y_positions: List[int] = []
        if profile_photo_in_chat and isinstance(profile_photo_in_chat, list):
            avatar_y_positions = [r.y for r in profile_photo_in_chat if r.success and r.y is not None]
            logger.debug(f"保存联系人 '{contact_name or '默认'}' 的头像y位置: {avatar_y_positions}")
        
        # 使用状态管理器保存状态
        manager.save_state(
            contact_name=contact_name,
            chat_hash=chat_hash,
            avatar_y_positions=avatar_y_positions
        )
        
        return True
    
    except Exception as e:
        logger.error(f"保存聊天状态失败 (联系人: {contact_name or '默认'}): {e}")
        return False


def clear_chat_state(contact_name: Optional[str] = None) -> bool:
    """
    清除指定联系人的视觉基线（与信息锚点绑定：锚点重置/初始化失败时调用，避免视觉状态与锚点不一致）。
    
    Args:
        contact_name: 联系人名称，None 表示默认键
    
    Returns:
        是否成功清除
    """
    try:
        manager = _get_state_manager()
        return manager.clear_state(contact_name=contact_name)
    except Exception as e:
        logger.error(f"清除聊天状态失败 (联系人: {contact_name or '默认'}): {e}")
        return False


def has_new_message(
    positions: Optional[Dict[str, Union[LocateResult, List[LocateResult]]]] = None,
    screenshot: Optional[np.ndarray] = None,
    hash_threshold: int = 8,
    contact_name: Optional[str] = None,
    state_manager: Optional[ChatStateManager] = None
) -> bool:
    """
    判断是否有新消息（使用视觉指纹方法）
    
    方案：
    1. 使用感知哈希（pHash）比较聊天区域的变化
    2. 如果hash变化超过阈值，再检查头像y位置是否变化
    
    现在支持为每个联系人单独维护状态，通过contact_name参数区分。
    
    向后兼容：
    - 如果不提供contact_name，使用默认状态（与旧版本行为一致）
    - 如果提供contact_name，为该联系人单独判断新消息
    
    Args:
        positions: 元素位置字典，如果为None则自动定位
        screenshot: 窗口截图，如果为None则自动截取
        hash_threshold: 哈希差异阈值（pHash建议8-12）
        contact_name: 联系人名称（可选），如果提供则为此联系人单独判断新消息
        state_manager: 状态管理器实例（可选），如果为None则使用全局单例
    
    Returns:
        是否有新消息
    
    Example:
        # 为特定联系人判断新消息
        has_new = has_new_message(contact_name="策月帘风")
        
        # 使用默认状态（向后兼容）
        has_new = has_new_message()
    """
    if not IMAGEHASH_AVAILABLE:
        logger.warning("imagehash未安装，无法使用视觉指纹检测新消息；降级为「假定可能有新消息」以便 poll 仍会尝试读取")
        return True  # 降级：让 message_channel 仍尝试读取，避免 CLI read 永远返回「暂无新消息」
    
    try:
        # 获取状态管理器
        manager = state_manager if state_manager is not None else _get_state_manager()
        
        # 如果没有提供截图，自动截取（支持包内/独立目录两种运行方式）
        if screenshot is None:
            try:
                from .screen import get_wechat_hwnd, capture_window
            except ImportError:
                from screen import get_wechat_hwnd, capture_window
            hwnd = get_wechat_hwnd()
            screenshot = capture_window(hwnd)
        
        # 如果没有提供位置信息，自动定位
        if positions is None:
            positions = locate_all_elements(screenshot, contact_name=contact_name)
        
        # 获取聊天区域ROI（无 video_call_icon 时右界用界面最右边缘）
        img_w = screenshot.shape[1] if screenshot is not None and len(screenshot.shape) >= 2 else None
        roi = get_chat_area_roi(positions, image_width=img_w)
        if roi is None:
            logger.info(f"[has_new_message] 无法获取聊天区域ROI (联系人: {contact_name or '默认'})，判定为无新消息")
            return False
        
        # 计算当前聊天区域的感知哈希
        from PIL import Image as _PILImage
        import imagehash as _imagehash
        roi_x, roi_y, roi_width, roi_height = roi
        roi_image = screenshot[roi_y:roi_y+roi_height, roi_x:roi_x+roi_width]
        roi_pil = _PILImage.fromarray(cv2.cvtColor(roi_image, cv2.COLOR_BGR2RGB))
        current_hash = _imagehash.phash(roi_pil)
        current_hash_str = str(current_hash)
        
        # 获取当前头像y位置（仅保留非 None 的 y 坐标）
        profile_photo_in_chat = positions.get("profile_photo_in_chat")
        current_avatar_y_positions: List[int] = []
        if profile_photo_in_chat and isinstance(profile_photo_in_chat, list):
            current_avatar_y_positions = [r.y for r in profile_photo_in_chat if r.success and r.y is not None]
        
        # 使用状态管理器判断新消息
        has_new = manager.has_new_message(
            contact_name=contact_name,
            current_hash=current_hash_str,
            current_avatar_y_positions=current_avatar_y_positions,
            hash_threshold=hash_threshold
        )
        
        return has_new
    
    except Exception as e:
        logger.error(f"判断新消息失败 (联系人: {contact_name or '默认'}): {e}")
        return False


def has_new_message_by_red_point(
    positions: Optional[Dict[str, Union[LocateResult, List[LocateResult]]]] = None,
    screenshot: Optional[np.ndarray] = None,
    contact_name: Optional[str] = None
) -> bool:
    """
    判断是否有新消息（基于红点存在性方法）
    
    方案：
    1. 定位联系人列表中的新消息红点（new_message_red_point）
    2. 如果找到红点，说明有新消息
    3. 如果没找到红点，说明没有新消息
    
    优点：
    - 简单直接，不需要计算hash
    - 不依赖imagehash库
    - 微信官方UI提示，可靠性高
    
    缺点：
    - 需要先打开联系人列表（如果当前在聊天窗口）
    - 红点可能被其他UI元素遮挡
    
    Args:
        positions: 元素位置字典，如果为None则自动定位
        screenshot: 窗口截图，如果为None则自动截取
        contact_name: 联系人名称（可选，用于日志输出）
    
    Returns:
        是否有新消息（True表示有新消息，False表示没有新消息）
    """
    try:
        # 如果没有提供截图，自动截取（支持包内/独立目录两种运行方式）
        if screenshot is None:
            try:
                from .screen import get_wechat_hwnd, capture_window
            except ImportError:
                from screen import get_wechat_hwnd, capture_window
            hwnd = get_wechat_hwnd()
            screenshot = capture_window(hwnd)
        
        # 如果没有提供位置信息，自动定位
        if positions is None:
            positions = locate_all_elements(screenshot)
        
        # 定位新消息红点
        red_point_result = _get_single_result(positions, "new_message_red_point")
        
        # 准备联系人信息字符串（用于日志）
        contact_info = f" ({contact_name})" if contact_name else ""
        
        if red_point_result is None:
            logger.debug(f"未找到new_message_red_point元素{contact_info}，无法判断新消息")
            return False
        
        # 检查红点是否成功定位
        if red_point_result.success:
            _rx, _ry = red_point_result.x or 0, red_point_result.y or 0
            logger.info(f"检测到新消息红点{contact_info}: ({_rx}, {_ry}), 置信度={red_point_result.confidence:.3f}")
            return True
        else:
            # 红点定位失败，说明没有新消息（或红点不存在）
            logger.debug(f"未检测到新消息红点{contact_info}，最佳置信度={red_point_result.confidence:.3f}")
            return False
    
    except Exception as e:
        logger.error(f"基于红点判断新消息失败: {e}")
        import traceback
        logger.debug(traceback.format_exc())
        return False


def get_contacts_with_new_message_red_point(
    screenshot: Optional[np.ndarray] = None,
    threshold: Optional[float] = None,
    contact_mapper: Optional["ContactUserMapper"] = None,
    enabled_contacts_only: bool = True,
) -> List[str]:
    """
    扫描联系人列表，检测哪些联系人的头像右上角存在新消息红点。
    判定逻辑：检测区域内红色像素面积占比大于配置阈值（默认 70%）则判定为有红点。

    Args:
        screenshot: 窗口截图（BGR），若为 None 则自动截取
        threshold: 红色面积占比阈值（0.0–1.0）；不传时使用 config.RED_POINT_AREA_RATIO_THRESHOLD
        contact_mapper: 联系人映射器，若为 None 则创建新实例
        enabled_contacts_only: 是否只扫描启用的联系人

    Returns:
        存在新消息红点的联系人名称列表（可能为空或包含多个）。
    """
    try:
        from .config import WeChatAutomationConfig as _config
    except ImportError:
        from config import WeChatAutomationConfig as _config
    ratio_threshold: float = (
        threshold if threshold is not None else getattr(_config, "RED_POINT_AREA_RATIO_THRESHOLD", 0.7)
    )

    if screenshot is None:
        try:
            from .screen import get_wechat_hwnd, capture_window
        except ImportError:
            from screen import get_wechat_hwnd, capture_window
        hwnd = get_wechat_hwnd()
        screenshot = capture_window(hwnd)

    if len(screenshot.shape) < 3:
        logger.debug("[新消息红点] 需要 BGR 截图")
        return []

    if contact_mapper is None:
        try:
            from .contact_mapper import ContactUserMapper
        except ImportError:
            from contact_mapper import ContactUserMapper
        contact_mapper = ContactUserMapper()

    contact_avatars = locate_all_contact_avatars_in_list(
        screenshot=screenshot,
        threshold=0.7,
        contact_mapper=contact_mapper,
        enabled_contacts_only=enabled_contacts_only,
    )
    if not contact_avatars:
        logger.debug("[新消息红点] 未找到任何联系人头像")
        return []

    avatar_size = get_element_size("profile_photo_in_list")
    avatar_radius = (avatar_size[0] if avatar_size else 50) // 2
    search_radius = 10
    h_img, w_img = screenshot.shape[:2]
    contact_names_with_red_point: List[str] = []

    for contact_result in contact_avatars:
        avatar_x = contact_result.locate_result.x or 0
        avatar_y = contact_result.locate_result.y or 0
        contact_name = contact_result.contact_name
        top_right_x = avatar_x + avatar_radius
        top_right_y = avatar_y - avatar_radius
        search_left = max(0, int(top_right_x - search_radius))
        search_right = min(w_img, int(top_right_x + search_radius))
        search_top = max(0, int(top_right_y - search_radius))
        search_bottom = min(h_img, int(top_right_y + search_radius))
        if search_right <= search_left or search_bottom <= search_top:
            continue
        ratio, cx, cy = _red_pixel_ratio_in_region(
            screenshot, search_left, search_top, search_right, search_bottom
        )
        if ratio >= ratio_threshold:
            contact_names_with_red_point.append(contact_name)
            logger.debug(
                f"[新消息红点] 联系人 {contact_name} 红色占比={ratio:.2%} >= {ratio_threshold:.0%}, 判定有红点: ({cx}, {cy})"
            )

    return contact_names_with_red_point