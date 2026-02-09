# -*- coding: utf-8 -*-
"""阿里云 OCR 封装（现已切换为 DashScope Qwen-VL OCR，兼容 OpenAI 接口）。

用法保持不变：locator.ocr_region() 仍通过 ocr_region_aliyun(image_bgr, roi) 调用。

优先使用环境变量 DASHSCOPE_API_KEY（推荐）：
  - DASHSCOPE_API_KEY: DashScope API 密钥
  - 可选：DASHSCOPE_BASE_URL（默认 https://dashscope.aliyuncs.com/compatible-mode/v1）

若未配置 DASHSCOPE_API_KEY，则继续尝试旧的 ALIYUN_OCR_APPCODE HTTP 接口（向后兼容），
但推荐迁移到 DashScope。
"""

import base64
import json
import logging
import os
import ssl
from typing import Optional, Tuple

import cv2

try:
    # 新版 OpenAI 客户端（兼容 DashScope OpenAI 模式）
    from openai import OpenAI
except ImportError:  # pragma: no cover - 仅在缺少依赖时触发
    OpenAI = None  # type: ignore[assignment]

try:
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen
except ImportError:
    from urllib.request import Request, urlopen, HTTPError

logger = logging.getLogger(__name__)

# 支持相对导入和绝对导入
try:
    from .config import WeChatAutomationConfig
except ImportError:
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from config import WeChatAutomationConfig


def _image_to_base64_png(image_bgr) -> str:
    """将 BGR 图像转为 PNG base64 字符串"""
    success, buf = cv2.imencode(".png", image_bgr)
    if not success:
        raise ValueError("cv2.imencode png 失败")
    return base64.b64encode(buf.tobytes()).decode("utf-8")


def _ocr_via_dashscope_qwen(
    image_bgr,
    roi: Tuple[int, int, int, int],
    timeout: float = 15.0,
) -> str:
    """
    使用 DashScope Qwen-VL OCR（OpenAI 兼容接口）识别 ROI。

    返回识别出的文本（失败返回空字符串）。
    """
    api_key = (os.getenv("DASHSCOPE_API_KEY") or "").strip()
    if not api_key:
        return ""
    if OpenAI is None:
        logger.warning("openai 客户端未安装，无法使用 DashScope OCR")
        return ""

    base_url = os.getenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    ).strip() or "https://dashscope.aliyuncs.com/compatible-mode/v1"

    x, y, w, h = roi
    roi_image = image_bgr[y : y + h, x : x + w]
    if roi_image.size == 0:
        logger.warning("DashScope OCR ROI 区域为空")
        return ""

    # 最短边至少 15px（保持与旧接口一致的预处理）
    min_side = min(w, h)
    if min_side < 15:
        scale = 15 / min_side
        new_w = max(15, int(w * scale))
        new_h = max(15, int(h * scale))
        roi_image = cv2.resize(roi_image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    # 编码为 PNG 并构造 data URL 给 image_url 使用
    success, buf = cv2.imencode(".png", roi_image)
    if not success:
        logger.warning("DashScope OCR: cv2.imencode 失败")
        return ""
    b64 = base64.b64encode(buf.tobytes()).decode("utf-8")
    data_url = f"data:image/png;base64,{b64}"

    try:
        client = OpenAI(api_key=api_key, base_url=base_url, timeout=timeout)
        completion = client.chat.completions.create(
            model=os.getenv("DASHSCOPE_OCR_MODEL", "qwen-vl-ocr-2025-11-20"),
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                        {
                            "type": "text",
                            "text": "请仅输出图像中的文本内容。",
                        },
                    ],
                }
            ],
        )
        content = completion.choices[0].message.content
        # 兼容字符串或结构化 content
        if isinstance(content, str):
            text = content
        else:
            # openai>=1 通常返回 list[{"type": "text", "text": "..."}]
            parts = []
            for part in content:  # type: ignore[assignment]
                if isinstance(part, dict) and part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
            text = " ".join(parts)
        return (text or "").strip()
    except Exception as e:
        logger.warning("DashScope Qwen OCR 调用异常: %s", e)
        return ""


def _ocr_via_legacy_market_api(
    image_bgr,
    roi: Tuple[int, int, int, int],
    appcode: Optional[str],
    timeout: float = 15.0,
) -> str:
    """
    兼容旧版阿里云市场高精版 OCR 接口（APPCODE 方式）。
    """
    appcode = (appcode or WeChatAutomationConfig.ALIYUN_OCR_APPCODE or "").strip()
    if not appcode:
        return ""

    x, y, w, h = roi
    roi_image = image_bgr[y : y + h, x : x + w]
    if roi_image.size == 0:
        logger.warning("OCR ROI 区域为空")
        return ""

    min_side = min(w, h)
    if min_side < 15:
        scale = 15 / min_side
        new_w = max(15, int(w * scale))
        new_h = max(15, int(h * scale))
        roi_image = cv2.resize(roi_image, (new_w, new_h), interpolation=cv2.INTER_CUBIC)

    img_base64 = _image_to_base64_png(roi_image)
    body = {
        "img": img_base64,
        "prob": False,
        "charInfo": False,
        "rotate": False,
        "table": False,
        "sortPage": False,
        "noStamp": False,
        "figure": False,
        "row": False,
        "paragraph": False,
        "oricoord": False,
    }
    url = WeChatAutomationConfig.ALIYUN_OCR_URL
    headers = {
        "Authorization": "APPCODE %s" % appcode,
        "Content-Type": "application/json; charset=UTF-8",
    }
    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        resp = urlopen(req, timeout=timeout, context=ctx)
        raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        words = data.get("prism_wordsInfo") or []
        text = "".join(w.get("word", "") for w in words)
        return (text or "").strip()
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        logger.warning("阿里云 OCR 请求失败: %s %s", e.code, body[:200])
        return ""
    except Exception as e:
        logger.warning("阿里云 OCR 请求异常: %s", e)
        return ""


def ocr_region_aliyun(
    image_bgr,
    roi: Tuple[int, int, int, int],
    appcode: Optional[str] = None,
    timeout: float = 15.0,
) -> str:
    """
    统一对外的阿里云 OCR 封装。

    优先：
      1) 若配置了 DASHSCOPE_API_KEY，则使用 DashScope Qwen-VL OCR（OpenAI 兼容接口）
      2) 否则，若配置了 ALIYUN_OCR_APPCODE，则使用旧的阿里云市场高精版 OCR
      3) 都没有时，返回空字符串（locator.ocr_region 会再决定是否回退到 Tesseract）
    """
    # 1) DashScope Qwen-VL OCR
    text = _ocr_via_dashscope_qwen(image_bgr, roi, timeout=timeout)
    if text:
        return text

    # 2) 旧版 APPCODE 接口（向后兼容）
    text = _ocr_via_legacy_market_api(image_bgr, roi, appcode=appcode, timeout=timeout)
    return text or ""
