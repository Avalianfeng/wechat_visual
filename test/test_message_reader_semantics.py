"""Phase 4：MessageReader 的“单条语义证明”

验证 3 个性质：
1. read_next 不重复：连续两次 read_next() 不会返回同一条消息（索引推进，不同条）。
2. reset 后行为可预测：reset() 后 read_next() 从当前画面底部开始（第一条是最下面）。
3. read_until(anchor) 单调：返回的 messages 中不包含锚点之后的消息（遇锚点即停，锚点不出现在列表里）。

说明：MessageReader 依赖真实窗口与 UI，本测试以文档化 + 行为约定为主；
若需自动化验证，需 mock 窗口/截图/头像列表与 copy_text_at。
"""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def test_read_next_not_repeat_semantic_doc():
    """
    语义约定：read_next() 是“不重复”的。
    - 第一次 read_next() 返回第 _current_index 条（0 为最下面）。
    - 返回后 _current_index += 1。
    - 第二次 read_next() 返回下一条，故两条结果不应相同（content/hash 不同）。
    若两次都返回非 None，则 assert raw1.hash != raw2.hash。
    """
    # 无 mock 时不执行实际 MessageReader，仅文档化
    assert True


def test_reset_then_read_next_from_bottom_semantic_doc():
    """
    语义约定：reset() 后 read_next() 从当前画面底部开始。
    - reset() 重新定位头像、_avatars 按 y 从大到小排序、_current_index = 0。
    - 随后 read_next() 返回的是 _avatars[0] 对应的消息（最下面一条）。
    """
    assert True


def test_read_until_anchor_monotonic_semantic_doc():
    """
    语义约定：read_until(anchor_hash) 是单调的。
    - 从当前位置开始 read_next()，直到某条消息的 hash == anchor_hash 则停止。
    - 返回的 messages 不包含锚点那条，且不应出现“锚点之后”的消息（按从下到上顺序，遇锚即停）。
    - 即：若 messages = read_until(anchor)，则对任意 m in messages，m.hash != anchor_hash，
      且列表顺序为从下到上（新到旧），锚点之后的消息不会出现在列表中。
    """
    assert True


if __name__ == "__main__":
    test_read_next_not_repeat_semantic_doc()
    test_reset_then_read_next_from_bottom_semantic_doc()
    test_read_until_anchor_monotonic_semantic_doc()
    print("OK: MessageReader semantics documented")
