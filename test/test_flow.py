"""Flow 功能测试

对各流程（open_chat、send_message、send_text_to_contact、read_new_messages、get_initial_anchor）
进行专门测试。通过 mock 窗口/截图/定位/操作，在无真实微信环境下验证流程逻辑与返回结构。
"""

import sys
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from models import FlowResult, TaskType, LocateResult, LocateMethod


def _make_locate_result(x: int, y: int, success: bool = True) -> LocateResult:
    return LocateResult(success=success, x=x, y=y, confidence=0.9, method=LocateMethod.TEMPLATE_MATCH)


# ---------------------------------------------------------------------------
# open_chat
# ---------------------------------------------------------------------------

def test_open_chat_success_when_already_on_contact():
    """open_chat：当前已是目标联系人时，直接返回成功，不点击列表。"""
    from flows import open_chat

    hwnd = 12345
    with patch("flows.get_wechat_hwnd", return_value=hwnd), \
         patch("flows.activate_window", return_value=True), \
         patch("flows.get_contact_name", return_value="  张三  "):
        result = open_chat("张三", require_red_point=False)
    assert result.success is True
    assert result.task_type == TaskType.OPEN_CHAT
    assert result.data is not None
    assert result.data.get("skipped") is True
    assert result.execution_time >= 0


def test_open_chat_fails_when_no_hwnd():
    """open_chat：无窗口句柄时返回失败。"""
    from flows import open_chat

    with patch("flows.get_wechat_hwnd", side_effect=Exception("未找到窗口")):
        result = open_chat("张三", require_red_point=False)
    assert result.success is False
    assert result.task_type == TaskType.OPEN_CHAT
    assert "微信窗口" in (result.error_message or "")


def test_open_chat_fails_when_activate_fails():
    """open_chat：激活窗口失败时返回失败。"""
    from flows import open_chat

    with patch("flows.get_wechat_hwnd", return_value=12345), \
         patch("flows.activate_window", return_value=False):
        result = open_chat("张三", require_red_point=False)
    assert result.success is False
    assert "激活" in (result.error_message or "")


def test_open_chat_success_when_switch_contact_mocked():
    """open_chat：需要切换联系人时，mock 定位与点击成功则返回成功。"""
    from flows import open_chat

    hwnd = 12345
    # 当前联系人不是目标，需要定位并点击
    positions = {
        "profile_photo_in_list": _make_locate_result(100, 200),
        "new_message_red_point": _make_locate_result(110, 190),
    }
    with patch("flows.get_wechat_hwnd", return_value=hwnd), \
         patch("flows.activate_window", return_value=True), \
         patch("flows.get_contact_name", return_value="李四"), \
         patch("flows.capture_window", return_value=np.zeros((800, 1200, 3), dtype=np.uint8)), \
         patch("flows.locate_all_elements", return_value=positions), \
         patch("flows.click", return_value=True), \
         patch("flows.human_delay"):
        result = open_chat("张三", require_red_point=True)
    assert result.success is True
    assert result.task_type == TaskType.OPEN_CHAT
    assert result.data is None or result.data.get("skipped") is not True


def test_open_chat_fails_when_no_profile_photo():
    """open_chat：未找到联系人头像时返回失败。"""
    from flows import open_chat

    positions = {"profile_photo_in_list": _make_locate_result(0, 0, success=False)}
    with patch("flows.get_wechat_hwnd", return_value=12345), \
         patch("flows.activate_window", return_value=True), \
         patch("flows.get_contact_name", return_value="李四"), \
         patch("flows.capture_window", return_value=np.zeros((800, 1200, 3), dtype=np.uint8)), \
         patch("flows.locate_all_elements", return_value=positions), \
         patch("flows.human_delay"):
        result = open_chat("张三", require_red_point=False)
    assert result.success is False
    assert "头像" in (result.error_message or "")


# ---------------------------------------------------------------------------
# send_message
# ---------------------------------------------------------------------------

def test_send_message_success_mocked():
    """send_message：mock 输入框定位与操作成功时返回成功。"""
    from flows import send_message

    hwnd = 12345
    positions = {"input_box_anchor": _make_locate_result(600, 750)}
    with patch("flows.get_wechat_hwnd", return_value=hwnd), \
         patch("flows.activate_window", return_value=True), \
         patch("flows.capture_window", return_value=np.zeros((800, 1200, 3), dtype=np.uint8)), \
         patch("flows.locate_all_elements", return_value=positions), \
         patch("flows.click", return_value=True), \
         patch("flows.hotkey", return_value=True), \
         patch("flows.paste_text", return_value=True), \
         patch("flows.save_chat_state"), \
         patch("flows.human_delay"):
        result = send_message("你好")
    assert result.success is True
    assert result.task_type == TaskType.SEND_MESSAGE
    assert result.data is not None and result.data.get("message") == "你好"


def test_send_message_fails_when_no_input_box():
    """send_message：未找到输入框时返回失败。"""
    from flows import send_message

    positions = {"input_box_anchor": _make_locate_result(0, 0, success=False)}
    with patch("flows.get_wechat_hwnd", return_value=12345), \
         patch("flows.activate_window", return_value=True), \
         patch("flows.capture_window", return_value=np.zeros((800, 1200, 3), dtype=np.uint8)), \
         patch("flows.locate_all_elements", return_value=positions), \
         patch("flows.human_delay"):
        result = send_message("你好")
    assert result.success is False
    assert "输入框" in (result.error_message or "")


# ---------------------------------------------------------------------------
# send_text_to_contact
# ---------------------------------------------------------------------------

def test_send_text_to_contact_success_mocked():
    """send_text_to_contact：open_chat + send_message 均成功时返回成功。"""
    from flows import send_text_to_contact

    with patch("flows.open_chat", return_value=FlowResult(
        success=True, task_type=TaskType.OPEN_CHAT, execution_time=0.1, data={"contact_name": "张三"}
    )), \
         patch("flows.send_message", return_value=FlowResult(
             success=True, task_type=TaskType.SEND_MESSAGE, execution_time=0.2, data={"message": "你好"}
         )):
        result = send_text_to_contact("张三", "你好")
    assert result.success is True
    assert result.task_type == TaskType.SEND_MESSAGE
    assert result.data is not None
    assert result.data.get("contact_name") == "张三"
    assert result.data.get("message") == "你好"


def test_send_text_to_contact_fails_when_open_chat_fails():
    """send_text_to_contact：open_chat 失败时返回失败。"""
    from flows import send_text_to_contact

    with patch("flows.open_chat", return_value=FlowResult(
        success=False, task_type=TaskType.OPEN_CHAT, execution_time=0.1, error_message="打开失败"
    )):
        result = send_text_to_contact("张三", "你好")
    assert result.success is False
    assert "打开" in (result.error_message or "")


# ---------------------------------------------------------------------------
# read_new_messages
# ---------------------------------------------------------------------------

def test_read_new_messages_success_mocked():
    """read_new_messages：mock 头像与 copy_text_at，返回消息列表结构正确。"""
    from flows import read_new_messages

    hwnd = 12345
    # 两个头像（两条消息），从下到上
    avatar1 = _make_locate_result(200, 600)
    avatar2 = _make_locate_result(200, 500)
    positions = {"profile_photo_in_chat": [avatar1, avatar2]}
    texts = ["最新消息", "上一条消息"]
    call_count = [0]

    def fake_copy(x, y, win, double_click=False):
        call_count[0] += 1
        return texts[call_count[0] - 1] if call_count[0] <= len(texts) else ""

    with patch("flows.get_wechat_hwnd", return_value=hwnd), \
         patch("flows.activate_window", return_value=True), \
         patch("flows.capture_window", return_value=np.zeros((800, 1200, 3), dtype=np.uint8)), \
         patch("flows.locate_all_elements", return_value=positions), \
         patch("flows.copy_text_at", side_effect=fake_copy), \
         patch("flows.human_delay"):
        result = read_new_messages(contact_name="张三", anchor_hash=None)
    assert result.success is True
    assert result.task_type == TaskType.READ_MESSAGES
    assert result.data is not None
    assert "messages" in result.data
    assert "count" in result.data
    assert "anchor_hash" in result.data
    assert result.data["count"] >= 0


def test_read_new_messages_fails_when_no_avatars():
    """read_new_messages：未找到聊天区域头像时返回失败。"""
    from flows import read_new_messages

    positions = {"profile_photo_in_chat": []}
    with patch("flows.get_wechat_hwnd", return_value=12345), \
         patch("flows.activate_window", return_value=True), \
         patch("flows.capture_window", return_value=np.zeros((800, 1200, 3), dtype=np.uint8)), \
         patch("flows.locate_all_elements", return_value=positions), \
         patch("flows.human_delay"):
        result = read_new_messages(anchor_hash=None)
    assert result.success is False
    assert "头像" in (result.error_message or "")


def test_read_new_messages_anchor_hash_accepts_text():
    """read_new_messages：anchor_hash 可传文本，内部会转成 hash 比较。"""
    from flows import read_new_messages

    anchor_text = "锚点内容"
    anchor_hash = hashlib.md5(anchor_text.strip().encode("utf-8")).hexdigest()
    avatar = _make_locate_result(200, 600)
    positions = {"profile_photo_in_chat": [avatar]}
    call_count = [0]

    def fake_copy(x, y, win, double_click=False):
        call_count[0] += 1
        # 第一条即锚点内容，应匹配后停止
        return anchor_text if call_count[0] == 1 else "其他"

    with patch("flows.get_wechat_hwnd", return_value=12345), \
         patch("flows.activate_window", return_value=True), \
         patch("flows.capture_window", return_value=np.zeros((800, 1200, 3), dtype=np.uint8)), \
         patch("flows.locate_all_elements", return_value=positions), \
         patch("flows.copy_text_at", side_effect=fake_copy), \
         patch("flows.human_delay"):
        result = read_new_messages(anchor_hash=anchor_text)
    assert result.success is True
    assert result.data is not None
    # 匹配到锚点即停，新消息列表应不包含锚点那条
    assert result.data.get("anchor_matched") is True or result.data["count"] == 0


# ---------------------------------------------------------------------------
# get_initial_anchor
# ---------------------------------------------------------------------------

def test_get_initial_anchor_fails_without_contact_name():
    """get_initial_anchor：未提供 contact_name 时返回失败（入口即校验，不调用窗口）。"""
    from flows import get_initial_anchor

    result = get_initial_anchor(contact_name=None)
    assert result.success is False
    assert "contact_name" in (result.error_message or "").lower()


def test_get_initial_anchor_success_mocked():
    """get_initial_anchor：mock 当前已是目标联系人、定位到头像、复制成功时返回成功。"""
    from flows import get_initial_anchor

    with patch("flows.get_wechat_hwnd", return_value=12345), \
         patch("flows.get_contact_name", return_value="张三"), \
         patch("flows.activate_window", return_value=True), \
         patch("flows.capture_window", return_value=np.zeros((800, 1200, 3), dtype=np.uint8)), \
         patch("flows.locate_all_elements", return_value={
             "profile_photo_in_chat": [_make_locate_result(200, 600)]
         }), \
         patch("flows.copy_text_at", return_value="最下面一条消息"), \
         patch("flows.human_delay"):
        result = get_initial_anchor(contact_name="张三")
    assert result.success is True
    assert result.data is not None
    assert "anchor_hash" in result.data
    assert result.data.get("source") == "current_message"


# ---------------------------------------------------------------------------
# FlowResult / TaskType 结构
# ---------------------------------------------------------------------------

def test_flow_result_has_required_fields():
    """FlowResult 包含 success、task_type、execution_time 等必要字段。"""
    r = FlowResult(success=True, task_type=TaskType.OPEN_CHAT, execution_time=1.0, data={})
    assert r.success is True
    assert r.task_type == TaskType.OPEN_CHAT
    assert r.execution_time == 1.0
    assert r.error_message is None


if __name__ == "__main__":
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        # 无 pytest 时逐个执行
        test_open_chat_success_when_already_on_contact()
        test_open_chat_fails_when_no_hwnd()
        test_open_chat_fails_when_activate_fails()
        test_open_chat_success_when_switch_contact_mocked()
        test_open_chat_fails_when_no_profile_photo()
        test_send_message_success_mocked()
        test_send_message_fails_when_no_input_box()
        test_send_text_to_contact_success_mocked()
        test_send_text_to_contact_fails_when_open_chat_fails()
        test_read_new_messages_success_mocked()
        test_read_new_messages_fails_when_no_avatars()
        test_read_new_messages_anchor_hash_accepts_text()
        test_get_initial_anchor_fails_without_contact_name()
        test_get_initial_anchor_success_mocked()
        test_flow_result_has_required_fields()
        print("OK: all flow tests passed")
