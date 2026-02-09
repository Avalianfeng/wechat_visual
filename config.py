"""微信自动化配置管理

定义微信自动化的运行约束和配置项。

运行约束（必须严格遵守）：
1. 窗口约束：微信窗口必须固定位置和大小，必须前台运行
2. 显示约束：DPI 缩放支持自适应（100%/125%/150% 等均可），推荐 1920x1080 分辨率
3. 语言约束：微信界面必须为简体中文
4. 输入法约束：优先使用剪贴板策略，避免输入法干扰

配置项：
- 窗口位置和大小
- DPI和分辨率设置
- 模板图片路径
- OCR关键词配置
- 重试策略
- 超时设置

注意事项：
1. 所有配置项应在启动前验证
2. 配置变更需要重启服务
3. 生产环境配置应通过环境变量或配置文件管理
"""

import os
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from dotenv import load_dotenv

# 先加载项目根目录下的 .env（如果存在），用于管理环境变量
# 例如：WECHAT_ME_CONTACT、ALIYUN_OCR_APPCODE 等
_BASE_DIR = Path(__file__).parent
load_dotenv(dotenv_path=_BASE_DIR / ".env", override=False)

# 支持相对导入（作为模块）和绝对导入（直接运行）
try:
    from .models import WeChatConfig
except ImportError:
    # 如果相对导入失败，尝试绝对导入（用于直接运行或测试）
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from models import WeChatConfig


class ConfigValidationError(Exception):
    """配置验证失败（硬失败）：必须成立的前提未满足，启动前应直接报错。"""
    pass


class WeChatAutomationConfig:
    """微信自动化配置类"""
    
    # ========== 窗口约束配置 ==========
    WINDOW_POSITION = (0, 0)  # 窗口位置（左上角对齐）
    WINDOW_SIZE = (1200, 800)  # 窗口大小（宽x高）
    WINDOW_TITLE = "微信"  # 窗口标题
    MUST_FOREGROUND = True  # 必须前台运行
    
    # ========== 显示约束配置 ==========
    DPI_SCALE = 100  # DPI 缩放基准（实际使用系统当前缩放，自适应）
    DISPLAY_RESOLUTION = (1920, 1080)  # 推荐分辨率
    COLOR_DEPTH = 32  # 颜色深度
    
    # ========== 微信设置约束 ==========
    WECHAT_LANGUAGE = "zh_CN"  # 界面语言（必须简体中文）
    WECHAT_FONT_SIZE = "normal"  # 字体大小
    WECHAT_THEME = "light"  # 主题（浅色，OCR更稳定）
    
    # ========== 输入法约束 ==========
    INPUT_STRATEGY = "clipboard"  # 输入策略：clipboard/direct
    INPUT_FALLBACK = "direct"  # 备用策略
    AVOID_IME = True  # 避免输入法干扰
    
    # ========== 路径配置 ==========
    BASE_DIR = _BASE_DIR
    ASSETS_DIR = BASE_DIR / "assets"
    TEMPLATES_DIR = ASSETS_DIR / "templates"
    CONTACTS_DIR = ASSETS_DIR / "contacts"  # 联系人头像目录
    OCR_KEYWORDS_DIR = ASSETS_DIR / "ocr_keywords"
    DEBUG_DIR = BASE_DIR / "debug"
    ELEMENT_POSITIONS_FILE = DEBUG_DIR / "element_positions.json"  # 元素位置配置文件（调试用）
    ANCHOR_STATE_FILE = DEBUG_DIR / "message_anchor_state.json"  # 消息锚点持久化（按次调用读取时用）
    VISUAL_STATE_FILE = DEBUG_DIR / "visual_state.json"  # 聊天区 UI 哈希持久化（按联系人，用于轮询时先比较再 OCR）
    
    # ========== 阿里云 OCR（高精版）==========
    # 设置环境变量 ALIYUN_OCR_APPCODE 或在代码中赋值，优先使用阿里云 OCR；未设置时回退到 Tesseract
    ALIYUN_OCR_APPCODE = os.environ.get("ALIYUN_OCR_APPCODE", "f121886fece64b1daaaacea7d01e2137")
    ALIYUN_OCR_URL = "https://gjbsb.market.alicloudapi.com/ocrservice/advanced"
    
    # ========== 模板图片路径 ==========
    TEMPLATE_PATHS = {
        # 搜索相关
        "search_icon": TEMPLATES_DIR / "search_icon.png",  # 默认（light主题，未搜索状态）
        "search_icon_dark": TEMPLATES_DIR / "search_icon_dark.png",  # 暗色主题，未搜索状态
        "search_icon_ing": TEMPLATES_DIR / "search_icon_ing.png",  # light主题，搜索中状态（Ctrl+F后）
        "search_icon_dark_ing": TEMPLATES_DIR / "search_icon_dark_ing.png",  # 暗色主题，搜索中状态（Ctrl+F后）
        "search_bar": TEMPLATES_DIR / "search_bar.png",
        "search_bar_ing": TEMPLATES_DIR / "search_bar_ing.png",  # 搜索框输入中状态
        # 输入框相关
        "input_box_anchor": TEMPLATES_DIR / "input_box_anchor.png",
        "input_box_anchor_light": TEMPLATES_DIR / "input_box_anchor_light.png",
        "input_box_anchor_dark": TEMPLATES_DIR / "input_box_anchor_dark.png",
        # 发送按钮
        "send_button": TEMPLATES_DIR / "send_button.png",
        "send_button_default": TEMPLATES_DIR / "send_button_default.png",  # 发送按钮默认状态
        # 聊天列表
        "chat_list_item": TEMPLATES_DIR / "chat_list_item.png",
        # 消息气泡
        "message_bubble": TEMPLATES_DIR / "message_bubble.png",
        # 发送区域工具栏图标（用于定位下边界）
        "toolbar_sticker": TEMPLATES_DIR / "sticker_icon.png",  # 表情图标
        "toolbar_save": TEMPLATES_DIR / "save_icon.png",  # 收藏图标
        "toolbar_file": TEMPLATES_DIR / "file_icon.png",  # 文件图标
        "toolbar_screencap": TEMPLATES_DIR / "screencap_icon.png",  # 截图图标
        "toolbar_tape": TEMPLATES_DIR / "tape_icon.png",  # 磁带/录音等图标（微信更新后新增，在截图图标右侧）
        "toolbar_voice_call": TEMPLATES_DIR / "voice_call_icon.png",  # 语音通话图标
        "toolbar_video_call": TEMPLATES_DIR / "video_call_icon.png",  # 视频通话图标
        # 顶部栏图标（用于定位上边界）
        "topbar_chat_message": TEMPLATES_DIR / "chat_message_icon.png",  # 聊天信息图标
        "topbar_three_point": TEMPLATES_DIR / "three_point_icon.png",  # 三个点图标
        "topbar_pin": TEMPLATES_DIR / "pin_icon.png",  # 置顶图标
        # 头像（用于定位消息气泡）
        # 注意：profile_photo 现在已迁移到 contacts 目录，每个联系人有独立的头像文件
        # 这里保留作为默认头像路径（向后兼容）
        "profile_photo": TEMPLATES_DIR / "profile_photo.png",  # 默认头像图标（向后兼容，已废弃）
        # 新消息红点（未读消息标识）
        "new_message_red_point": TEMPLATES_DIR / "new_message_red_point.png",  # 新消息红点（在联系人列表头像右上角）
    }
    
    # ========== 联系人头像配置 ==========
    DEFAULT_PROFILE_PHOTO = CONTACTS_DIR / "default_profile_photo.png"  # 默认头像路径
    
    @classmethod
    def get_contact_profile_photo_path(cls, contact_name: str = "", contact_id: str = "") -> Path:
        """
        获取联系人头像路径
        
        优先级：
        1. 如果提供了contact_id和contact_name，优先查找 {contact_id}_{contact_name}.png
        2. 如果只提供了contact_name，查找 {contact_name}.png
        3. 如果都未提供或文件不存在，返回默认头像路径
        
        Args:
            contact_name: 联系人名称（可选）
            contact_id: 联系人ID（可选）
        
        Returns:
            头像文件路径
        """
        logger = logging.getLogger(__name__)
        
        # 确保联系人目录存在
        cls.CONTACTS_DIR.mkdir(parents=True, exist_ok=True)
        
        # 尝试多种命名方式
        possible_paths = []
        
        if contact_id and contact_name:
            # 优先级1: {contact_id}_{contact_name}.png
            path1 = cls.CONTACTS_DIR / f"{contact_id}_{contact_name}.png"
            possible_paths.append(("ID+名称", path1))
        
        if contact_name:
            # 优先级2: {contact_name}.png
            path2 = cls.CONTACTS_DIR / f"{contact_name}.png"
            possible_paths.append(("名称", path2))
        
        # 查找存在的文件
        for desc, path in possible_paths:
            if path.exists():
                logger.debug(f"找到联系人头像 ({desc}): {path}")
                return path
        
        # 如果都没找到，使用默认头像
        default_path = cls.DEFAULT_PROFILE_PHOTO
        
        # 如果默认头像不存在，尝试从templates目录复制（向后兼容）
        if not default_path.exists():
            old_default = cls.TEMPLATES_DIR / "profile_photo.png"
            if old_default.exists():
                logger.info(f"默认头像不存在，从旧位置复制: {old_default} -> {default_path}")
                import shutil
                shutil.copy2(old_default, default_path)
                return default_path
            else:
                logger.warning(f"默认头像不存在: {default_path}，且旧位置也没有: {old_default}")
        
        logger.debug(f"使用默认头像: {default_path}")
        return default_path
    
    @classmethod
    def list_contact_profile_photos(cls) -> list[Path]:
        """
        列出所有联系人头像文件
        
        Returns:
            头像文件路径列表
        """
        if not cls.CONTACTS_DIR.exists():
            return []
        
        # 查找所有png文件
        photos = list(cls.CONTACTS_DIR.glob("*.png"))
        return sorted(photos)
    
    # ========== OCR关键词配置 ==========
    OCR_KEYWORDS_FILE = OCR_KEYWORDS_DIR / "keywords.json"
    
    # ========== 重试策略 ==========
    MAX_RETRY_COUNT = 3  # 最大重试次数
    RETRY_INTERVAL = 0.5  # 重试间隔（秒）
    
    # ========== 超时设置 ==========
    OPERATION_TIMEOUT = 5  # 单次操作超时（秒）
    FLOW_TIMEOUT = 30  # 流程超时（秒）
    LOCATE_TIMEOUT = 3  # 定位超时（秒）

    # ========== 红点检测 ==========
    # 红点判定逻辑：检测区域内红色像素面积占比超过此阈值则判定为有红点（默认 0.7）
    RED_POINT_AREA_RATIO_THRESHOLD = 0.6
    # 以下为旧版模板匹配用，若使用面积占比逻辑则可不依赖
    RED_POINT_MATCH_THRESHOLD = 0.5
    
    # ========== 延迟设置 ==========
    CLICK_DELAY = 0.1  # 点击后延迟（秒）
    INPUT_DELAY = 0.2  # 输入后延迟（秒）
    SCROLL_DELAY = 0.3  # 滚动后延迟（秒）
    
    # ========== 调试设置 ==========
    SAVE_SCREENSHOT_ON_ERROR = True  # 错误时保存截图
    SAVE_SCREENSHOT_ON_SUCCESS = False  # 成功时保存截图（调试用）
    LOG_LEVEL = "INFO"  # 日志级别
    
    # ========== 必需模板文件 ==========
    # 这些模板是核心功能必需的（基于 element_locator.py 的实际使用）
    # 注意：element_locator 使用模板路径键名，不是文件名
    REQUIRED_TEMPLATES = {
        # 顶部栏图标（用于定位聊天区域上边界）
        "topbar_chat_message",  # 聊天信息图标 -> chat_message_icon.png
        "topbar_three_point",  # 三个点图标 -> three_point_icon.png
        "topbar_pin",  # 置顶图标 -> pin_icon.png
        # 搜索框（用于定位联系人列表区域）
        "search_bar",  # 搜索框 -> search_bar.png（包含search_bar_ing状态）
        # 头像（用于定位消息气泡）
        "profile_photo",  # 头像图标 -> profile_photo.png
        # 工具栏图标（用于定位输入区域和聊天区域下边界）
        "toolbar_sticker",  # 表情图标 -> sticker_icon.png
        "toolbar_video_call",  # 视频通话图标 -> video_call_icon.png（用于计算聊天区域ROI）
        # 发送按钮（用于定位输入框）
        "send_button",  # 发送按钮 -> send_button.png（包含send_button_default状态）
    }
    
    # ========== 可选模板文件（依赖其他元素） ==========
    # 这些模板用于增强功能，依赖其他元素才能定位
    DEPENDENT_TEMPLATES = {
        "new_message_red_point",  # 新消息红点 -> new_message_red_point.png（依赖profile_photo_in_list）
    }
    
    # ========== 可选模板文件 ==========
    # 这些模板用于增强功能，缺失时功能可能受限但不影响基本使用
    OPTIONAL_TEMPLATES = {
        # 搜索框相关（已废弃，不再使用）
        "search_icon",  # 旧版搜索图标（已废弃）
        "search_icon_ing",  # 旧版搜索中状态图标（已废弃）
        "search_icon_dark",  # 暗色主题搜索图标（已废弃）
        "search_icon_dark_ing",  # 暗色主题搜索中图标（已废弃）
        "search_bar_ing",  # 搜索框输入中状态（可选，search_bar已包含此功能）
        # 输入框相关
        "input_box_anchor",  # 输入框锚点（可选，现在使用sticker_icon和send_button的中点定位）
        "input_box_anchor_light",  # 亮色主题输入框锚点（可选）
        "input_box_anchor_dark",  # 暗色主题输入框锚点（可选）
        # 工具栏图标（可选，用于增强定位）
        "toolbar_save",  # 收藏图标 -> save_icon.png
        "toolbar_file",  # 文件图标 -> file_icon.png
        "toolbar_screencap",  # 截图图标 -> screencap_icon.png
        "toolbar_tape",  # 磁带/录音等图标 -> tape_icon.png
        "toolbar_voice_call",  # 语音通话图标 -> voice_call_icon.png
        "send_button_default",  # 发送按钮默认状态（可选，send_button已包含此功能）
        # 其他（已废弃或未实现）
        "chat_list_item",  # 聊天列表项（已废弃）
        "message_bubble",  # 消息气泡（已废弃）
    }
    
    @classmethod
    def validate(cls, strict: bool = False) -> tuple[bool, str]:
        """
        验证配置是否满足运行约束
        
        Args:
            strict: 是否严格验证（True=所有模板必需，False=只验证必需模板）
        
        Returns:
            (is_valid, error_message): 配置是否有效，错误信息
        """
        errors = []
        
        # DPI 已自适应，不再校验必须 100%
        
        # 验证窗口大小
        if cls.WINDOW_SIZE[0] < 800 or cls.WINDOW_SIZE[1] < 600:
            errors.append(f"窗口大小过小，推荐至少800x600，当前为{cls.WINDOW_SIZE}")
        
        # 验证语言设置
        if cls.WECHAT_LANGUAGE != "zh_CN":
            errors.append(f"微信界面语言必须为简体中文(zh_CN)，当前为{cls.WECHAT_LANGUAGE}")
        
        # 验证模板文件
        templates_to_check = cls.TEMPLATE_PATHS if strict else {
            name: path for name, path in cls.TEMPLATE_PATHS.items()
            if name in cls.REQUIRED_TEMPLATES
        }
        
        missing_required = []
        missing_optional = []
        
        for name, path in cls.TEMPLATE_PATHS.items():
            if not path.exists():
                if name in cls.REQUIRED_TEMPLATES:
                    missing_required.append(f"{name} -> {path.name}")
                elif name in cls.OPTIONAL_TEMPLATES:
                    missing_optional.append(f"{name} -> {path.name}")
        
        if missing_required:
            errors.append(f"必需模板文件缺失: {', '.join(missing_required)}")
        
        if strict and missing_optional:
            errors.append(f"可选模板文件缺失: {', '.join(missing_optional)}")
        
        if errors:
            return False, "; ".join(errors)
        return True, ""
    
    @classmethod
    def validate_config(cls, strict: bool = False) -> None:
        """
        配置自检：硬失败（FAIL FAST），不返回布尔值。
        用于启动前校验「必须成立的前提」；未通过则直接抛出 ConfigValidationError。
        
        - 必需模板缺失 → 抛 ConfigValidationError
        - 窗口过小 → 抛 ConfigValidationError
        - 语言 != zh_CN → 抛 ConfigValidationError
        - strict=True 时，可选模板缺失也会抛 ConfigValidationError
        
        Args:
            strict: True=所有模板（含可选）必需；False=仅必需模板。
        """
        is_valid, error_message = cls.validate(strict=strict)
        if not is_valid:
            raise ConfigValidationError(error_message)
    
    @classmethod
    def get_config(cls) -> WeChatConfig:
        """获取配置对象"""
        return WeChatConfig(
            window_position=cls.WINDOW_POSITION,
            window_size=cls.WINDOW_SIZE,
            window_title=cls.WINDOW_TITLE,
            dpi_scale=cls.DPI_SCALE,
            display_resolution=cls.DISPLAY_RESOLUTION,
            language=cls.WECHAT_LANGUAGE,
            input_method=cls.INPUT_STRATEGY,
        )
    
    @classmethod
    def ensure_directories(cls):
        """确保必要的目录存在"""
        cls.ASSETS_DIR.mkdir(exist_ok=True)
        cls.TEMPLATES_DIR.mkdir(exist_ok=True)
        cls.CONTACTS_DIR.mkdir(exist_ok=True)
        cls.OCR_KEYWORDS_DIR.mkdir(exist_ok=True)
        cls.DEBUG_DIR.mkdir(exist_ok=True)
