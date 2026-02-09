"""联系人名字识别测试

测试使用OCR获取当前聊天界面联系人的名字
"""

import sys
from pathlib import Path

# 添加项目根目录（wechat 目录）到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from element_locator import (
    locate_all_elements,
    get_contact_name_roi,
    get_contact_name,
    get_element_bounds,
)
from models import LocateResult
from screen import get_wechat_hwnd, capture_window
from locator import put_chinese_text
import cv2
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_contact_name_roi():
    """测试1: 获取联系人名字区域并标注"""
    logger.info("=" * 60)
    logger.info("测试1: 获取联系人名字区域并标注")
    logger.info("=" * 60)
    
    try:
        # 获取窗口句柄
        hwnd = get_wechat_hwnd()
        logger.info(f"获取到窗口句柄: {hwnd}")
        
        # 截取窗口
        screenshot = capture_window(hwnd)
        logger.info(f"窗口截图尺寸: {screenshot.shape}")
        
        # 定位所有元素
        logger.info("开始定位所有UI元素...")
        positions = locate_all_elements(screenshot, threshold=0.7)
        
        # 获取联系人名字区域
        roi = get_contact_name_roi(positions)
        if roi is None:
            logger.warning("无法获取联系人名字区域，可能没有打开聊天界面")
            return False
        
        roi_x, roi_y, roi_width, roi_height = roi
        logger.info(f"联系人名字区域: x={roi_x}, y={roi_y}, width={roi_width}, height={roi_height}")
        
        # 在截图上标注区域
        annotated = screenshot.copy()
        
        # 绘制ROI边界框（红色）
        cv2.rectangle(
            annotated,
            (roi_x, roi_y),
            (roi_x + roi_width, roi_y + roi_height),
            (0, 0, 255),  # 红色
            3
        )
        
        # 标注区域信息
        label = f"联系人名字区域 ({roi_x},{roi_y}) {roi_width}x{roi_height}"
        annotated = put_chinese_text(
            annotated,
            label,
            (roi_x, roi_y - 20),
            font_size=14,
            color=(0, 0, 255)  # 红色
        )
        
        # 标注相关元素位置（用于验证）
        sticker_result = positions.get("sticker_icon")
        chat_message_result = positions.get("chat_message_icon")
        pin_result = positions.get("pin_icon")
        
        if (
            isinstance(sticker_result, LocateResult)
            and sticker_result.success
            and sticker_result.x is not None
            and sticker_result.y is not None
        ):
            sticker_bounds = get_element_bounds(
                sticker_result.x, sticker_result.y, "sticker_icon"
            )
            sticker_left = sticker_bounds[0]
            # 绘制sticker_icon左界（绿色竖线）
            cv2.line(
                annotated,
                (sticker_left, roi_y - 10),
                (sticker_left, roi_y + roi_height + 10),
                (0, 255, 0),  # 绿色
                2
            )
            annotated = put_chinese_text(
                annotated,
                "sticker左界",
                (sticker_left - 50, roi_y - 5),
                font_size=12,
                color=(0, 255, 0)  # 绿色
            )
        
        if (
            isinstance(chat_message_result, LocateResult)
            and chat_message_result.success
            and chat_message_result.x is not None
            and chat_message_result.y is not None
        ):
            chat_message_bounds = get_element_bounds(
                chat_message_result.x, chat_message_result.y, "chat_message_icon"
            )
            chat_message_left = chat_message_bounds[0]
            chat_message_bottom = chat_message_bounds[1] + chat_message_bounds[3]
            # 绘制chat_message_icon左界（蓝色竖线）
            cv2.line(
                annotated,
                (chat_message_left, roi_y - 10),
                (chat_message_left, roi_y + roi_height + 10),
                (255, 0, 0),  # 蓝色
                2
            )
            annotated = put_chinese_text(
                annotated,
                "chat_message左界",
                (chat_message_left - 80, roi_y - 5),
                font_size=12,
                color=(255, 0, 0)  # 蓝色
            )
            # 绘制chat_message_icon下界（蓝色横线）
            cv2.line(
                annotated,
                (roi_x - 10, chat_message_bottom),
                (roi_x + roi_width + 10, chat_message_bottom),
                (255, 0, 0),  # 蓝色
                2
            )
        
        if (
            isinstance(pin_result, LocateResult)
            and pin_result.success
            and pin_result.x is not None
            and pin_result.y is not None
        ):
            pin_bounds = get_element_bounds(
                pin_result.x, pin_result.y, "pin_icon"
            )
            pin_bottom = pin_bounds[1] + pin_bounds[3]
            # 绘制pin_icon下界（深粉色横线）
            cv2.line(
                annotated,
                (roi_x - 10, pin_bottom),
                (roi_x + roi_width + 10, pin_bottom),
                (255, 20, 147),  # 深粉色
                2
            )
            annotated = put_chinese_text(
                annotated,
                "pin下界",
                (roi_x + roi_width + 15, pin_bottom),
                font_size=12,
                color=(255, 20, 147)  # 深粉色
            )
        
        # 保存标注后的图像
        from screen import save_screenshot
        save_screenshot(
            annotated,
            "contact_name_roi",
            task_id="test_contact_name",
            step_name="roi",
            error_info=None
        )
        logger.info("标注图像已保存")
        
        return True
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_contact_name_ocr():
    """测试2: 使用OCR识别联系人名字"""
    logger.info("=" * 60)
    logger.info("测试2: 使用OCR识别联系人名字")
    logger.info("=" * 60)
    
    try:
        # 获取窗口句柄
        hwnd = get_wechat_hwnd()
        logger.info(f"获取到窗口句柄: {hwnd}")
        
        # 截取窗口
        screenshot = capture_window(hwnd)
        logger.info(f"窗口截图尺寸: {screenshot.shape}")
        
        # 获取联系人名字
        contact_name = get_contact_name(screenshot)
        
        if contact_name:
            logger.info(f"✓ 识别到联系人名字: '{contact_name}'")
            return True
        else:
            logger.warning("✗ 未识别到联系人名字")
            return False
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    logger.info("=" * 60)
    logger.info("联系人名字识别功能测试")
    logger.info("=" * 60)
    
    # 测试1: 获取联系人名字区域并标注
    if not test_contact_name_roi():
        logger.error("测试1失败")
        return
    
    logger.info("")
    
    # 测试2: 使用OCR识别联系人名字
    if not test_contact_name_ocr():
        logger.error("测试2失败")
        return
    
    logger.info("")
    logger.info("=" * 60)
    logger.info("所有测试完成！")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
