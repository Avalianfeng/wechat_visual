"""基础操作模块

提供基础的自动化操作，包括点击、输入、粘贴、快捷键等。

核心功能：
- activate_window(): 激活微信窗口（置前）
- click(): 点击指定坐标（支持相对窗口坐标）
- hotkey(): 快捷键操作（Ctrl+F, Ctrl+A, Ctrl+V, Enter, Esc等）
- paste_text(): 剪贴板粘贴文本
- type_text(): 模拟打字（可选）
- human_delay(): 人类化延迟策略

注意事项：
1. 所有操作前应确保窗口处于前台
2. 操作后应添加适当延迟，等待界面响应
3. 使用剪贴板粘贴比直接输入更稳定
4. 点击操作应使用相对坐标（窗口内坐标）
5. 快捷键操作比视觉定位更稳定
6. 人类化延迟使操作更自然

依赖库：
- pyautogui: 基础自动化操作
- pyperclip: 剪贴板操作
- pywin32: Windows API操作
"""

import random
import time
import logging
from typing import Optional
from pathlib import Path
from io import BytesIO
import pyautogui
import pyperclip
import win32gui
import win32con
import win32clipboard
import cv2
import numpy as np
from PIL import Image

# 支持相对导入（作为模块）和绝对导入（直接运行）
try:
    from .screen import get_wechat_hwnd, get_window_client_bbox, window_to_screen_coords, WindowNotFoundError, save_screenshot, capture_window
    from .config import WeChatAutomationConfig
    from .locator import put_chinese_text
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from screen import get_wechat_hwnd, get_window_client_bbox, window_to_screen_coords, WindowNotFoundError, save_screenshot, capture_window
    from config import WeChatAutomationConfig
    from locator import put_chinese_text

logger = logging.getLogger(__name__)

# 禁用 pyautogui 的安全检查（在受控环境中使用）
pyautogui.FAILSAFE = False


class ActionError(Exception):
    """操作错误异常"""
    pass


# 缓存窗口句柄，避免重复查找
_cached_hwnd = None


def _get_hwnd() -> int:
    """获取窗口句柄（带缓存）"""
    global _cached_hwnd
    if _cached_hwnd is None or not win32gui.IsWindow(_cached_hwnd):
        _cached_hwnd = get_wechat_hwnd()
    return _cached_hwnd


def ensure_wechat_foreground(hwnd: Optional[int] = None) -> bool:
    """
    确保微信窗口在前台（严格验证）
    
    每次关键操作前都应该调用此函数，确保快捷键不会被发送到其他窗口
    
    Args:
        hwnd: 窗口句柄，None则自动查找
    
    Returns:
        是否成功
    
    Raises:
        WindowNotFoundError: 窗口未找到
        ActionError: 激活失败
    """
    try:
        global _cached_hwnd
        
        if hwnd is None:
            _cached_hwnd = None
            hwnd = _get_hwnd()
        
        # 检查窗口是否存在且有效
        if not win32gui.IsWindow(hwnd):
            logger.warning(f"窗口句柄无效: {hwnd}，尝试重新获取")
            _cached_hwnd = None
            try:
                hwnd = get_wechat_hwnd()
                logger.debug(f"重新获取到窗口句柄: {hwnd}")
            except Exception as e:
                raise WindowNotFoundError(f"重新获取窗口句柄失败: {str(e)}")
        
        if not win32gui.IsWindow(hwnd):
            raise WindowNotFoundError(f"窗口句柄无效: {hwnd}")
        
        # 如果窗口已最小化，先恢复
        if win32gui.IsIconic(hwnd):
            logger.debug("窗口已最小化，正在恢复...")
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            time.sleep(0.2)
        
        # 激活窗口
        try:
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
        except Exception as e:
            # 某些情况下 SetForegroundWindow 可能失败（Windows安全限制），但不影响后续操作
            logger.debug(f"SetForegroundWindow 失败: {e}，尝试备用方法")
        
        # 等待窗口激活
        time.sleep(0.1)
        
        # 严格验证：当前前台窗口必须是微信
        current_hwnd = win32gui.GetForegroundWindow()
        current_title = win32gui.GetWindowText(current_hwnd)
        
        logger.debug(f"当前前台窗口: hwnd={current_hwnd}, 标题='{current_title}'")
        
        if current_hwnd != hwnd:
            # 如果直接激活失败，尝试点击标题栏
            try:
                window_rect = win32gui.GetWindowRect(hwnd)
                if window_rect:
                    title_bar_y = window_rect[1] + 10
                    title_bar_x = window_rect[0] + (window_rect[2] - window_rect[0]) // 2
                    
                    pyautogui.click(title_bar_x, title_bar_y)
                    time.sleep(0.2)
                    
                    try:
                        win32gui.SetForegroundWindow(hwnd)
                    except:
                        pass
                    
                    time.sleep(0.1)
                    current_hwnd = win32gui.GetForegroundWindow()
                    current_title = win32gui.GetWindowText(current_hwnd)
                    logger.debug(f"点击标题栏后，当前前台窗口: hwnd={current_hwnd}, 标题='{current_title}'")
            except Exception as e:
                logger.warning(f"点击标题栏激活窗口失败: {e}")
        
        # 最终验证：如果仍然不是微信窗口，抛出异常
        if current_hwnd != hwnd:
            target_title = win32gui.GetWindowText(hwnd)
            error_msg = (
                f"微信窗口未在前台！"
                f"目标窗口: hwnd={hwnd}, 标题='{target_title}'; "
                f"当前前台窗口: hwnd={current_hwnd}, 标题='{current_title}'"
            )
            logger.error(error_msg)
            raise ActionError(error_msg)
        
        logger.debug(f"✓ 微信窗口已在前台: '{current_title}'")
        return True
    
    except WindowNotFoundError:
        raise
    except ActionError:
        raise
    except Exception as e:
        error_msg = f"确保微信窗口在前台失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


def activate_window(hwnd: Optional[int] = None) -> bool:
    """
    激活微信窗口，将其置前
    
    Args:
        hwnd: 窗口句柄，None则自动查找
    
    Returns:
        是否成功
    
    Raises:
        WindowNotFoundError: 窗口未找到
        ActionError: 激活失败
    """
    try:
        global _cached_hwnd
        
        if hwnd is None:
            # 清除缓存，强制重新获取
            _cached_hwnd = None
            hwnd = _get_hwnd()
        
        # 严格验证句柄有效性（在调用 SetForegroundWindow 之前）
        if not isinstance(hwnd, int) or not win32gui.IsWindow(hwnd):
            logger.warning(f"窗口句柄无效: {hwnd} (类型: {type(hwnd)})，尝试重新获取")
            # 清除缓存并重新获取
            _cached_hwnd = None
            try:
                hwnd = get_wechat_hwnd()
                logger.debug(f"重新获取到窗口句柄: {hwnd}")
            except Exception as e:
                raise WindowNotFoundError(f"重新获取窗口句柄失败: {str(e)}")
        
        # 再次验证句柄有效性
        if not isinstance(hwnd, int) or not win32gui.IsWindow(hwnd):
            raise WindowNotFoundError(f"窗口句柄无效: {hwnd}")
        
        # 如果窗口已最小化，先恢复
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            human_delay(0.2, 0.3)
        
        # 尝试激活窗口（可能因为Windows安全限制而失败）
        try:
            win32gui.SetForegroundWindow(hwnd)
            win32gui.BringWindowToTop(hwnd)
        except Exception as e:
            # 某些情况下 SetForegroundWindow 可能失败（Windows安全限制），但不影响后续操作
            logger.debug(f"SetForegroundWindow 失败: {e}，尝试备用方法")
            # 如果 SetForegroundWindow 失败，尝试其他方法
        
        # 验证窗口是否在前台
        time.sleep(0.1)
        current_hwnd = win32gui.GetForegroundWindow()
        
        if current_hwnd != hwnd:
            # 如果直接激活失败，尝试点击标题栏
            try:
                window_rect = win32gui.GetWindowRect(hwnd)
                if window_rect:
                    title_bar_y = window_rect[1] + 10  # 标题栏中间位置
                    title_bar_x = window_rect[0] + (window_rect[2] - window_rect[0]) // 2
                    
                    # 点击标题栏
                    pyautogui.click(title_bar_x, title_bar_y)
                    human_delay(0.1, 0.2)
                    
                    # 再次尝试激活
                    try:
                        win32gui.SetForegroundWindow(hwnd)
                    except:
                        pass  # 忽略错误，继续验证
                    
                    time.sleep(0.1)
                    current_hwnd = win32gui.GetForegroundWindow()
            except Exception as e:
                logger.warning(f"点击标题栏激活窗口失败: {e}")
        
        # 如果仍然失败，尝试使用 ShowWindow
        if current_hwnd != hwnd:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.1)
                current_hwnd = win32gui.GetForegroundWindow()
            except Exception as e:
                logger.warning(f"ShowWindow 激活失败: {e}")
        
        if current_hwnd == hwnd:
            logger.debug(f"窗口激活成功: {hwnd}")
            return True
        else:
            # 即使激活失败，如果窗口可见，也允许继续（某些情况下Windows会阻止SetForegroundWindow）
            if win32gui.IsWindowVisible(hwnd):
                logger.warning(f"窗口激活验证失败，但窗口可见，允许继续。当前前台窗口: {current_hwnd}, 目标窗口: {hwnd}")
                return True
            else:
                raise ActionError(f"窗口激活失败，当前前台窗口: {current_hwnd}, 目标窗口: {hwnd}")
    
    except WindowNotFoundError:
        raise
    except Exception as e:
        error_msg = f"激活窗口失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


def click(x: int, y: int, hwnd: Optional[int] = None, delay: Optional[float] = None) -> bool:
    """
    点击指定坐标（支持相对窗口坐标）
    
    Args:
        x, y: 点击坐标（窗口内相对坐标）
        hwnd: 窗口句柄，None则自动查找
        delay: 点击后延迟（秒），None则使用人类化延迟
    
    Returns:
        是否成功
    
    Raises:
        WindowNotFoundError: 窗口未找到
        ActionError: 点击失败
    """
    try:
        if hwnd is None:
            hwnd = _get_hwnd()
        
        # 确保窗口在前台（严格验证）
        ensure_wechat_foreground(hwnd)
        
        # 将窗口相对坐标转换为屏幕绝对坐标
        screen_x, screen_y = window_to_screen_coords(hwnd, x, y)
        
        # 执行点击
        pyautogui.click(screen_x, screen_y)
        
        # 延迟
        if delay is None:
            human_delay()
        else:
            time.sleep(delay)
        
        logger.debug(f"点击成功: 窗口坐标({x}, {y}) -> 屏幕坐标({screen_x}, {screen_y})")
        return True
    
    except WindowNotFoundError:
        raise
    except Exception as e:
        error_msg = f"点击失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


def hotkey(*keys, hwnd: Optional[int] = None, delay: Optional[float] = None) -> bool:
    """
    快捷键操作
    
    支持组合键，例如：
    - hotkey('ctrl', 'f')  # Ctrl+F
    - hotkey('ctrl', 'a')  # Ctrl+A
    - hotkey('ctrl', 'v')  # Ctrl+V
    - hotkey('enter')      # Enter
    - hotkey('esc')        # Esc
    
    Args:
        *keys: 按键序列，如 ('ctrl', 'f') 或 ('enter',)
        hwnd: 窗口句柄，None则自动查找
        delay: 按键后延迟（秒），None则使用人类化延迟
    
    Returns:
        是否成功
    
    Raises:
        WindowNotFoundError: 窗口未找到
        ActionError: 按键失败
    """
    try:
        if hwnd is None:
            hwnd = _get_hwnd()
        
        # 确保窗口在前台（严格验证，每次快捷键前都检查）
        ensure_wechat_foreground(hwnd)
        
        # 执行快捷键
        pyautogui.hotkey(*keys)
        
        # 延迟
        if delay is None:
            human_delay()
        else:
            time.sleep(delay)
        
        keys_str = '+'.join(keys)
        logger.debug(f"快捷键成功: {keys_str}")
        return True
    
    except WindowNotFoundError:
        raise
    except Exception as e:
        error_msg = f"快捷键失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


def paste_text(text: str, hwnd: Optional[int] = None, delay: Optional[float] = None) -> bool:
    """
    通过剪贴板粘贴文本（推荐方式，避免输入法干扰）
    
    Args:
        text: 要粘贴的文本
        hwnd: 窗口句柄，None则自动查找
        delay: 粘贴后延迟（秒），None则使用人类化延迟
    
    Returns:
        是否成功
    
    Raises:
        WindowNotFoundError: 窗口未找到
        ActionError: 粘贴失败
    """
    try:
        if hwnd is None:
            hwnd = _get_hwnd()
        
        # 确保窗口在前台（严格验证）
        ensure_wechat_foreground(hwnd)
        
        # 复制到剪贴板
        pyperclip.copy(text)
        human_delay(0.05, 0.1)  # 等待剪贴板更新
        
        # 粘贴（粘贴前再次确保窗口在前台，因为剪贴板操作可能切换窗口）
        ensure_wechat_foreground(hwnd)
        pyautogui.hotkey('ctrl', 'v')
        
        # 延迟
        if delay is None:
            human_delay()
        else:
            time.sleep(delay)
        
        logger.debug(f"粘贴文本成功: {text[:20]}...")
        return True
    
    except WindowNotFoundError:
        raise
    except Exception as e:
        error_msg = f"粘贴文本失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


def type_text(text: str, hwnd: Optional[int] = None, delay: Optional[float] = None) -> bool:
    """
    模拟打字输入文本（可选，仅当确实需要时使用）
    
    注意：此方法可能受输入法影响，优先使用 paste_text()
    
    Args:
        text: 要输入的文本
        hwnd: 窗口句柄，None则自动查找
        delay: 输入后延迟（秒），None则使用人类化延迟
    
    Returns:
        是否成功
    
    Raises:
        WindowNotFoundError: 窗口未找到
        ActionError: 输入失败
    """
    try:
        if hwnd is None:
            hwnd = _get_hwnd()
        
        # 确保窗口在前台（严格验证）
        ensure_wechat_foreground(hwnd)
        
        # 模拟打字（每个字符之间添加小延迟）
        pyautogui.write(text, interval=random.uniform(0.05, 0.15))
        
        # 延迟
        if delay is None:
            human_delay()
        else:
            time.sleep(delay)
        
        logger.debug(f"输入文本成功: {text[:20]}...")
        return True
    
    except WindowNotFoundError:
        raise
    except Exception as e:
        error_msg = f"输入文本失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


def human_delay(min_seconds: Optional[float] = None, max_seconds: Optional[float] = None) -> None:
    """
    人类化延迟策略（随机延迟，使操作更自然）
    
    默认延迟范围根据配置：
    - 点击后: 0.1-0.2秒
    - 输入后: 0.2-0.3秒
    - 滚动后: 0.3-0.5秒
    
    Args:
        min_seconds: 最小延迟（秒），None则使用配置默认值
        max_seconds: 最大延迟（秒），None则使用配置默认值
    """
    if min_seconds is None:
        min_seconds = WeChatAutomationConfig.CLICK_DELAY
    if max_seconds is None:
        max_seconds = min_seconds * 2
    
    delay = random.uniform(min_seconds, max_seconds)
    time.sleep(delay)


def wait(seconds: float) -> None:
    """
    等待指定时间（固定延迟）
    
    Args:
        seconds: 等待时间（秒）
    """
    time.sleep(seconds)


def copy_text_at(x: int, y: int, hwnd: Optional[int] = None, double_click: bool = True, timeout: float = 2.0, max_retries: int = 2) -> Optional[str]:
    """
    在指定坐标双击后复制文本（Ctrl+C），然后从剪贴板读取（带剪贴板一致性校验）
    
    流程（事务式）：
    1. 读取当前剪贴板内容 before
    2. 确保窗口在前台
    3. 双击气泡（微信默认单击不能选中全部，直接双击）
    4. 按 Ctrl+C 复制
    5. 等待 50~200ms 读取剪贴板 after
    6. 若 after == before 或 after 为空：重试（最多 max_retries 次）
    7. 仍为空：返回失败并保存 debug 截图
    
    Args:
        x, y: 点击坐标（窗口内相对坐标）
        hwnd: 窗口句柄，None则自动查找
        double_click: 是否双击（默认True，直接使用双击）
        timeout: 超时时间（秒，暂未使用）
        max_retries: 最大重试次数（默认2次）
    
    Returns:
        剪贴板文本内容，失败返回None
    
    Raises:
        WindowNotFoundError: 窗口未找到
        ActionError: 操作失败
    """
    import pyperclip
    try:
        from .screen import save_screenshot, capture_window
    except ImportError:
        import sys
        from pathlib import Path
        _dir = Path(__file__).resolve().parent
        if str(_dir) not in sys.path:
            sys.path.insert(0, str(_dir))
        from screen import save_screenshot, capture_window
    
    try:
        if hwnd is None:
            hwnd = _get_hwnd()
        
        # 确保窗口在前台（严格验证）
        ensure_wechat_foreground(hwnd)
        
        # 将窗口相对坐标转换为屏幕绝对坐标
        screen_x, screen_y = window_to_screen_coords(hwnd, x, y)
        
        # 读取复制前的剪贴板内容
        clipboard_before = pyperclip.paste()
        logger.debug(f"复制前剪贴板内容: {clipboard_before[:50] if clipboard_before else '(空)'}...")
        
        # 重试循环
        for attempt in range(max_retries + 1):
            try:
                # 直接使用双击（微信默认单击不能选中全部）
                if double_click:
                    pyautogui.doubleClick(screen_x, screen_y)
                    logger.debug(f"尝试 {attempt+1}/{max_retries+1}: 双击 窗口坐标({x}, {y}) -> 屏幕坐标({screen_x}, {screen_y})")
                else:
                    pyautogui.click(screen_x, screen_y)
                    logger.debug(f"尝试 {attempt+1}/{max_retries+1}: 单击 窗口坐标({x}, {y}) -> 屏幕坐标({screen_x}, {screen_y})")
                
                human_delay(0.1, 0.15)  # 等待点击生效
                
                # 按 Ctrl+C 复制
                pyautogui.hotkey('ctrl', 'c')
                
                # 等待复制完成（50~200ms）
                import random
                wait_time = random.uniform(0.05, 0.2)
                time.sleep(wait_time)
                
                # 读取复制后的剪贴板内容
                clipboard_after = pyperclip.paste()
                
                # 验证剪贴板是否变化且不为空
                if clipboard_after and clipboard_after.strip():
                    # 检查是否与复制前相同（可能是重复复制或没点中）
                    if clipboard_after.strip() == clipboard_before.strip():
                        logger.debug(f"剪贴板内容未变化（可能是重复复制），重试...")
                        if attempt < max_retries:
                            continue
                        else:
                            logger.warning(f"剪贴板内容未变化，可能未点中气泡或重复复制")
                            # 保存标注了点击位置的调试截图
                            try:
                                debug_screenshot = capture_window(hwnd)
                                # 标注点击位置（红色十字）
                                cv2.circle(debug_screenshot, (x, y), 15, (0, 0, 255), 2)
                                cv2.line(debug_screenshot, (x - 20, y), (x + 20, y), (0, 0, 255), 2)
                                cv2.line(debug_screenshot, (x, y - 20), (x, y + 20), (0, 0, 255), 2)
                                debug_screenshot = put_chinese_text(debug_screenshot, f"点击位置({x}, {y})", (x + 25, y - 10), 
                                           font_size=16, color=(0, 0, 255))
                                save_screenshot(
                                    debug_screenshot,
                                    "copy_text_clipboard_unchanged",
                                    task_id="copy_text",
                                    step_name="copy_failed",
                                    error_info=f"剪贴板未变化，位置=({x}, {y})"
                                )
                            except:
                                pass
                            return None
                    else:
                        # 剪贴板内容已变化且不为空，复制成功
                        text = clipboard_after.strip()
                        logger.debug(f"复制文本成功: {text[:50]}...")
                        return text
                else:
                    # 剪贴板为空
                    logger.debug(f"剪贴板为空，重试...")
                    if attempt < max_retries:
                        continue
                    else:
                        logger.warning(f"剪贴板文本为空，可能不是文本消息（图片/表情等）或未点中")
                        # 保存标注了点击位置的调试截图
                        try:
                            debug_screenshot = capture_window(hwnd)
                            # 标注点击位置（红色十字）
                            cv2.circle(debug_screenshot, (x, y), 15, (0, 0, 255), 2)
                            cv2.line(debug_screenshot, (x - 20, y), (x + 20, y), (0, 0, 255), 2)
                            cv2.line(debug_screenshot, (x, y - 20), (x, y + 20), (0, 0, 255), 2)
                            debug_screenshot = put_chinese_text(debug_screenshot, f"点击位置({x}, {y})", (x + 25, y - 10), 
                                           font_size=16, color=(0, 0, 255))
                            save_screenshot(
                                debug_screenshot,
                                "copy_text_clipboard_empty",
                                task_id="copy_text",
                                step_name="copy_failed",
                                error_info=f"剪贴板为空，位置=({x}, {y})"
                            )
                        except:
                            pass
                        return None
                        
            except Exception as e:
                logger.warning(f"复制尝试 {attempt+1} 失败: {e}")
                if attempt < max_retries:
                    continue
                else:
                    raise
        
        # 所有重试都失败
        return None
        
    except WindowNotFoundError:
        raise
    except Exception as e:
        error_msg = f"复制文本失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


def scroll(direction: str, amount: int = 3, hwnd: Optional[int] = None, delay: Optional[float] = None) -> bool:
    """
    滚动操作
    
    Args:
        direction: 滚动方向（'up'/'down'）
        amount: 滚动量（滚轮单位，默认3）
        hwnd: 窗口句柄，None则自动查找
        delay: 滚动后延迟（秒），None则使用人类化延迟
    
    Returns:
        是否成功
    
    Raises:
        WindowNotFoundError: 窗口未找到
        ActionError: 滚动失败
    """
    try:
        if hwnd is None:
            hwnd = _get_hwnd()
        
        # 确保窗口在前台（严格验证）
        ensure_wechat_foreground(hwnd)
        
        # 获取窗口中心位置
        left, top, width, height = get_window_client_bbox(hwnd)
        center_x = left + width // 2
        center_y = top + height // 2
        
        # 执行滚动
        if direction.lower() == 'up':
            pyautogui.scroll(amount, x=center_x, y=center_y)
        elif direction.lower() == 'down':
            pyautogui.scroll(-amount, x=center_x, y=center_y)
        else:
            raise ActionError(f"无效的滚动方向: {direction}，应为 'up' 或 'down'")
        
        # 延迟
        if delay is None:
            human_delay(WeChatAutomationConfig.SCROLL_DELAY, WeChatAutomationConfig.SCROLL_DELAY * 1.5)
        else:
            time.sleep(delay)
        
        logger.debug(f"滚动成功: {direction} {amount}单位")
        return True
    except WindowNotFoundError:
        raise
    except Exception as e:
        error_msg = f"滚动失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


def scroll_at(
    x: int,
    y: int,
    direction: str,
    amount: int = 3,
    delay: Optional[float] = None,
) -> bool:
    """
    在指定屏幕坐标 (x, y) 处执行滚轮滚动。
    用于「判断是否已到底部」等需要固定滚动位置的操作。

    Args:
        x: 屏幕横坐标（滚轮作用点）
        y: 屏幕纵坐标（滚轮作用点）
        direction: 滚动方向（'up'/'down'）
        amount: 滚轮单位数
        delay: 滚动后延迟（秒），None 则使用人类化延迟

    Returns:
        是否成功
    """
    try:
        if direction.lower() == "up":
            pyautogui.scroll(amount, x=x, y=y)
        elif direction.lower() == "down":
            pyautogui.scroll(-amount, x=x, y=y)
        else:
            raise ActionError(f"无效的滚动方向: {direction}，应为 'up' 或 'down'")
        if delay is None:
            human_delay(WeChatAutomationConfig.SCROLL_DELAY, WeChatAutomationConfig.SCROLL_DELAY * 1.5)
        else:
            time.sleep(delay)
        return True
    except Exception as e:
        logger.error("scroll_at 失败: %s", e)
        raise ActionError(str(e))


def scroll_chat_area_up(
    hwnd: int,
    roi: tuple[int, int, int, int],
    steps: int = 5,
    step_amount: int = 120,
    delay_range: tuple[float, float] = (0.05, 0.1),
    save_debug: bool = True,
) -> None:
    """
    在消息区域内滚轮向上滚动。

    Args:
        hwnd: 窗口句柄
        roi: 消息区域 (x, y, w, h) 相对窗口坐标
        steps: 滚轮次数
        step_amount: 每次滚轮的幅度（正数=向上）
        delay_range: 每次滚动后的随机等待区间 (min, max)
        save_debug: 是否保存标注调试图片（默认True）
    """
    try:
        from .screen import capture_window, save_screenshot
    except ImportError:
        import sys
        from pathlib import Path
        _dir = Path(__file__).resolve().parent
        if str(_dir) not in sys.path:
            sys.path.insert(0, str(_dir))
        from screen import capture_window, save_screenshot
    
    try:
        ensure_wechat_foreground(hwnd)
        # 使用 ROI 中心点作为滚动位置，确保滚动的是消息区域而不是列表/窗口
        x, y, w, h = roi
        center_x = x + w // 2
        center_y = y + h // 2
        screen_x, screen_y = window_to_screen_coords(hwnd, center_x, center_y)
        
        # 保存标注了滚动位置和ROI的调试图片
        if save_debug:
            try:
                debug_screenshot = capture_window(hwnd)
                # 标注ROI区域（蓝色矩形）
                cv2.rectangle(debug_screenshot, (x, y), (x + w, y + h), (255, 0, 0), 2)
                cv2.putText(debug_screenshot, "ROI", (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 0, 0), 2)
                
                # 标注滚动焦点位置（黄色圆圈和十字）
                cv2.circle(debug_screenshot, (center_x, center_y), 20, (0, 255, 255), 2)
                cv2.line(debug_screenshot, (center_x - 30, center_y), (center_x + 30, center_y), (0, 255, 255), 2)
                cv2.line(debug_screenshot, (center_x, center_y - 30), (center_x, center_y + 30), (0, 255, 255), 2)
                debug_screenshot = put_chinese_text(debug_screenshot, f"滚动焦点({center_x}, {center_y})", (center_x + 35, center_y - 10), 
                           font_size=16, color=(0, 255, 255))
                debug_screenshot = put_chinese_text(debug_screenshot, f"方向: {'向上' if step_amount > 0 else '向下'} x{steps}", 
                           (center_x + 35, center_y + 10), font_size=16, color=(0, 255, 255))
                
                save_screenshot(
                    debug_screenshot,
                    "scroll_chat_area_debug",
                    task_id="scroll",
                    step_name="scroll_position",
                    error_info=f"方向={'向上' if step_amount > 0 else '向下'}, 步数={steps}, 焦点=({center_x}, {center_y})"
                )
                logger.debug("已保存标注调试图片：蓝色矩形=ROI，黄色十字=滚动焦点")
            except Exception as e:
                logger.debug(f"保存滚动调试图片失败: {e}")
        
        pyautogui.moveTo(screen_x, screen_y)
        for _ in range(max(1, steps)):
            pyautogui.scroll(step_amount)
            # 人类化延迟
            wait_time = random.uniform(delay_range[0], delay_range[1])
            time.sleep(wait_time)
    except WindowNotFoundError:
        raise
    except Exception as e:
        error_msg = f"滚动失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


def copy_image_to_clipboard(image_path: str) -> bool:
    """
    将图片文件复制到剪贴板（使用 win32clipboard）
    
    使用 CF_DIB 格式（Device Independent Bitmap），将图片转换为 BMP 格式
    并去除文件头（14字节）后写入剪贴板。
    
    Args:
        image_path: 图片文件路径
    
    Returns:
        是否成功
    
    Raises:
        ActionError: 操作失败（文件不存在、格式不支持等）
    """
    try:
        image_path_obj = Path(image_path)
        if not image_path_obj.exists():
            raise ActionError(f"图片文件不存在: {image_path}")
        
        # 使用 PIL 打开图片
        try:
            image = Image.open(image_path)
        except Exception as e:
            raise ActionError(f"无法打开图片文件: {image_path}, 错误: {e}")
        
        # 转换为 RGB 格式（确保兼容性）
        if image.mode != "RGB":
            image = image.convert("RGB")
        
        # 保存为 BMP 格式到内存
        output = BytesIO()
        image.save(output, "BMP")
        data = output.getvalue()
        output.close()
        
        # 去除 BMP 文件头（14字节），只保留 DIB 数据
        if len(data) < 14:
            raise ActionError(f"BMP 数据无效: {image_path}")
        dib_data = data[14:]
        
        # 写入剪贴板
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32clipboard.CF_DIB, dib_data)
            win32clipboard.CloseClipboard()
            logger.debug(f"图片已复制到剪贴板: {image_path}")
            return True
        except Exception as e:
            try:
                win32clipboard.CloseClipboard()
            except:
                pass
            raise ActionError(f"写入剪贴板失败: {e}")
    
    except ActionError:
        raise
    except Exception as e:
        error_msg = f"复制图片到剪贴板失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


# 图片扩展名（用于判断是否走 CF_DIB 路径）
_IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff", ".tif"})


def _is_image_path(path: str) -> bool:
    """根据扩展名判断是否为图片文件"""
    ext = Path(path).suffix.lower()
    return ext in _IMAGE_EXTENSIONS


def copy_file_to_clipboard(file_path: str) -> bool:
    """
    将文件路径复制到剪贴板（使用 CF_HDROP）
    
    适用于非图片文件（.pdf、.docx、.md 等），粘贴时作为文件发送。
    图片请使用 copy_image_to_clipboard。
    
    Args:
        file_path: 文件路径
    
    Returns:
        是否成功
    """
    try:
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise ActionError(f"文件不存在: {file_path}")
        abs_path = str(file_path_obj.resolve())
        
        # 构造 CF_HDROP 格式：DROPFILES 头 + 以双 \0 结尾的 Unicode 路径
        import ctypes
        from ctypes import wintypes

        GMEM_MOVEABLE = 0x0002
        CF_HDROP = 15

        # DROPFILES: pFiles(4) + pt(8) + fNC(4) + fWide(4) = 20 bytes
        # pFiles = 20 表示文件列表从结构体后开始，fWide = 1 表示 Unicode
        dropfiles_header = (
            (20).to_bytes(4, "little")  # pFiles
            + (0).to_bytes(8, "little")  # pt
            + (0).to_bytes(4, "little")  # fNC
            + (1).to_bytes(4, "little")  # fWide
        )
        path_bytes = (abs_path + "\0\0").encode("utf-16-le")
        data = dropfiles_header + path_bytes

        kernel32 = ctypes.windll.kernel32
        # 64 位 Windows 下必须显式声明类型，否则句柄/指针截断或 OverflowError
        kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
        kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
        kernel32.GlobalLock.restype = ctypes.c_void_p
        kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalUnlock.restype = wintypes.BOOL
        kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
        kernel32.GlobalFree.restype = wintypes.HGLOBAL

        size = len(data)
        h_global = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h_global:
            raise ActionError("GlobalAlloc 失败")
        ptr = kernel32.GlobalLock(h_global)
        if not ptr:
            raise ActionError("GlobalLock 失败")
        try:
            ctypes.memmove(ptr, data, size)
        finally:
            kernel32.GlobalUnlock(h_global)
        
        try:
            win32clipboard.OpenClipboard()
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(CF_HDROP, h_global)
            win32clipboard.CloseClipboard()
            logger.debug(f"文件已复制到剪贴板(CF_HDROP): {file_path}")
            return True
        except Exception as e:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass
            kernel32.GlobalFree(h_global)
            raise ActionError(f"写入剪贴板失败: {e}")
    except ActionError:
        raise
    except Exception as e:
        logger.error("复制文件到剪贴板失败: %s", e)
        raise ActionError(f"复制文件到剪贴板失败: {e}")


def copy_file_or_image_to_clipboard(file_path: str) -> bool:
    """
    根据文件类型将文件/图片复制到剪贴板
    - 图片：使用 CF_DIB
    - 其他文件：使用 CF_HDROP
    """
    if _is_image_path(file_path):
        return copy_image_to_clipboard(file_path)
    return copy_file_to_clipboard(file_path)


def paste_file_or_image(hwnd: Optional[int] = None, delay: Optional[float] = None) -> bool:
    """
    粘贴剪贴板中的文件或图片（Ctrl+V）
    与 paste_image 相同，用于统一文件/图片发送流程。
    """
    return paste_image(hwnd=hwnd, delay=delay)


def paste_image(hwnd: Optional[int] = None, delay: Optional[float] = None) -> bool:
    """
    粘贴图片（Ctrl+V）
    
    确保窗口在前台后执行 Ctrl+V 粘贴剪贴板中的图片。
    
    Args:
        hwnd: 窗口句柄，None则自动查找
        delay: 粘贴后延迟（秒），None则使用人类化延迟
    
    Returns:
        是否成功
    
    Raises:
        WindowNotFoundError: 窗口未找到
        ActionError: 粘贴失败
    """
    try:
        if hwnd is None:
            hwnd = _get_hwnd()
        
        # 确保窗口在前台（严格验证）
        ensure_wechat_foreground(hwnd)
        
        # 执行 Ctrl+V 粘贴
        pyautogui.hotkey('ctrl', 'v')
        
        # 延迟（等待图片加载）
        if delay is None:
            human_delay(0.5, 1.0)  # 图片加载需要更长时间
        else:
            time.sleep(delay)
        
        logger.debug("粘贴图片成功")
        return True
    
    except WindowNotFoundError:
        raise
    except Exception as e:
        error_msg = f"粘贴图片失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)


def select_file_via_dialog(file_path: str, timeout: float = 5.0) -> bool:
    """
    通过 Windows API 操作文件选择对话框选择文件
    
    查找文件选择对话框窗口，在文件名输入框中输入完整路径，
    然后点击"打开"按钮或按 Enter。
    若无法定位到输入框，则使用剪贴板粘贴路径 + Enter 作为回退。
    
    Args:
        file_path: 文件完整路径
        timeout: 超时时间（秒）
    
    Returns:
        是否成功
    
    Raises:
        ActionError: 操作失败（对话框未找到、文件不存在等）
    """
    try:
        file_path_obj = Path(file_path)
        if not file_path_obj.exists():
            raise ActionError(f"文件不存在: {file_path}")
        
        # 转换为绝对路径
        abs_path = str(file_path_obj.resolve())
        
        # 查找文件选择对话框窗口
        # 常见的对话框标题：打开、选择文件、选择要上传的文件等
        dialog_titles = ["打开", "选择文件", "选择要上传的文件", "Open", "Select File"]
        dialog_hwnd = None
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            for title in dialog_titles:
                hwnd = win32gui.FindWindow(None, title)
                if hwnd:
                    dialog_hwnd = hwnd
                    logger.debug(f"找到文件选择对话框: {title}")
                    break
            if dialog_hwnd:
                break
            time.sleep(0.2)
        
        if not dialog_hwnd:
            raise ActionError(f"未找到文件选择对话框（超时 {timeout} 秒）")
        
        # 激活对话框窗口（必须，确保后续按键发到对话框）
        try:
            win32gui.SetForegroundWindow(dialog_hwnd)
            time.sleep(0.3)
        except Exception as e:
            logger.warning(f"激活对话框窗口失败: {e}")
        
        # 查找文件名输入框：Edit 或 ComboBox 内的 Edit
        edit_hwnd = None
        common_edit_ids = [0x047c, 0x046c, 0x0000]
        
        for edit_id in common_edit_ids:
            try:
                ctrl_hwnd = win32gui.GetDlgItem(dialog_hwnd, edit_id)
                if not ctrl_hwnd:
                    continue
                class_name = win32gui.GetClassName(ctrl_hwnd)
                if class_name == "Edit":
                    try:
                        win32gui.SendMessage(ctrl_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)
                    except Exception:
                        continue
                    edit_hwnd = ctrl_hwnd
                    logger.debug(f"找到文件名输入框(Edit)，ID: {hex(edit_id)}")
                    break
                if class_name == "ComboBox":
                    # ComboBox 的编辑区需通过 GetComboBoxInfo 获取
                    try:
                        import ctypes
                        from ctypes import wintypes
                        CB_GETCOMBOBOXINFO = 0x0164
                        class COMBOBOXINFO(ctypes.Structure):
                            _fields_ = [
                                ("cbSize", wintypes.DWORD),
                                ("rcItem", wintypes.RECT),
                                ("rcButton", wintypes.RECT),
                                ("stateButton", wintypes.DWORD),
                                ("hwndCombo", wintypes.HWND),
                                ("hwndItem", wintypes.HWND),
                                ("hwndList", wintypes.HWND),
                            ]
                        cbi = COMBOBOXINFO()
                        cbi.cbSize = ctypes.sizeof(COMBOBOXINFO)
                        if ctypes.windll.user32.GetComboBoxInfo(ctrl_hwnd, ctypes.byref(cbi)):
                            edit_hwnd = cbi.hwndItem
                            if edit_hwnd:
                                logger.debug(f"找到文件名输入框(ComboBox子Edit)，ID: {hex(edit_id)}")
                                break
                    except Exception:
                        pass
            except Exception:
                continue
        
        # 枚举子窗口查找 Edit
        if not edit_hwnd:
            found_edits = []

            def enum_child_proc(hwnd, lParam):
                class_name = win32gui.GetClassName(hwnd)
                if class_name == "Edit":
                    found_edits.append(hwnd)
                return True

            try:
                win32gui.EnumChildWindows(dialog_hwnd, enum_child_proc, None)
                if found_edits:
                    # 取第一个或最后一个 Edit（文件名栏多为最后一个）
                    edit_hwnd = found_edits[-1]
                    logger.debug("通过枚举找到 Edit 控件")
            except Exception:
                pass
        
        if edit_hwnd:
            # 通过控件设置路径
            try:
                win32gui.SetForegroundWindow(dialog_hwnd)
                time.sleep(0.1)
                win32gui.SendMessage(edit_hwnd, win32con.WM_SETTEXT, 0, abs_path)
                time.sleep(0.2)
                logger.debug(f"已输入文件路径(控件): {abs_path[:60]}...")
            except Exception as e:
                logger.warning(f"控件输入路径失败: {e}，尝试剪贴板粘贴")
                edit_hwnd = None
        
        if not edit_hwnd:
            # 回退：剪贴板粘贴路径 + Enter（多数文件对话框打开时焦点在文件名栏）
            logger.debug("使用剪贴板粘贴路径并回车")
            try:
                win32gui.SetForegroundWindow(dialog_hwnd)
                time.sleep(0.2)
                pyperclip.copy(abs_path)
                time.sleep(0.1)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(0.3)
                pyautogui.press("enter")
                logger.debug("已粘贴路径并按 Enter")
                time.sleep(0.5)
                return True
            except Exception as e:
                raise ActionError(f"剪贴板粘贴路径失败: {e}")
        
        # 按 Enter 确认
        try:
            win32gui.SetForegroundWindow(dialog_hwnd)
            win32gui.SendMessage(dialog_hwnd, win32con.WM_KEYDOWN, win32con.VK_RETURN, 0)
            win32gui.SendMessage(dialog_hwnd, win32con.WM_KEYUP, win32con.VK_RETURN, 0)
            logger.debug("已按 Enter 确认选择文件")
            time.sleep(0.5)
            return True
        except Exception as e:
            logger.warning(f"按 Enter 失败: {e}，尝试点击打开按钮")
        
        open_button_hwnd = None
        for btn_id in (0x0001, 0x0002):
            try:
                btn_hwnd = win32gui.GetDlgItem(dialog_hwnd, btn_id)
                if btn_hwnd:
                    text_len = win32gui.SendMessage(btn_hwnd, win32con.WM_GETTEXTLENGTH, 0, 0)
                    if text_len > 0:
                        buffer = win32gui.PyMakeBuffer(text_len + 1)
                        win32gui.SendMessage(btn_hwnd, win32con.WM_GETTEXT, text_len + 1, buffer)
                        btn_text = win32gui.PyGetBuffer(buffer, text_len)
                        if "打开" in btn_text or "Open" in btn_text:
                            open_button_hwnd = btn_hwnd
                            break
            except Exception:
                continue
        
        if open_button_hwnd:
            win32gui.SendMessage(open_button_hwnd, win32con.BM_CLICK, 0, 0)
            time.sleep(0.5)
            return True
        return True  # 已通过控件输入并尝试 Enter，视为完成
    
    except ActionError:
        raise
    except Exception as e:
        error_msg = f"选择文件失败: {str(e)}"
        logger.error(error_msg)
        raise ActionError(error_msg)
