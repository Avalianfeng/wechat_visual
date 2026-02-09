"""定位服务模块

提供多种定位方法，用于在微信窗口中定位UI元素。

核心功能：
- match_template(): 基础模板匹配（被match_all_templates内部使用）
- match_all_templates(): 多模板匹配（亮/暗主题、不同版本）
- ocr_region(): 区域OCR识别
- put_chinese_text(): 在图像上绘制中文文本

注意事项：
1. 模板匹配是最可靠的方法，优先使用
2. OCR定位受字体、语言影响
3. 定位结果应包含置信度，低于0.8的结果需要重试
4. 定位失败时应保存截图用于调试

依赖库：
- opencv-python: 模板匹配和图像处理
- pytesseract: OCR识别（可选）
- numpy: 数组操作
- PIL/Pillow: 中文文本绘制
"""

import cv2
import numpy as np
import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any
from pathlib import Path

# 支持相对导入（作为模块）和绝对导入（直接运行）
try:
    from .models import LocateResult, LocateMethod
    from .screen import save_screenshot, crop_region
    from .config import WeChatAutomationConfig
except ImportError:
    import sys
    sys.path.insert(0, str(Path(__file__).parent))
    from models import LocateResult, LocateMethod
    from screen import save_screenshot, crop_region
    from config import WeChatAutomationConfig

logger = logging.getLogger(__name__)

# PIL/Pillow 用于中文文本绘制
try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None  # type: ignore[assignment, misc]
    ImageDraw = None  # type: ignore[assignment, misc]
    ImageFont = None  # type: ignore[assignment, misc]
    logger.warning("PIL/Pillow 未安装，中文文本标注功能将不可用")


def put_chinese_text(
    image: np.ndarray,
    text: str,
    position: Tuple[int, int],
    font_size: int = 16,
    color: Tuple[int, int, int] = (255, 255, 255),
    stroke_width: int = 0,
    stroke_fill: Optional[Tuple[int, int, int]] = None,
) -> np.ndarray:
    """
    在OpenCV图像上绘制中文文本（使用PIL/Pillow）
    
    Args:
        image: OpenCV图像（BGR格式，numpy数组）
        text: 要绘制的文本（支持中文）
        position: 文本位置 (x, y)
        font_size: 字体大小（默认16）
        color: 文本颜色 (B, G, R)（默认白色）
        stroke_width: 描边宽度（默认0，无描边）
        stroke_fill: 描边颜色 (B, G, R)（默认None）
    
    Returns:
        绘制了文本的图像（BGR格式，numpy数组）
    """
    if not PIL_AVAILABLE or Image is None or ImageDraw is None or ImageFont is None:
        # 如果PIL不可用，使用cv2.putText绘制（可能无法显示中文）
        logger.warning("PIL不可用，使用cv2.putText绘制文本（可能无法显示中文）")
        cv2.putText(image, text, position, cv2.FONT_HERSHEY_SIMPLEX, 
                   font_size / 20.0, color, max(1, stroke_width))
        return image
    
    try:
        # 将OpenCV图像（BGR）转换为PIL图像（RGB）
        pil_image = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil_image)
        
        # 尝试加载中文字体
        font = None
        try:
            # 尝试使用Windows系统字体
            import platform
            if platform.system() == 'Windows':
                # Windows常见中文字体路径
                font_paths = [
                    'C:/Windows/Fonts/msyh.ttc',  # 微软雅黑
                    'C:/Windows/Fonts/simsun.ttc',  # 宋体
                    'C:/Windows/Fonts/simhei.ttf',  # 黑体
                ]
                for font_path in font_paths:
                    if Path(font_path).exists():
                        try:
                            font = ImageFont.truetype(font_path, font_size)
                            break
                        except:
                            continue
        except:
            pass
        
        # 如果没有找到字体，使用默认字体（可能不支持中文）
        if font is None:
            font = ImageFont.load_default()
        
        # 转换颜色格式（BGR -> RGB）
        rgb_color = (color[2], color[1], color[0])
        rgb_stroke_fill = None
        if stroke_fill is not None:
            rgb_stroke_fill = (stroke_fill[2], stroke_fill[1], stroke_fill[0])
        
        # 绘制文本
        draw.text(
            position,
            text,
            font=font,
            fill=rgb_color,
            stroke_width=stroke_width,
            stroke_fill=rgb_stroke_fill
        )
        
        # 将PIL图像（RGB）转换回OpenCV图像（BGR）
        image_with_text = cv2.cvtColor(np.array(pil_image), cv2.COLOR_RGB2BGR)
        return image_with_text
        
    except Exception as e:
        logger.warning(f"使用PIL绘制中文文本失败: {e}，回退到cv2.putText")
        # 回退到cv2.putText（可能无法显示中文）
        cv2.putText(image, text, position, cv2.FONT_HERSHEY_SIMPLEX, 
                   font_size / 20.0, color, max(1, stroke_width))
        return image


# OCR 可选依赖
pytesseract = None  # type: ignore[assignment]
try:
    import pytesseract
    import os
    
    # 配置 Tesseract 路径
    # 方法1：从环境变量读取
    tesseract_path = os.getenv('TESSERACT_CMD')
    if tesseract_path and os.path.exists(tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = tesseract_path
        logger.info(f"从环境变量找到 Tesseract: {tesseract_path}")
    else:
        # 方法2：尝试默认路径（包括常见安装位置）
        default_paths = [
            r'D:\software\Tesseract-OCR\tesseract.exe',  # 用户实际路径
            r'C:\Program Files\Tesseract-OCR\tesseract.exe',
            r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
            r'D:\Tesseract-OCR\tesseract.exe',
            r'E:\Tesseract-OCR\tesseract.exe',
        ]
        found = False
        for path in default_paths:
            if os.path.exists(path):
                pytesseract.pytesseract.tesseract_cmd = path
                logger.info(f"找到 Tesseract: {path}")
                found = True
                break
        
        if not found:
            # 方法3：尝试使用系统PATH中的tesseract（通过subprocess查找）
            try:
                import subprocess
                result = subprocess.run(['where.exe', 'tesseract'], 
                                      capture_output=True, text=True, timeout=2)
                if result.returncode == 0 and result.stdout.strip():
                    path = result.stdout.strip().split('\n')[0]
                    if os.path.exists(path):
                        pytesseract.pytesseract.tesseract_cmd = path
                        logger.info(f"从系统PATH找到 Tesseract: {path}")
                        found = True
            except Exception as e:
                logger.debug(f"通过where.exe查找失败: {e}")
            
            if not found:
                logger.warning("未找到 Tesseract，OCR功能可能不可用")
    
    # 测试Tesseract是否可用
    try:
        # 确保tesseract_cmd指向可执行文件，而不是目录
        if hasattr(pytesseract.pytesseract, 'tesseract_cmd'):
            tesseract_cmd = pytesseract.pytesseract.tesseract_cmd
            if tesseract_cmd and os.path.exists(tesseract_cmd):
                # 如果是目录，添加tesseract.exe
                if os.path.isdir(tesseract_cmd):
                    tesseract_cmd = os.path.join(tesseract_cmd, 'tesseract.exe')
                    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
                    logger.info(f"修正Tesseract路径: {tesseract_cmd}")
                # 如果路径不存在，尝试在目录下查找tesseract.exe
                elif not os.path.isfile(tesseract_cmd):
                    # 可能是路径配置错误，尝试在常见位置查找
                    parent_dir = os.path.dirname(tesseract_cmd) if os.path.dirname(tesseract_cmd) else tesseract_cmd
                    possible_exe = os.path.join(parent_dir, 'tesseract.exe')
                    if os.path.exists(possible_exe):
                        pytesseract.pytesseract.tesseract_cmd = possible_exe
                        logger.info(f"修正Tesseract路径: {possible_exe}")
        
        # 尝试获取版本信息来验证Tesseract是否可用
        version = pytesseract.get_tesseract_version()
        logger.info(f"Tesseract版本: {version}")
        OCR_AVAILABLE = True
        logger.info("OCR功能已启用")
    except Exception as e:
        OCR_AVAILABLE = False
        logger.warning(f"Tesseract不可用: {e}，OCR功能将不可用")
        # 尝试最后的手段：使用系统PATH中的tesseract
        try:
            import subprocess
            result = subprocess.run(['where.exe', 'tesseract'], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip():
                path = result.stdout.strip().split('\n')[0]
                if os.path.exists(path):
                    pytesseract.pytesseract.tesseract_cmd = path
                    logger.info(f"从系统PATH找到Tesseract: {path}")
                    # 再次尝试获取版本
                    version = pytesseract.get_tesseract_version()
                    logger.info(f"Tesseract版本: {version}")
                    OCR_AVAILABLE = True
                    logger.info("OCR功能已启用（通过系统PATH）")
        except Exception as e2:
            logger.debug(f"通过系统PATH查找也失败: {e2}")
except ImportError:
    pytesseract = None  # type: ignore[assignment]
    OCR_AVAILABLE = False
    logger.warning("pytesseract 未安装，OCR功能将不可用")
except Exception as e:
    OCR_AVAILABLE = False
    logger.warning(f"OCR配置失败: {e}，OCR功能将不可用")


class LocateError(Exception):
    """定位错误异常"""
    pass


def match_template(
    image: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.8
) -> Tuple[Optional[Tuple[int, int]], float]:
    """
    模板匹配，返回最佳点和置信度
    
    Args:
        image: 源图像（BGR格式）
        template: 模板图像（BGR格式）
        threshold: 匹配阈值（0.0-1.0），低于此值返回None
    
    Returns:
        (最佳点坐标(x, y), 置信度) 或 (None, 置信度)
    """
    try:
        # 转换为灰度图（模板匹配通常在灰度图上进行）
        if len(image.shape) == 3:
            image_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        else:
            image_gray = image
        
        if len(template.shape) == 3:
            template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
        else:
            template_gray = template
        
        # 模板匹配
        result = cv2.matchTemplate(image_gray, template_gray, cv2.TM_CCOEFF_NORMED)
        
        # 找到最佳匹配位置
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        confidence = float(max_val)
        
        if confidence >= threshold:
            # 返回模板中心点坐标
            template_h, template_w = template_gray.shape[:2]
            center_x = max_loc[0] + template_w // 2
            center_y = max_loc[1] + template_h // 2
            return ((center_x, center_y), confidence)
        else:
            return (None, confidence)
    
    except Exception as e:
        logger.error(f"模板匹配失败: {e}")
        return (None, 0.0)


def match_all_templates(
    image: np.ndarray,
    template_group: List[Path],
    threshold: float = 0.8,
    original_image: Optional[np.ndarray] = None,
    search_region_offset: Optional[Tuple[int, int]] = None,
) -> LocateResult:
    """
    多模板匹配（同一元素的不同版本：亮/暗主题、不同版本等）
    
    尝试所有模板，返回最佳匹配结果
    
    Args:
        image: 源图像（BGR格式，可能是裁剪后的区域）
        template_group: 模板文件路径列表
        threshold: 匹配阈值（0.0-1.0）
        original_image: 原始完整截图（可选，用于保存调试截图时显示完整区域）
        search_region_offset: 搜索区域在原始图像中的偏移 (offset_x, offset_y)（可选）
    
    Returns:
        定位结果（最佳匹配）
    """
    best_result = None
    best_confidence = 0.0
    best_template = None
    
    for template_path in template_group:
        if not template_path.exists():
            logger.warning(f"模板文件不存在: {template_path}")
            continue
        
        try:
            # 加载模板
            template = cv2.imread(str(template_path))
            if template is None:
                logger.warning(f"无法加载模板: {template_path}")
                continue
            
            # 匹配模板
            point, confidence = match_template(image, template, threshold)
            
            logger.debug(f"模板 {template_path.name}: 置信度={confidence:.3f}, 匹配成功={point is not None}, 阈值={threshold}")
            
            # 更新最佳置信度（无论是否匹配成功）
            if confidence > best_confidence:
                best_confidence = confidence
                best_template = template_path.name
            
            # 如果匹配成功（point不为None），创建或更新best_result
            # 注意：即使置信度不是最高的，只要匹配成功就应该返回
            if point is not None:
                x, y = point
                template_h, template_w = template.shape[:2]
                # 如果还没有成功的结果，或者这个结果的置信度更高，则更新
                if best_result is None or confidence > best_result.confidence:
                    best_result = LocateResult(
                        success=True,
                        x=x,
                        y=y,
                        confidence=confidence,
                        method=LocateMethod.TEMPLATE_MATCH,
                        region=(x - template_w // 2, y - template_h // 2, template_w, template_h),
                        error_message=None
                    )
                    logger.debug(f"更新最佳匹配结果: {template_path.name}, 位置=({x}, {y}), 置信度={confidence:.3f}")
        
        except Exception as e:
            logger.warning(f"匹配模板 {template_path} 时出错: {e}")
            continue
    
    if best_result is None:
        # 所有模板都匹配失败，不保存调试截图（只在最终汇总时保存）
        return LocateResult(
            success=False,
            confidence=best_confidence,
            method=LocateMethod.TEMPLATE_MATCH,
            error_message=f"所有模板匹配失败，最佳置信度: {best_confidence:.2f}"
        )
    
    return best_result


def _contains_chinese(text: str) -> bool:
    """判断文本是否包含中文字符"""
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            return True
    return False


def ocr_region(
    image: np.ndarray, 
    roi: Tuple[int, int, int, int],
    save_preprocessed: bool = False,
    debug_prefix: Optional[str] = None,
    save_steps: bool = False,  # 保存每个预处理步骤的图像
    expect_chinese: bool = False,  # 期望中文（如联系人名），不回退到英文模式（避免中文被误识为乱码如"Sv)"）
    prefer_aliyun: bool = False  # 为 True 时仅使用阿里云 OCR，不回退到 Tesseract（用于联系人名校验等）
) -> str:
    """
    区域OCR识别（只做区域OCR，不做全屏）
    
    优先使用阿里云高精版 OCR（需配置 ALIYUN_OCR_APPCODE），未配置时使用 Tesseract。
    当 prefer_aliyun=True 时仅尝试阿里云，失败或未配置时返回空字符串。
    
    Args:
        image: 源图像（BGR格式）
        roi: 感兴趣区域 (x, y, width, height)
        save_preprocessed: 是否保存预处理后的图像（用于调试）
        debug_prefix: 调试文件前缀（如果save_preprocessed=True）
        save_steps: 是否保存每个预处理步骤的图像（用于调试）
        expect_chinese: 期望中文时设为True，仅使用chi_sim+eng，不回退到eng（避免中文被误识为乱码）
        prefer_aliyun: 为 True 时仅使用阿里云，不回退 Tesseract
    
    Returns:
        识别出的文本（去除空白字符）
    """
    appcode = (getattr(WeChatAutomationConfig, "ALIYUN_OCR_APPCODE", None) or "").strip()
    ocr_aliyun_module = None
    if appcode:
        try:
            from . import ocr_aliyun as ocr_aliyun_module
        except ImportError:
            try:
                import ocr_aliyun as ocr_aliyun_module
            except ImportError:
                logger.debug("阿里云 OCR 模块未找到，回退 Tesseract")
                appcode = ""
        if appcode and ocr_aliyun_module is not None:
            try:
                text = ocr_aliyun_module.ocr_region_aliyun(image, roi, appcode=appcode)
                text = text.strip().replace("\n", " ").replace("\r", " ")
                return text
            except Exception as e:
                logger.warning("阿里云 OCR 调用异常，回退 Tesseract: %s", e)
                if prefer_aliyun:
                    return ""

    if prefer_aliyun:
        return ""
    if not OCR_AVAILABLE or pytesseract is None:
        logger.warning("OCR功能不可用（pytesseract未安装）")
        return ""

    try:
        x, y, w, h = roi

        # 裁剪区域
        if len(image.shape) == 3:
            roi_image = image[y:y+h, x:x+w]
        else:
            roi_image = image[y:y+h, x:x+w]

        # 保存原始ROI（用于对比）
        if save_steps:
            try:
                prefix = debug_prefix or "ocr"
                save_screenshot(
                    roi_image,
                    f"{prefix}_roi_raw",
                    task_id="ocr",
                    step_name="raw",
                    error_info=None
                )
            except Exception as e:
                logger.debug(f"保存原始ROI失败: {e}")
        
        # 图像预处理 - 仅做灰度化
        # 不做任何其他处理（放大、对比度增强等都会降低清晰度）
        
        # 转换为灰度图
        if len(roi_image.shape) == 3:
            # 确保从BGR转换为灰度
            processed_image = cv2.cvtColor(roi_image, cv2.COLOR_BGR2GRAY)
        else:
            processed_image = roi_image.copy()
        
        # 小区域放大 2 倍再 OCR，提高中文识别稳定性（Tesseract 对小字识别较差）
        if expect_chinese and (w < 200 or h < 50):
            scale = 2
            processed_image = cv2.resize(
                processed_image,
                (w * scale, h * scale),
                interpolation=cv2.INTER_CUBIC
            )
        
        # 保存灰度图（用于调试）
        if save_steps:
            try:
                prefix = debug_prefix or "ocr"
                save_screenshot(
                    processed_image,
                    f"{prefix}_roi_gray",
                    task_id="ocr",
                    step_name="gray",
                    error_info=None
                )
            except Exception as e:
                logger.debug(f"保存灰度图失败: {e}")
        
        # 保存最终预处理后的图像（用于调试）
        if save_preprocessed or save_steps:
            try:
                prefix = debug_prefix or "ocr"
                save_screenshot(
                    processed_image,
                    f"{prefix}_roi_final",
                    task_id="ocr",
                    step_name="final",
                    error_info=None
                )
                logger.debug(f"最终预处理图像已保存: {prefix}_roi_final")
            except Exception as e:
                logger.debug(f"保存最终预处理图像失败（非关键错误）: {e}")
        
        # 转换为PIL Image（pytesseract需要PIL Image）
        # 注意：processed_image 是灰度图（单通道），直接转换即可
        # 如果是多通道图像，需要先转换为RGB（避免BGR/RGB混用问题）
        from PIL import Image
        import os
        import tempfile
        
        # 确保是单通道灰度图或正确转换为RGB
        if len(processed_image.shape) == 3:
            # 如果是多通道，转换为RGB（从BGR转换）
            if processed_image.shape[2] == 3:
                processed_image = cv2.cvtColor(processed_image, cv2.COLOR_BGR2RGB)
            pil_image = Image.fromarray(processed_image)
        else:
            # 单通道灰度图，直接转换
            pil_image = Image.fromarray(processed_image)
        
        # OCR识别配置
        # 对于联系人名字（单行文本），使用PSM 7（单行文本）或PSM 6（单块文本）
        # PSM 7 = 单行文本，适合联系人名字这种单行文本
        # PSM 6 = 单块文本，也适合
        text = ""
        
        # 设置临时目录环境变量，避免权限问题
        # 使用用户临时目录，通常有写入权限
        original_temp = os.environ.get('TMPDIR') or os.environ.get('TMP') or os.environ.get('TEMP')
        try:
            # 确保临时目录存在且有写入权限
            user_temp = tempfile.gettempdir()
            if not os.path.exists(user_temp):
                os.makedirs(user_temp, exist_ok=True)
            # 设置临时目录环境变量（pytesseract可能会使用）
            os.environ['TMPDIR'] = user_temp
            os.environ['TMP'] = user_temp
            os.environ['TEMP'] = user_temp
            
            # 尝试不同的PSM模式
            psm_modes = ['--psm 7', '--psm 6', '--psm 11', '--psm 8']
            
            for psm_mode in psm_modes:
                try:
                    # 优先尝试中文+英文
                    text = pytesseract.image_to_string(
                        pil_image, 
                        lang='chi_sim+eng',
                        config=psm_mode
                    )
                    if text.strip():
                        # 若期望中文但结果为纯ASCII乱码（如"Sv)"），不采纳，继续尝试其他PSM
                        if expect_chinese and not _contains_chinese(text):
                            logger.warning(f"期望中文但识别结果为非中文: '{text}'，可能是chi_sim语言包未安装或识别错误，忽略")
                            text = ""
                        else:
                            logger.debug(f"OCR识别成功，使用PSM模式: {psm_mode}")
                            break
                except Exception as e1:
                    logger.debug(f"PSM {psm_mode} 中文+英文OCR失败: {e1}")
                    if expect_chinese:
                        # 期望中文时不回退到eng，避免中文被误识为乱码
                        logger.warning(f"期望中文但chi_sim+eng失败: {e1}，请确保已安装chi_sim语言包")
                    else:
                        try:
                            # 如果中文识别失败，尝试只用英文
                            text = pytesseract.image_to_string(
                                pil_image, 
                                lang='eng',
                                config=psm_mode
                            )
                            if text.strip():
                                logger.debug(f"OCR识别成功（英文），使用PSM模式: {psm_mode}")
                                break
                        except Exception as e2:
                            logger.debug(f"PSM {psm_mode} 英文OCR失败: {e2}")
                            try:
                                # 最后尝试默认语言
                                text = pytesseract.image_to_string(pil_image, config=psm_mode)
                                if text.strip():
                                    logger.debug(f"OCR识别成功（默认语言），使用PSM模式: {psm_mode}")
                                    break
                            except Exception as e3:
                                logger.debug(f"PSM {psm_mode} 默认语言OCR失败: {e3}")
                                continue
            
            if not text.strip():
                if expect_chinese:
                    logger.warning(
                        "所有PSM模式都失败，无法识别中文。"
                        "请确保已安装 Tesseract 中文语言包 chi_sim，参考 test/pytesseract_setup.md"
                    )
                else:
                    logger.warning(f"所有PSM模式都失败，无法识别文字")
        except Exception as e:
            logger.warning(f"OCR识别过程出错: {e}")
            import traceback
            logger.debug(traceback.format_exc())
        finally:
            # 恢复原始临时目录环境变量
            if original_temp:
                os.environ['TMPDIR'] = original_temp
                os.environ['TMP'] = original_temp
                os.environ['TEMP'] = original_temp
            else:
                # 如果原来没有设置，删除环境变量
                os.environ.pop('TMPDIR', None)
                os.environ.pop('TMP', None)
                os.environ.pop('TEMP', None)
        
        # 清理文本
        text = text.strip().replace('\n', ' ').replace('\r', ' ')
        
        return text
    
    except Exception as e:
        logger.warning(f"OCR识别失败: {e}")
        return ""


def validate_location(result: LocateResult, window_size: Tuple[int, int]) -> bool:
    """
    验证定位结果是否在窗口范围内
    
    Args:
        result: 定位结果
        window_size: 窗口大小 (width, height)
    
    Returns:
        是否有效
    """
    if not result.success:
        return False
    
    if result.x is None or result.y is None:
        return False
    
    width, height = window_size
    
    # 检查坐标是否在窗口内
    if 0 <= result.x < width and 0 <= result.y < height:
        return True
    
    return False
