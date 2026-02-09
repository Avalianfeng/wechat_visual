"""Phase 2：屏幕与定位层的“可重复性”

同一画面 → 同一结果。验证的不是“能不能定位”，而是可重复性。

1. screen 纯函数：给截图/区域 → 出确定结果（crop_region 同入同出；get_window_client_bbox 同 hwnd 同出）
2. locator 不依赖“上一帧状态”：同一图+同一模板跑多次，结果差在阈值内
3. DPI 只是缩放：dpi=100/125/150 下，归一化后逻辑 ROI 坐标一致
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np

# 项目根加入 path
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


# ---------------------------------------------------------------------------
# 1. Screen：纯函数 / 同入同出
# ---------------------------------------------------------------------------

def test_crop_region_same_input_same_output():
    """crop_region：同一 image + 同一 region → 两次输出完全一致（纯函数）。"""
    from screen import crop_region

    np.random.seed(42)
    image = np.random.randint(0, 255, (200, 300, 3), dtype=np.uint8)
    region = (10, 20, 50, 60)  # x, y, w, h

    out1 = crop_region(image, region)
    out2 = crop_region(image, region)

    assert out1.shape == out2.shape == (60, 50, 3)
    np.testing.assert_array_equal(out1, out2)


def test_get_window_client_bbox_same_hwnd_same_output():
    """get_window_client_bbox：同一 hwnd（模拟同一画面）→ 两次输出一致。"""
    from screen import get_window_client_bbox

    hwnd = 12345
    # 固定返回值：同一“画面”对应同一 rect
    window_rect = (100, 50, 1100, 850)
    client_rect = (0, 0, 1000, 800)
    client_to_screen_point = (100, 50)

    with patch("screen.win32gui") as m_win32gui:
        m_win32gui.IsWindow.return_value = True
        m_win32gui.GetWindowRect.return_value = window_rect
        m_win32gui.GetClientRect.return_value = client_rect
        m_win32gui.ClientToScreen.return_value = client_to_screen_point

        out1 = get_window_client_bbox(hwnd)
        out2 = get_window_client_bbox(hwnd)

    # (screen_left, screen_top, width, height)
    expected = (100, 50, 1000, 800)
    assert out1 == expected and out2 == expected
    assert out1 == out2


# ---------------------------------------------------------------------------
# 2. Locator：不依赖上一帧，多次结果在阈值内
# ---------------------------------------------------------------------------

def test_match_template_same_input_same_output_three_times():
    """match_template：同一 image + 同一 template 跑 3 次，结果差在 1 像素内（无“上一帧状态”）。"""
    from locator import match_template

    # 合成图：大图里放一块小图，保证能匹配到
    np.random.seed(123)
    template = np.random.randint(0, 255, (24, 24, 3), dtype=np.uint8)
    image = np.zeros((100, 100, 3), dtype=np.uint8)
    image[30:54, 40:64] = template  # 中心约 (52, 42) 模板中心

    results = []
    for _ in range(3):
        point, confidence = match_template(image, template, threshold=0.5)
        results.append((point, confidence))

    # 三次结果应一致（或坐标差 ≤ 1）
    for i in range(1, len(results)):
        p0, c0 = results[i - 1]
        p1, c1 = results[i]
        assert p0 is not None and p1 is not None
        assert abs(p0[0] - p1[0]) <= 1 and abs(p0[1] - p1[1]) <= 1
        assert abs(c0 - c1) < 1e-6  # 置信度应完全一致


# ---------------------------------------------------------------------------
# 3. DPI 只是缩放，归一化后逻辑坐标一致
# ---------------------------------------------------------------------------

def test_normalize_coords_dpi_100_125_150_same_logical_roi():
    """normalize_coords：dpi=100/125/150 下，同一逻辑 ROI 归一化到 100% 后坐标一致。"""
    from screen import normalize_coords

    target = 100.0
    # 逻辑坐标 (100, 100) 在不同 DPI 下的物理坐标
    physical_at_100 = (100, 100)
    physical_at_125 = (125, 125)  # 125% 时同一逻辑点
    physical_at_150 = (150, 150)

    out_100 = normalize_coords(physical_at_100[0], physical_at_100[1], 100.0, target)
    out_125 = normalize_coords(physical_at_125[0], physical_at_125[1], 125.0, target)
    out_150 = normalize_coords(physical_at_150[0], physical_at_150[1], 150.0, target)

    assert out_100 == (100, 100)
    assert out_125 == (100, 100)
    assert out_150 == (100, 100)


def test_normalize_coords_roundtrip_physical_to_logical():
    """物理 → 逻辑(100%) → 再乘回源 DPI，应与原物理坐标一致（舍入误差内）。"""
    from screen import normalize_coords

    for source_dpi in (100.0, 125.0, 150.0):
        px, py = 200, 150
        lx, ly = normalize_coords(px, py, source_dpi, 100.0)
        scale = source_dpi / 100.0
        back_x = int(lx * scale)
        back_y = int(ly * scale)
        assert abs(back_x - px) <= 1 and abs(back_y - py) <= 1


if __name__ == "__main__":
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        test_crop_region_same_input_same_output()
        test_get_window_client_bbox_same_hwnd_same_output()
        test_match_template_same_input_same_output_three_times()
        test_normalize_coords_dpi_100_125_150_same_logical_roi()
        test_normalize_coords_roundtrip_physical_to_logical()
        print("OK: all screen/locator repeatability tests passed")
