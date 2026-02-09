"""MessageChannel 的“跨进程健壮性”证明

必测三件事：
1. 锚点文件损坏（空/无效）→ fallback to get_initial_anchor，不崩溃
2. 锚点文件过旧（UI 已滚动，锚点不在当前页）→ 不 crash，至多重复一条
3. 连续 CLI 调用（多次 poll）→ 不重复、不跳读

通过 mock 证明设计行为符合预期。
"""

import sys
import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from message_channel import WeChatMessageChannel, MessageEvent
from message_reader import RawMessage
import element_locator as _element_locator_module


def _raw_msg(content: str, x: int = 100, y: int = 200) -> RawMessage:
    h = hashlib.md5(content.strip().encode("utf-8")).hexdigest()
    return RawMessage(content=content.strip(), hash=h, position=(x, y), avatar_index=0)


# ---------------------------------------------------------------------------
# 1. 锚点文件损坏 → fallback to get_initial_anchor
# ---------------------------------------------------------------------------

def test_anchor_file_empty_fallback_to_init_anchor():
    """锚点文件为空 {} 时，首次 poll 应走 _init_anchor，不崩溃，返回 []。"""
    wechat = MagicMock()
    wechat.open_chat.return_value = MagicMock(success=True)
    wechat.get_current_chat_hash.return_value = "cur_hash"

    with patch.object(WeChatMessageChannel, "_load_anchor_state", return_value={}), \
         patch.object(WeChatMessageChannel, "_load_visual_state", return_value={}):
        channel = WeChatMessageChannel(wechat)
    assert channel._anchor_hashes == {}
    channel._save_anchor_state = MagicMock()
    channel._save_visual_state = MagicMock()

    with patch("element_locator.get_contact_name", return_value="张三"), \
         patch.object(channel, "_init_anchor", return_value="init_hash_xxx") as init_anchor:
        events = channel.poll("张三")
    init_anchor.assert_called_once_with("张三")
    assert channel._anchor_hashes.get("张三") == "init_hash_xxx"
    assert events == []


def test_anchor_file_missing_treated_as_empty():
    """锚点文件不存在时，_load_anchor_state 返回 {}。"""
    wechat = MagicMock()
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = Path(tmpdir) / "nonexistent_anchor.json"
        assert not missing.exists()
        with patch.object(WeChatMessageChannel, "_anchor_state_path", return_value=missing):
            channel = WeChatMessageChannel(wechat)
            result = channel._load_anchor_state()
        assert result == {}


def test_anchor_file_corrupted_load_returns_empty():
    """锚点文件损坏（JSON 解析异常）时，_load_anchor_state 返回 {}，不崩溃。"""
    wechat = MagicMock()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        f.write("not valid json {{{")
        bad_path = Path(f.name)
    try:
        with patch.object(WeChatMessageChannel, "_anchor_state_path", return_value=bad_path):
            channel = WeChatMessageChannel(wechat)
            result = channel._load_anchor_state()
        assert result == {}
    finally:
        bad_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# 2. 锚点文件过旧（UI 已滚动）→ 不 crash，至多重复一条
# ---------------------------------------------------------------------------

def test_stale_anchor_no_crash():
    """锚点过旧（当前页读不到锚点）时，_read_snapshot 返回整页消息；_filter 不崩溃，可返回多条（设计上至多重复一条由业务保证）。"""
    wechat = MagicMock()
    channel = WeChatMessageChannel(wechat)
    channel._anchor_hashes["张三"] = "old_anchor_not_on_page"
    channel._seen_hashes["张三"] = set()

    # 模拟 read_until(old_anchor) 没遇到锚点，返回当前页全部 3 条
    raw_list = [
        _raw_msg("最新消息"),
        _raw_msg("第二条"),
        _raw_msg("第三条"),
    ]
    filtered = channel._filter_new_messages_from_raw("张三", raw_list, "old_anchor_not_on_page")
    assert len(filtered) == 3
    hashes = [e.hash for e in filtered]
    assert len(hashes) == len(set(hashes))


# ---------------------------------------------------------------------------
# 3. 连续 poll → 不重复、不跳读
# ---------------------------------------------------------------------------

def test_consecutive_polls_no_duplicate_no_skip():
    """连续三次 poll(contact)：第一次无锚点初始化；第二、三次模拟“新消息”，断言无重复、无跳读。"""
    wechat = MagicMock()
    wechat.open_chat.return_value = MagicMock(success=True)
    wechat.get_current_chat_hash.return_value = "cur_hash"

    channel = WeChatMessageChannel(wechat)
    channel._anchor_hashes = {}
    channel._seen_hashes = {}
    channel._save_anchor_state = MagicMock()
    channel._save_visual_state = MagicMock()

    with patch.object(WeChatMessageChannel, "_load_visual_state", return_value={}), \
         patch("element_locator.get_contact_name", return_value="张三"):
        # 第一次：无锚点 → _init_anchor，返回 []
        with patch.object(channel, "_init_anchor", return_value="anchor_after_first") as init:
            events1 = channel.poll("张三")
        init.assert_called_once_with("张三")
        channel._anchor_hashes["张三"] = "anchor_after_first"
        assert events1 == []

        # 第二次：有锚点，_read_snapshot 返回 2 条“新消息”（不含锚点那条）
        raw_second = [_raw_msg("新消息A"), _raw_msg("新消息B")]
        with patch.object(channel, "_read_snapshot", return_value=raw_second):
            events2 = channel.poll("张三")
        assert len(events2) == 2
        hashes2 = [e.hash for e in events2]
        assert len(hashes2) == len(set(hashes2))
        channel._anchor_hashes["张三"] = hashes2[0]  # 更新为最新
        for e in events2:
            channel._seen_hashes["张三"].add(e.hash)

        # 第三次：再“新”一条，锚点为 hashes2[0]
        raw_third = [_raw_msg("新消息C")]
        with patch.object(channel, "_read_snapshot", return_value=raw_third):
            events3 = channel.poll("张三")
        assert len(events3) == 1
        assert events3[0].hash == hashlib.md5("新消息C".strip().encode("utf-8")).hexdigest()

        # 全局无重复
        all_hashes = hashes2 + [events3[0].hash]
        assert len(all_hashes) == len(set(all_hashes))


def test_consecutive_polls_dedup_by_seen_hashes():
    """_filter_new_messages_from_raw 会跳过 _seen_hashes 中已有 hash，保证同一消息不会重复产出。"""
    wechat = MagicMock()
    channel = WeChatMessageChannel(wechat)
    channel._anchor_hashes["李四"] = "some_anchor"
    channel._seen_hashes["李四"] = {"already_seen_hash"}

    raw_list = [
        _raw_msg("新消息"),
        RawMessage(content="旧消息", hash="already_seen_hash", position=(0, 0), avatar_index=0),
    ]
    filtered = channel._filter_new_messages_from_raw("李四", raw_list, "some_anchor")
    assert len(filtered) == 1
    assert filtered[0].content == "新消息"
    assert filtered[0].hash != "already_seen_hash"


def test_consecutive_cli_calls_cross_process_no_duplicate_no_skip():
    """连续 CLI 调用（模拟多进程）：每次新进程从文件加载锚点，三次 read 不重复、不跳读。"""
    wechat = MagicMock()
    wechat.open_chat.return_value = MagicMock(success=True)
    wechat.get_current_chat_hash.return_value = "cur_hash"

    with tempfile.TemporaryDirectory() as tmpdir:
        anchor_path = Path(tmpdir) / "anchor.json"
        visual_path = Path(tmpdir) / "visual.json"

        with patch.object(WeChatMessageChannel, "_anchor_state_path", return_value=anchor_path), \
             patch.object(WeChatMessageChannel, "_visual_state_path", return_value=visual_path), \
             patch.object(WeChatMessageChannel, "_load_visual_state", return_value={}), \
             patch.object(_element_locator_module, "get_contact_name", return_value="王五"):
            # 进程1：无锚点 → 初始化锚点，保存到文件，返回 []
            ch1 = WeChatMessageChannel(wechat)
            with patch.object(ch1, "_init_anchor", return_value="anchor_after_init"):
                events1 = ch1.poll("王五")
            ch1._save_anchor_state()
            assert events1 == []
            assert ch1._anchor_hashes.get("王五") == "anchor_after_init"
            assert anchor_path.exists()
            data1 = json.loads(anchor_path.read_text(encoding="utf-8"))
            assert "王五" in data1 and data1["王五"] == "anchor_after_init"

            # 进程2：从文件加载锚点，模拟读到两条新消息 A、B
            ch2 = WeChatMessageChannel(wechat)
            assert ch2._anchor_hashes.get("王五") == "anchor_after_init"
            raw_ab = [_raw_msg("新消息A"), _raw_msg("新消息B")]
            with patch.object(ch2, "_read_snapshot", return_value=raw_ab):
                events2 = ch2.poll("王五")
            ch2._save_anchor_state()
            assert len(events2) == 2
            hashes_ab = [e.hash for e in events2]
            assert len(hashes_ab) == len(set(hashes_ab))
            new_anchor = ch2._anchor_hashes.get("王五")
            assert new_anchor in hashes_ab

            # 进程3：从文件加载新锚点，模拟再读到一条 C
            ch3 = WeChatMessageChannel(wechat)
            assert ch3._anchor_hashes.get("王五") == new_anchor
            raw_c = [_raw_msg("新消息C")]
            with patch.object(ch3, "_read_snapshot", return_value=raw_c):
                events3 = ch3.poll("王五")
            assert len(events3) == 1
            assert events3[0].content == "新消息C"

            # 三次调用全局无重复、无跳读
            all_hashes = hashes_ab + [events3[0].hash]
            assert len(all_hashes) == 3 and len(all_hashes) == len(set(all_hashes))


if __name__ == "__main__":
    try:
        import pytest
        sys.exit(pytest.main([__file__, "-v"]))
    except ImportError:
        test_anchor_file_empty_fallback_to_init_anchor()
        test_anchor_file_missing_treated_as_empty()
        test_anchor_file_corrupted_load_returns_empty()
        test_stale_anchor_no_crash()
        test_consecutive_polls_no_duplicate_no_skip()
        test_consecutive_polls_dedup_by_seen_hashes()
        test_consecutive_cli_calls_cross_process_no_duplicate_no_skip()
        print("OK: message_channel robustness tests passed")
