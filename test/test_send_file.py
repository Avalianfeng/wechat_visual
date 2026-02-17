"""发送文件功能测试（send_file 统一复制粘贴）

测试 send_file 和 send_file_to_contact 流程（文件/图片均走复制粘贴）。
包含 mock 测试（逻辑验证）和 E2E 测试（真实窗口）。
"""

import sys
import os
import tempfile
from pathlib import Path
from typing import Optional
from unittest.mock import patch

import numpy as np

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from models import FlowResult, TaskType, LocateResult, LocateMethod


def _make_locate_result(x: int, y: int, success: bool = True) -> LocateResult:
    """创建模拟的定位结果"""
    return LocateResult(success=success, x=x, y=y, confidence=0.9, method=LocateMethod.TEMPLATE_MATCH)


def _create_test_file(file_path: str, content: str = "test file content") -> str:
    """创建测试用的文件"""
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    return file_path


# ---------------------------------------------------------------------------
# Mock 测试
# ---------------------------------------------------------------------------

def test_send_file_success():
    """send_file：成功发送文件的流程测试（复制粘贴）"""
    from flows import send_file

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        file_path = tmp.name
        _create_test_file(file_path)

    try:
        hwnd = 12345
        positions = {"input_box_anchor": _make_locate_result(500, 600)}

        with (
            patch("flows.get_wechat_hwnd", return_value=hwnd),
            patch("flows.activate_window", return_value=True),
            patch(
                "flows.capture_window",
                return_value=np.zeros((800, 1200, 3), dtype=np.uint8),
            ),
            patch("flows.locate_all_elements", return_value=positions),
            patch("flows.click", return_value=True),
            patch("flows.copy_file_or_image_to_clipboard", return_value=True),
            patch("flows.paste_file_or_image", return_value=True),
            patch("flows.hotkey", return_value=True),
            patch("flows.save_chat_state"),
            patch("flows.human_delay"),
        ):
            result = send_file(file_path)

        assert result.success is True
        assert result.task_type == TaskType.SEND_MESSAGE
        assert result.data is not None
        assert result.data.get("file_path") == file_path
        assert result.execution_time >= 0
    finally:
        if os.path.exists(file_path):
            os.unlink(file_path)


def test_send_file_fails_when_no_input_box():
    """send_file：未找到输入框时返回失败"""
    from flows import send_file

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        file_path = tmp.name
        _create_test_file(file_path)

    try:
        hwnd = 12345
        positions = {"input_box_anchor": _make_locate_result(0, 0, success=False)}

        with (
            patch("flows.get_wechat_hwnd", return_value=hwnd),
            patch("flows.activate_window", return_value=True),
            patch(
                "flows.capture_window",
                return_value=np.zeros((800, 1200, 3), dtype=np.uint8),
            ),
            patch("flows.locate_all_elements", return_value=positions),
            patch("flows.human_delay"),
        ):
            result = send_file(file_path)

        assert result.success is False
        assert "输入框" in (result.error_message or "")
    finally:
        if os.path.exists(file_path):
            os.unlink(file_path)


def test_send_file_fails_when_copy_clipboard_fails():
    """send_file：复制到剪贴板失败时返回失败"""
    from flows import send_file

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        file_path = tmp.name
        _create_test_file(file_path)

    try:
        hwnd = 12345
        positions = {"input_box_anchor": _make_locate_result(500, 600)}

        with (
            patch("flows.get_wechat_hwnd", return_value=hwnd),
            patch("flows.activate_window", return_value=True),
            patch(
                "flows.capture_window",
                return_value=np.zeros((800, 1200, 3), dtype=np.uint8),
            ),
            patch("flows.locate_all_elements", return_value=positions),
            patch("flows.click", return_value=True),
            patch("flows.copy_file_or_image_to_clipboard", return_value=False),
            patch("flows.human_delay"),
        ):
            result = send_file(file_path)

        assert result.success is False
        assert "剪贴板" in (result.error_message or "")
    finally:
        if os.path.exists(file_path):
            os.unlink(file_path)


def test_send_file_to_contact_success():
    """send_file_to_contact：成功向指定联系人发送文件"""
    from flows import send_file_to_contact

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        file_path = tmp.name
        _create_test_file(file_path)

    try:
        open_result = FlowResult(
            success=True,
            task_type=TaskType.OPEN_CHAT,
            execution_time=0.5,
            data={"contact_name": "张三"},
        )

        send_result = FlowResult(
            success=True,
            task_type=TaskType.SEND_MESSAGE,
            execution_time=2.0,
            data={"file_path": file_path},
        )

        with (
            patch("flows.open_chat", return_value=open_result),
            patch("flows.send_file", return_value=send_result),
        ):
            result = send_file_to_contact("张三", file_path)

        assert result.success is True
        assert result.task_type == TaskType.SEND_MESSAGE
        assert result.data is not None
        assert result.data.get("contact_name") == "张三"
        assert result.data.get("file_path") == file_path
    finally:
        if os.path.exists(file_path):
            os.unlink(file_path)


def test_send_file_to_contact_fails_when_open_chat_fails():
    """send_file_to_contact：打开聊天窗口失败时返回失败"""
    from flows import send_file_to_contact

    with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
        file_path = tmp.name
        _create_test_file(file_path)

    try:
        open_result = FlowResult(
            success=False,
            task_type=TaskType.OPEN_CHAT,
            execution_time=0.1,
            error_message="打开聊天窗口失败",
        )

        with patch("flows.open_chat", return_value=open_result):
            result = send_file_to_contact("张三", file_path)

        assert result.success is False
        assert "打开聊天窗口" in (result.error_message or "")
    finally:
        if os.path.exists(file_path):
            os.unlink(file_path)


# ---------------------------------------------------------------------------
# E2E 测试（真实窗口）
# ---------------------------------------------------------------------------

def run_real_send_file(file_path: str):
    """在真实窗口中执行 send_file，打印结果"""
    from flows import send_file

    result = send_file(file_path)
    _print_result("send_file", result, extra=f"文件路径: {file_path}")


def run_real_send_file_to_contact(contact: str, file_path: str):
    """在真实窗口中执行 send_file_to_contact，打印结果"""
    from flows import send_file_to_contact

    result = send_file_to_contact(contact, file_path)
    _print_result(
        "send_file_to_contact",
        result,
        contact=contact,
        extra=f"文件路径: {file_path}",
    )


def _print_result(
    step_name: str,
    result,
    contact: Optional[str] = None,
    extra: Optional[str] = None,
):
    """统一打印执行结果，便于人工判断"""
    from models import FlowResult

    if not isinstance(result, FlowResult):
        print(f"[{step_name}] 异常: 返回类型不是 FlowResult: {type(result)}")
        return

    status = "成功" if result.success else "失败"
    print(f"\n--- [{step_name}] {status} (耗时 {result.execution_time:.2f}s) ---")

    if result.success and result.data:
        for k, v in (result.data or {}).items():
            print(f"  {k}: {v}")

    if not result.success and result.error_message:
        print(f"  错误: {result.error_message}")

    if contact:
        print(f"  联系人: {contact}")

    if extra:
        print(f"  {extra}")

    print("--- 请人工确认上述结果是否符合预期 ---\n")


def _ensure_ready():
    """确保微信窗口与配置就绪"""
    from controller import WeChatController

    ctrl = WeChatController()
    ctrl._ensure_ready()


def main():
    """主函数：运行 E2E 测试"""
    import argparse

    parser = argparse.ArgumentParser(description="发送文件 E2E 测试")
    parser.add_argument("--contact", default="小朵儿", help="测试联系人名称")
    parser.add_argument("--file", required=True, help="文件路径（必填）")
    parser.add_argument(
        "--step",
        choices=["send", "send-to-contact", "all"],
        default="all",
        help="测试步骤：send=仅 send_file，send-to-contact=仅 send_file_to_contact，all=全部",
    )

    args = parser.parse_args()
    file_path = args.file

    print("========== 发送文件功能 · 真实窗口 E2E 测试 ==========")
    print(f"联系人: {args.contact}")
    print(f"文件: {file_path}")

    if not os.path.exists(file_path):
        print(f"错误: 文件不存在: {file_path}")
        return

    try:
        try:
            _ensure_ready()
            print("微信与配置自检通过。\n")
        except Exception as e:
            print(f"准备阶段失败: {e}")
            print("请确保微信已打开、配置正确后再运行。")
            return

        if args.step in ["send", "all"]:
            print("执行 send_file（需要先手动打开目标联系人聊天窗口）...")
            run_real_send_file(file_path)

        if args.step in ["send-to-contact", "all"]:
            print(f"执行 send_file_to_contact（联系人: {args.contact}）...")
            run_real_send_file_to_contact(args.contact, file_path)

        print("测试完成。")

    except Exception as e:
        print(f"测试异常: {e}")
        raise


if __name__ == "__main__":
    if len(sys.argv) > 1 or os.environ.get("RUN_E2E_TEST"):
        main()
    else:
        import pytest

        pytest.main([__file__, "-v"])
