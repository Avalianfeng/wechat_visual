"""屏幕操作模块

提供屏幕截图、裁剪、DPI处理和坐标转换功能。

核心功能：
- get_wechat_hwnd(): 获取微信窗口句柄（可缓存）
- get_window_client_bbox(): 获取窗口客户区在屏幕上的绝对位置
- capture_window(): 截取微信窗口
- crop_region(): 裁剪指定区域
- get_dpi_scale(): 获取系统DPI缩放比例
- normalize_coords(): 坐标归一化处理
- save_screenshot(): 保存调试截图（自动创建目录、时间戳、PNG格式）

注意事项：
1. 所有截图操作应使用窗口句柄，避免截取到其他窗口
2. DPI缩放处理必须准确，否则坐标会偏移
3. 截图格式统一使用PNG，保证无损
4. 大尺寸截图可能较慢，考虑异步或缓存
5. 坐标系统一使用窗口内相对坐标（左上角为原点）

依赖库：
- pywin32: Windows窗口操作
- PIL/Pillow: 图像处理
- numpy: 数组操作
"""

import win32gui
import win32ui
import win32api
import win32con
import win32process
from ctypes import windll
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
import os
import numpy as np
from PIL import Image
import logging
# 支持相对导入（作为模块）和绝对导入（直接运行）
try:
    from .config import WeChatAutomationConfig
except ImportError:
    # 如果相对导入失败，尝试绝对导入（用于直接运行或测试）
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    from config import WeChatAutomationConfig

logger = logging.getLogger(__name__)

# 进程 DPI 感知状态（仅设置一次，确保截图使用物理像素，避免右侧/下侧被裁切）
_capture_dpi_aware_done = False


def _ensure_capture_dpi_aware() -> None:
    """确保截图时进程为 DPI 感知，使 GetClientRect/PrintWindow 使用物理像素，截取完整窗口"""
    global _capture_dpi_aware_done
    if _capture_dpi_aware_done:
        return
    try:
        # Windows 10 1607+：Per-Monitor V2，获得真实物理尺寸
        if hasattr(windll.user32, "SetProcessDpiAwarenessContext"):
            DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            if windll.user32.SetProcessDpiAwarenessContext(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2):
                _capture_dpi_aware_done = True
                logger.debug("截图 DPI 感知: SetProcessDpiAwarenessContext(PER_MONITOR_AWARE_V2)")
                return
        # 回退：系统 DPI 感知
        if hasattr(windll.user32, "SetProcessDPIAware") and windll.user32.SetProcessDPIAware():
            _capture_dpi_aware_done = True
            logger.debug("截图 DPI 感知: SetProcessDPIAware")
    except Exception as e:
        logger.debug(f"设置截图 DPI 感知失败（将使用系统默认）: {e}")
    _capture_dpi_aware_done = True  # 避免重复尝试


class WindowNotFoundError(Exception):
    """窗口未找到异常"""
    pass


class DPIError(Exception):
    """DPI设置错误异常"""
    pass


class ScreenshotError(Exception):
    """截图错误异常"""
    pass


def get_wechat_hwnd(window_title: Optional[str] = None) -> int:
    """
    获取微信窗口句柄（可缓存）
    
    Args:
        window_title: 窗口标题，None则使用配置中的标题
    
    Returns:
        窗口句柄（HWND）
    
    Raises:
        WindowNotFoundError: 窗口未找到
    """
    if window_title is None:
        window_title = WeChatAutomationConfig.WINDOW_TITLE
    
    # 更严格的过滤策略：
    # 1. 只接受标题“完全等于” window_title 的窗口（不再模糊匹配）
    # 2. 且必须属于 Weixin.exe 进程
    def enum_handler(hwnd, ctx):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if title != window_title:
            return
        try:
            _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            if not pid:
                return
            hproc = win32api.OpenProcess(
                win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
                False,
                pid,
            )
            try:
                exe_path = win32process.GetModuleFileNameEx(hproc, 0)
            finally:
                win32api.CloseHandle(hproc)
            exe_name = os.path.basename(exe_path or "").lower()
            if exe_name == "weixin.exe":
                ctx.append(hwnd)
        except Exception as e:
            logger.debug(f"get_wechat_hwnd: 过滤进程名失败（忽略该窗口）: {e}")
    
    windows = []
    win32gui.EnumWindows(enum_handler, windows)
    
    if not windows:
        raise WindowNotFoundError(
            f"未找到标题为 '{window_title}' 且进程为 WeChat.exe 的窗口"
        )
    
    # 理论上只会有一个主窗口，这里保守取第一个
    return windows[0]


def get_window_client_bbox(hwnd: int) -> Tuple[int, int, int, int]:
    """
    获取窗口客户区在屏幕上的绝对位置
    
    Args:
        hwnd: 窗口句柄
    
    Returns:
        (left, top, width, height) - 客户区在屏幕上的绝对位置
    
    Raises:
        WindowNotFoundError: 窗口无效
    """
    if not win32gui.IsWindow(hwnd):
        raise WindowNotFoundError("无效的窗口句柄")
    
    # 获取窗口矩形（包含标题栏和边框）
    window_rect = win32gui.GetWindowRect(hwnd)
    left, top, right, bottom = window_rect
    
    # 获取客户区矩形（不包含标题栏和边框）
    client_rect = win32gui.GetClientRect(hwnd)
    client_left, client_top, client_right, client_bottom = client_rect
    
    # 计算客户区在屏幕上的绝对位置
    # 需要加上窗口边框的偏移
    point = win32gui.ClientToScreen(hwnd, (client_left, client_top))
    screen_left, screen_top = point
    
    width = client_right - client_left
    height = client_bottom - client_top
    
    return (screen_left, screen_top, width, height)


def get_dpi_scale() -> float:
    """
    获取系统 DPI 缩放比例（自适应，不强制 100%）
    
    截图与坐标已通过进程 DPI 感知使用物理像素，任意缩放比例下均可工作。
    
    Returns:
        DPI 缩放百分比（100 表示 100%，125 表示 125%）
    """
    try:
        # 获取主显示器的 DPI 缩放
        hdc = win32gui.GetDC(0)
        try:
            dpi = windll.user32.GetDpiForWindow(win32gui.GetDesktopWindow())
        except Exception as e:
            logger.debug(f"GetDpiForWindow 失败: {e}，尝试备用方法")
            dpi = 0
        finally:
            win32gui.ReleaseDC(0, hdc)
        
        # 96 DPI = 100%，120 = 125%，144 = 150%，192 = 200%
        if dpi == 0:
            try:
                user32 = windll.user32
                user32.SetProcessDPIAware()
                hdc = win32gui.GetDC(0)
                dpi = windll.gdi32.GetDeviceCaps(hdc, 88)  # LOGPIXELSX
                win32gui.ReleaseDC(0, hdc)
            except Exception as e:
                logger.warning(f"获取 DPI 缩放失败，使用默认值 100%: {e}")
                dpi = 96
        
        scale_percent = (dpi / 96.0) * 100
        if abs(scale_percent - 100.0) > 0.1:
            logger.info(f"当前 DPI 缩放: {scale_percent:.1f}%（已自适应，无需改为 100%）")
        return scale_percent
    except Exception as e:
        logger.warning(f"获取 DPI 缩放失败，使用默认值 100%: {e}")
        return 100.0


def capture_window(hwnd: Optional[int] = None, window_title: Optional[str] = None) -> np.ndarray:
    """
    截取指定窗口的屏幕内容
    
    Args:
        hwnd: 窗口句柄，None则自动查找
        window_title: 窗口标题，仅在hwnd为None时使用
    
    Returns:
        截图数组（numpy array，BGR 格式，与 OpenCV 一致，整条链路统一用 BGR）
    
    Raises:
        WindowNotFoundError: 窗口未找到
        ScreenshotError: 截图失败
    """
    try:
        # 确保 DPI 感知，使 GetClientRect/PrintWindow 使用物理像素，截取完整窗口（避免右侧/下侧被裁切）
        _ensure_capture_dpi_aware()

        # 获取窗口句柄
        if hwnd is None:
            hwnd = get_wechat_hwnd(window_title)
        
        # 检查窗口是否最小化，如果是则先恢复
        if win32gui.IsIconic(hwnd):
            logger.warning("窗口已最小化，正在恢复...")
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            import time
            time.sleep(1.0)  # 等待窗口完全重绘，避免截图时内容未刷新导致 OCR 不稳定
        
        # 检查窗口是否可见
        if not win32gui.IsWindowVisible(hwnd):
            raise WindowNotFoundError("窗口不可见，无法截图")
        
        # 获取窗口客户区位置和大小
        left, top, width, height = get_window_client_bbox(hwnd)
        
        # 验证窗口大小是否合理（如果太小可能是窗口未正确恢复）
        if width < 100 or height < 100:
            logger.warning(f"窗口尺寸异常: {width}x{height}，尝试恢复窗口")
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
            import time
            time.sleep(1.0)  # 等待窗口完全重绘
            # 重新获取窗口大小
            left, top, width, height = get_window_client_bbox(hwnd)
            if width < 100 or height < 100:
                raise ScreenshotError(f"窗口尺寸异常: {width}x{height}，请确保窗口已正确打开且可见")
        
        # 创建设备上下文
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        
        # 创建位图
        bitmap = win32ui.CreateBitmap()
        bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
        save_dc.SelectObject(bitmap)
        
        # 复制窗口内容到位图
        result = windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 3)
        
        # 转换为numpy数组
        bmp_info = bitmap.GetInfo()
        bmp_str = bitmap.GetBitmapBits(True)
        
        # 清理资源
        win32gui.DeleteObject(bitmap.GetHandle())
        save_dc.DeleteDC()
        mfc_dc.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwnd_dc)
        
        if result == 0:
            raise ScreenshotError("PrintWindow 失败")
        
        # 转换为PIL Image然后转为numpy数组（Windows 位图为 BGRX，PIL 解析后可能为 RGB）
        img = Image.frombuffer(
            'RGB',
            (bmp_info['bmWidth'], bmp_info['bmHeight']),
            bmp_str, 'raw', 'BGRX', 0, 1
        )
        img_array = np.array(img)
        # 统一为 BGR（OpenCV 约定），保证整条链路红点判定、保存前再转 RGB 时颜色一致
        if img_array.shape[2] == 3:
            img_array = np.ascontiguousarray(img_array[:, :, ::-1])
        return img_array
    
    except WindowNotFoundError:
        raise
    except Exception as e:
        error_msg = f"截图失败: {str(e)}"
        logger.error(error_msg)
        # 保存错误截图
        try:
            save_screenshot(
                np.zeros((100, 100, 3), dtype=np.uint8),
                f"error_capture_window_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
                task_id="error",
                step_name="capture_window",
                error_info=str(e)
            )
        except:
            pass
        raise ScreenshotError(error_msg)


def crop_region(image: np.ndarray, region: Tuple[int, int, int, int]) -> np.ndarray:
    """
    裁剪图像区域
    
    Args:
        image: 原始图像（numpy array）
        region: 区域 (x, y, width, height)
    
    Returns:
        裁剪后的图像
    """
    x, y, width, height = region
    return image[y:y+height, x:x+width]


def normalize_coords(x: int, y: int, source_dpi: float, target_dpi: float = 100.0) -> Tuple[int, int]:
    """
    坐标归一化处理
    
    Args:
        x, y: 原始坐标
        source_dpi: 源DPI缩放
        target_dpi: 目标DPI缩放（默认100%）
    
    Returns:
        归一化后的坐标 (x, y)
    """
    scale_factor = target_dpi / source_dpi
    new_x = int(x * scale_factor)
    new_y = int(y * scale_factor)
    return (new_x, new_y)


def window_to_screen_coords(hwnd: int, x: int, y: int) -> Tuple[int, int]:
    """
    将窗口内相对坐标转换为屏幕绝对坐标
    
    Args:
        hwnd: 窗口句柄
        x, y: 窗口内相对坐标
    
    Returns:
        屏幕绝对坐标 (screen_x, screen_y)
    """
    left, top, _, _ = get_window_client_bbox(hwnd)
    screen_x = left + x
    screen_y = top + y
    return (screen_x, screen_y)


def save_screenshot(
    image: np.ndarray,
    filename: str,
    task_id: Optional[str] = None,
    step_name: Optional[str] = None,
    confidence: Optional[float] = None,
    error_info: Optional[str] = None
) -> Path:
    """
    保存调试截图
    
    自动创建目录、添加时间戳、统一PNG格式。整条链路统一使用 BGR（OpenCV/capture_window），
    仅在写入文件前转为 RGB，保证打开保存的 PNG 时红色显示为红色。

    Args:
        image: 图像数组（numpy array，BGR 格式，与 capture_window / OpenCV 一致）
        filename: 基础文件名（不含扩展名）
        task_id: 任务ID（可选）
        step_name: 步骤名称（可选）
        confidence: 置信度（可选）
        error_info: 错误信息（可选）

    Returns:
        保存的文件路径
    """
    # 确保调试目录存在
    debug_dir = WeChatAutomationConfig.DEBUG_DIR
    debug_dir.mkdir(parents=True, exist_ok=True)
    
    # 构建文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [timestamp]
    
    if task_id:
        parts.append(f"task{task_id}")
    
    if step_name:
        parts.append(step_name)
    
    if confidence is not None:
        parts.append(f"conf{confidence:.2f}")
    
    if error_info:
        # 错误信息简化（移除特殊字符）
        error_clean = error_info.replace(":", "_").replace(" ", "_")[:20]
        parts.append(f"err_{error_clean}")
    
    parts.append(filename)
    filename_full = "_".join(parts) + ".png"
    
    # 保存文件
    file_path = debug_dir / filename_full
    
    try:
        # 整条链路为 BGR；保存时转为 RGB，否则看图软件会按 RGB 显示，红点会变成蓝紫色
        if len(image.shape) == 3 and image.shape[2] == 3:
            image = np.ascontiguousarray(image[:, :, ::-1])
        if len(image.shape) == 3:
            img = Image.fromarray(image)
        else:
            img = Image.fromarray(image).convert('RGB')
        img.save(file_path, 'PNG')
        logger.debug(f"截图已保存: {file_path}")
        return file_path
    
    except Exception as e:
        logger.error(f"保存截图失败: {e}")
        raise ScreenshotError(f"保存截图失败: {e}")
