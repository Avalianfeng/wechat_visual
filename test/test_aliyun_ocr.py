"""阿里云 / DashScope OCR 连通性测试（手动集成测试）。

说明：
- 这是一个「烟雾测试」，用于本地验证 OCR 接口配置是否正确，而不是严格的单元测试。
- 需要在环境变量或 .env 中配置以下任一项，否则自动 skip：
  - DASHSCOPE_API_KEY   （推荐，使用 DashScope Qwen-VL OCR）
  - ALIYUN_OCR_APPCODE  （兼容旧版阿里云市场高精 OCR）

用法示例：
  # 在项目根目录（包含 wechat 包的目录）执行：
  python -m pytest test/test_aliyun_ocr.py -q
"""

import os
import sys
from pathlib import Path

import numpy as np
import cv2
import pytest

# 添加项目根目录（wechat 目录）到路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from ocr_aliyun import ocr_region_aliyun  # noqa: E402


_HAS_DASHSCOPE = bool(os.getenv("DASHSCOPE_API_KEY", "").strip())
_HAS_APPCODE = bool(os.getenv("ALIYUN_OCR_APPCODE", "").strip())


@pytest.mark.skipif(
    not (_HAS_DASHSCOPE or _HAS_APPCODE),
    reason="未配置 DASHSCOPE_API_KEY 或 ALIYUN_OCR_APPCODE，跳过阿里云 OCR 测试",
)
def test_aliyun_ocr_smoke():
    """对接当前配置的 OCR 服务，做一次最小连通性测试。"""
    img_path = PROJECT_ROOT / "test_aliyun_ocr.png"

    if img_path.exists():
        # 如果用户提供了专门的中文测试图片，就直接使用（避免 cv2 中文字体问题）
        image = cv2.imread(str(img_path))
        if image is None:
            raise AssertionError(f"无法读取测试图片: {img_path}")
        h, w = image.shape[:2]
        src_desc = f"来自文件: {img_path.name}"
    else:
        # 回退：构造一张简单的英文测试图
        h, w = 200, 600
        image = np.ones((h, w, 3), dtype=np.uint8) * 255
        src_desc = "内置: ALIYUN OCR TEST"
        text = "ALIYUN OCR TEST"
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1.0
        thickness = 2
        (tw, th), _ = cv2.getTextSize(text, font, font_scale, thickness)
        x = (w - tw) // 2
        y = (h + th) // 2
        cv2.putText(image, text, (x, y), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)

    roi = (0, 0, w, h)

    result = ocr_region_aliyun(image, roi, timeout=10.0)

    # 仅做「不抛异常 + 返回字符串」的烟雾测试，不强制断言具体内容
    print(f"OCR 输入来源: {src_desc}")
    print(f"OCR 识别结果: {result!r}")

    assert isinstance(result, str)