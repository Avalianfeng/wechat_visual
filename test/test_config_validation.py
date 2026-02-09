"""Phase 1：配置完整性与“假设显式化”测试

1. 配置自检是“硬失败”而不是 warning：validate_config() 未通过则抛 ConfigValidationError。
2. validate(strict=False) 与 validate(strict=True) 行为必须不同：
   - strict=False：仅必需模板缺失时报错，可选模板缺失不报错。
   - strict=True：可选模板缺失也报错。
"""

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

# 项目根加入 path，支持直接运行或 pytest
_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from config import WeChatAutomationConfig, ConfigValidationError


def _make_template_paths_with_one_missing(required_name: str):
    """构造一份 TEMPLATE_PATHS，使指定必需键“不存在”。"""
    paths = dict(WeChatAutomationConfig.TEMPLATE_PATHS)
    fake = MagicMock(spec=Path)
    fake.exists.return_value = False
    fake.name = paths[required_name].name
    paths[required_name] = fake
    return paths


def test_validate_config_fails_fast_when_required_template_missing():
    """缺失必需模板时，validate_config() 必须硬失败（抛 ConfigValidationError）。"""
    required_name = next(iter(WeChatAutomationConfig.REQUIRED_TEMPLATES))
    paths = _make_template_paths_with_one_missing(required_name)

    with patch.object(WeChatAutomationConfig, "TEMPLATE_PATHS", paths):
        try:
            WeChatAutomationConfig.validate_config(strict=False)
        except ConfigValidationError as e:
            assert "必需模板" in str(e) or required_name in str(e)
            return
    assert False, "validate_config() 应抛出 ConfigValidationError"


def test_validate_config_fails_fast_when_window_too_small():
    """窗口过小时，validate_config() 必须硬失败。"""
    with patch.object(WeChatAutomationConfig, "WINDOW_SIZE", (600, 400)):
        try:
            WeChatAutomationConfig.validate_config(strict=False)
        except ConfigValidationError as e:
            assert "窗口" in str(e) or "800" in str(e)
            return
    assert False, "validate_config() 应抛出 ConfigValidationError"


def test_validate_config_fails_fast_when_language_not_zh_cn():
    """语言不为 zh_CN 时，validate_config() 必须硬失败。"""
    with patch.object(WeChatAutomationConfig, "WECHAT_LANGUAGE", "en_US"):
        try:
            WeChatAutomationConfig.validate_config(strict=False)
        except ConfigValidationError as e:
            assert "zh_CN" in str(e) or "语言" in str(e)
            return
    assert False, "validate_config() 应抛出 ConfigValidationError"


def test_validate_strict_false_passes_with_only_required_templates():
    """strict=False 时，仅必需模板存在即可通过；可选模板缺失不导致失败。"""
    is_valid, msg = WeChatAutomationConfig.validate(strict=False)
    assert is_valid, f"当前项目在 strict=False 下应通过，失败原因: {msg}"
    assert msg == ""


def _make_template_paths_with_optional_missing(optional_name: str):
    """构造一份 TEMPLATE_PATHS，使指定可选键“不存在”。"""
    paths = dict(WeChatAutomationConfig.TEMPLATE_PATHS)
    fake = MagicMock(spec=Path)
    fake.exists.return_value = False
    fake.name = paths[optional_name].name
    paths[optional_name] = fake
    return paths


def test_validate_strict_true_fails_when_optional_missing():
    """strict=True 时，若有可选模板缺失，必须失败（与 strict=False 行为不同）。"""
    optional_names = list(WeChatAutomationConfig.OPTIONAL_TEMPLATES)
    if not optional_names:
        return
    optional_name = optional_names[0]
    paths = _make_template_paths_with_optional_missing(optional_name)

    with patch.object(WeChatAutomationConfig, "TEMPLATE_PATHS", paths):
        is_valid_strict_false, _ = WeChatAutomationConfig.validate(strict=False)
        is_valid_strict_true, msg_strict = WeChatAutomationConfig.validate(strict=True)
    assert is_valid_strict_false, "strict=False 下可选模板缺失不应导致失败"
    assert not is_valid_strict_true, "strict=True 下可选模板缺失应导致失败"
    assert "可选" in msg_strict or optional_name in msg_strict


def test_validate_config_strict_true_raises_when_optional_missing():
    """validate_config(strict=True) 在可选模板缺失时应抛 ConfigValidationError。"""
    optional_names = list(WeChatAutomationConfig.OPTIONAL_TEMPLATES)
    if not optional_names:
        return
    optional_name = optional_names[0]
    paths = _make_template_paths_with_optional_missing(optional_name)

    with patch.object(WeChatAutomationConfig, "TEMPLATE_PATHS", paths):
        try:
            WeChatAutomationConfig.validate_config(strict=True)
        except ConfigValidationError as e:
            assert optional_name in str(e) or "可选" in str(e)
            return
    assert False, "validate_config(strict=True) 在可选缺失时应抛出 ConfigValidationError"


if __name__ == "__main__":
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        # 无 pytest 时直接跑
        test_validate_config_fails_fast_when_required_template_missing()
        test_validate_config_fails_fast_when_window_too_small()
        test_validate_config_fails_fast_when_language_not_zh_cn()
        test_validate_strict_false_passes_with_only_required_templates()
        test_validate_strict_true_fails_when_optional_missing()
        test_validate_config_strict_true_raises_when_optional_missing()
        print("OK: all config validation tests passed")
