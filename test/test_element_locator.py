"""元素定位测试

测试 element_locator 模块的功能，包括：
1. 定位所有UI元素
2. 标注所有元素位置
3. 保存位置信息到文件
"""

import sys
from pathlib import Path

# 添加项目根目录（wechat 目录）到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from element_locator import (
    locate_all_elements,
    locate_all_contact_avatars_in_list,
    locate_all_contact_avatars_in_chat,
    annotate_all_elements,
    save_element_positions,
    load_element_positions,
    test_locate_all_elements,
    get_chat_area_roi,
    has_new_message,
    save_chat_state,
)
from models import LocateResult
from screen import get_wechat_hwnd, capture_window
import logging

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """主测试函数"""
    try:
        logger.info("=" * 60)
        logger.info("开始测试元素定位功能")
        logger.info("=" * 60)
        
        # 运行测试函数（可以传递联系人信息进行测试）
        # 示例：测试特定联系人的头像定位
        # positions = test_locate_all_elements(contact_name="策月帘风", contact_id="cylf_id")
        # 测试所有联系人头像定位功能
        positions = test_locate_all_elements(test_all_contacts=True)
        
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
        
        logger.info("=" * 60)
        logger.info(f"测试完成: {success_count} 个元素定位成功（共 {total_count} 个元素类型）")
        logger.info("=" * 60)
        
        # 显示详细信息
        logger.info("\n详细结果:")
        for element_name, result_or_list in positions.items():
            if isinstance(result_or_list, list):
                # 数组类型（如profile_photo_in_chat）
                if result_or_list:
                    success_count = sum(1 for r in result_or_list if r.success)
                    logger.info(f"  ✓ {element_name}: 找到 {success_count}/{len(result_or_list)} 个（成功/总数）")
                    for i, result in enumerate(result_or_list):
                        if result.success:
                            logger.info(f"    [{i}] ({result.x}, {result.y}), 置信度={result.confidence:.3f}")
                else:
                    logger.info(f"  ✗ {element_name}: 未找到（空数组）")
            else:
                # 单个结果
                if result_or_list.success:
                    # 特殊处理：new_message_red_point 显示相对于头像的位置
                    if element_name == "new_message_red_point":
                        profile_photo = positions.get("profile_photo_in_list")
                        if (
                            isinstance(profile_photo, LocateResult)
                            and profile_photo.success
                            and profile_photo.x is not None
                            and profile_photo.y is not None
                            and result_or_list.x is not None
                            and result_or_list.y is not None
                        ):
                            # 计算相对于头像的偏移
                            offset_x = result_or_list.x - profile_photo.x
                            offset_y = result_or_list.y - profile_photo.y
                            logger.info(f"  ✓ {element_name}: ({result_or_list.x}, {result_or_list.y}), 置信度={result_or_list.confidence:.3f}")
                            logger.info(f"    相对于头像: (偏移x={offset_x:+d}, 偏移y={offset_y:+d})")
                        else:
                            logger.info(f"  ✓ {element_name}: ({result_or_list.x}, {result_or_list.y}), 置信度={result_or_list.confidence:.3f}")
                    else:
                        logger.info(f"  ✓ {element_name}: ({result_or_list.x}, {result_or_list.y}), 置信度={result_or_list.confidence:.3f}")
                else:
                    logger.info(f"  ✗ {element_name}: 定位失败 - {result_or_list.error_message}")
        
        # 测试加载保存的位置
        logger.info("\n测试加载保存的位置信息...")
        loaded_positions = load_element_positions()
        if loaded_positions:
            logger.info(f"成功加载 {len(loaded_positions)} 个元素的位置信息")
            for element_name, data in loaded_positions.items():
                # 检查是否为数组类型（如profile_photo_in_chat）
                if isinstance(data, list):
                    # 数组类型
                    logger.info(f"  {element_name}: 找到 {len(data)} 个头像")
                    for i, item in enumerate(data):
                        if item.get("success"):
                            logger.info(f"    [{i}] ({item['x']}, {item['y']}), 边界={item['bounds']}")
                else:
                    # 单个结果
                    if data.get("success"):
                        logger.info(f"  {element_name}: ({data['x']}, {data['y']}), 边界={data['bounds']}")
        else:
            logger.warning("未加载到位置信息")
        
        # 测试聊天区域ROI
        logger.info("\n测试聊天区域ROI...")
        chat_roi = get_chat_area_roi(positions)
        if chat_roi:
            roi_x, roi_y, roi_width, roi_height = chat_roi
            logger.info(f"✓ 聊天区域ROI: x={roi_x}, y={roi_y}, width={roi_width}, height={roi_height}")
        else:
            logger.warning("✗ 无法获取聊天区域ROI")
        
        # 测试一次性定位所有联系人头像（如果之前没有测试）
        logger.info("\n" + "=" * 60)
        logger.info("测试一次性定位所有联系人头像功能")
        logger.info("=" * 60)
        try:
            hwnd = get_wechat_hwnd()
            screenshot = capture_window(hwnd)
            
            # 测试列表区域
            logger.info("测试列表区域联系人头像定位...")
            # 测试时根据环境变量配置的“我”联系人排除掉
            try:
                from contact_mapper import ContactUserMapper as _TestContactUserMapper
            except ImportError:
                from ..contact_mapper import ContactUserMapper as _TestContactUserMapper  # type: ignore
            _mapper_for_test = _TestContactUserMapper()
            me_contact = _mapper_for_test.get_me_contact_name()
            exclude_for_test = [me_contact] if me_contact else None

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
        
        logger.info("\n" + "=" * 60)
        logger.info("所有测试完成！")
        logger.info("=" * 60)
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()


def test_has_new_message():
    """测试新消息检测功能"""
    try:
        logger.info("=" * 60)
        logger.info("测试新消息检测功能")
        logger.info("=" * 60)
        
        # 获取窗口截图
        hwnd = get_wechat_hwnd()
        screenshot = capture_window(hwnd)
        
        # 定位所有元素
        positions = locate_all_elements(screenshot)
        
        # 保存当前状态
        logger.info("保存当前聊天状态...")
        save_chat_state(positions, screenshot)
        
        # 等待一下
        import time
        logger.info("等待5秒，请在此期间发送一条新消息...")
        time.sleep(5)
        
        # 再次获取截图和位置
        screenshot2 = capture_window(hwnd)
        positions2 = locate_all_elements(screenshot2)
        
        # 检测是否有新消息
        logger.info("检测是否有新消息...")
        has_new = has_new_message(positions2, screenshot2)
        
        if has_new:
            logger.info("✓ 检测到新消息！")
        else:
            logger.info("✗ 未检测到新消息")
        
        return has_new
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "test_new_message":
            # 测试新消息检测
            test_has_new_message()
        elif sys.argv[1] == "test_single_contact":
            # 测试特定联系人头像定位
            contact_name = sys.argv[2] if len(sys.argv) > 2 else "策月帘风"
            contact_id = sys.argv[3] if len(sys.argv) > 3 else None
            logger.info(f"测试特定联系人头像定位: {contact_name}, ID: {contact_id}")
            positions = test_locate_all_elements(contact_name=contact_name, contact_id=contact_id)
        elif sys.argv[1] == "test_all_contacts":
            # 只测试一次性定位所有联系人头像
            logger.info("测试一次性定位所有联系人头像功能")
            positions = test_locate_all_elements(test_all_contacts=True)
        else:
            logger.warning(f"未知参数: {sys.argv[1]}，使用默认测试")
            main()
    else:
        # 默认测试元素定位（包含所有联系人头像定位测试）
        main()