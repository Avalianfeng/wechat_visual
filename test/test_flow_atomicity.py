"""Phase 3：流程（flows）在真实窗口中的 E2E 测试

在真实（可最小化）微信窗口中执行各 flow，不做 mock。
执行结果由人工判断是否完成；本脚本只负责执行并打印结果。

运行方式（二选一，推荐 -m 以正确解析包内相对导入）：
  python -m wechat.test.test_flow_atomicity [--contact 联系人] [--message 测试内容] [--steps open|send|read|anchor|all]
  或在项目根上一级执行：  python -m wechat.test.test_flow_atomicity
  直接运行脚本时，会自动重定向为上述 -m 方式执行。
若只执行 read/anchor，请先确保当前窗口已是目标联系人（或先执行 open）。

原子性含义（供人工验证）：
  在任意一步抛异常后，再次调用同一个 flow，成功率不降低。
"""

import sys
import os
import argparse
import runpy
from pathlib import Path
from typing import Optional

# 直接以脚本运行（非 python -m wechat.test.test_flow_atomicity）时，包内相对导入会报错，
# 故自举为以包模块方式执行。
if __name__ == "__main__" and not __package__:
    _project_root = Path(__file__).resolve().parent.parent
    _parent = _project_root.parent
    if str(_parent) not in sys.path:
        sys.path.insert(0, str(_parent))
    runpy.run_module("wechat.test.test_flow_atomicity", run_name="__main__")
    sys.exit(0)

_project_root = Path(__file__).resolve().parent.parent

# 默认测试用联系人与消息（可被环境变量或命令行覆盖）
DEFAULT_CONTACT = os.environ.get("TEST_FLOW_CONTACT", "小朵儿")
DEFAULT_MESSAGE = os.environ.get("TEST_FLOW_MESSAGE", "[E2E] 流程原子性测试消息")


def _ensure_ready():
    """确保微信窗口与配置就绪；失败则抛异常。"""
    from wechat.controller import WeChatController, WeChatNotReadyError
    ctrl = WeChatController()
    ctrl._ensure_ready()


def _run_open_chat(contact: str):
    """真实执行 open_chat(contact)。返回 FlowResult，不抛异常。"""
    from wechat.flows import open_chat
    # require_red_point=False 便于在无红点时也能切换（测试用）
    result = open_chat(contact, require_red_point=False)
    return result


def _run_send_message(text: str):
    """真实执行 send_message(text)（假定当前已在聊天窗口）。"""
    from wechat.flows import send_message
    return send_message(text)


def _run_send_text_to_contact(contact: str, text: str):
    """真实执行 send_text_to_contact(contact, text)。"""
    from wechat.flows import send_text_to_contact
    return send_text_to_contact(contact, text)


def _run_read_new_messages(contact_name: Optional[str] = None, anchor_hash: Optional[str] = None):
    """真实执行 read_new_messages(contact_name=..., anchor_hash=...)。"""
    from wechat.flows import read_new_messages
    return read_new_messages(contact_name=contact_name, anchor_hash=anchor_hash)


def _run_get_initial_anchor(contact: str):
    """真实执行 get_initial_anchor(contact_name=...)。"""
    from wechat.flows import get_initial_anchor
    return get_initial_anchor(contact_name=contact)


def _print_result(step_name: str, result, contact: Optional[str] = None, extra: Optional[str] = None):
    """统一打印某步的执行结果，便于人工判断。"""
    from wechat.models import FlowResult
    if not isinstance(result, FlowResult):
        print(f"[{step_name}] 异常: 返回类型不是 FlowResult: {type(result)}")
        return
    status = "成功" if result.success else "失败"
    print(f"\n--- [{step_name}] {status} (耗时 {result.execution_time:.2f}s) ---")
    if result.success and result.data:
        for k, v in (result.data or {}).items():
            if k == "messages" and isinstance(v, list):
                print(f"  {k}: 共 {len(v)} 条")
            else:
                print(f"  {k}: {v}")
    if not result.success and result.error_message:
        print(f"  错误: {result.error_message}")
    if extra:
        print(f"  {extra}")
    print("--- 请人工确认上述结果是否符合预期 ---\n")


def run_real_open_chat(contact: str):
    """执行 open_chat，打印结果。"""
    result = _run_open_chat(contact)
    _print_result("open_chat", result, contact=contact, extra=f"目标联系人: {contact}")


def run_real_send_message(message: str):
    """执行 send_message（当前已在聊天窗口），打印结果。"""
    result = _run_send_message(message)
    _print_result("send_message", result, extra=f"发送内容: {message}")


def run_real_send_text_to_contact(contact: str, message: str):
    """执行 send_text_to_contact，打印结果。"""
    result = _run_send_text_to_contact(contact, message)
    _print_result("send_text_to_contact", result, contact=contact, extra=f"内容: {message}")


def run_real_read_new_messages(contact: Optional[str] = None, anchor_hash: Optional[str] = None):
    """执行 read_new_messages，打印结果。"""
    result = _run_read_new_messages(contact_name=contact, anchor_hash=anchor_hash)
    _print_result("read_new_messages", result, contact=contact)


def run_real_get_initial_anchor(contact: str):
    """执行 get_initial_anchor，打印结果。"""
    result = _run_get_initial_anchor(contact)
    _print_result("get_initial_anchor", result, contact=contact)


def run_all_real_flows(contact: str, message: str, steps: list):
    """
    按顺序执行指定的真实 flow；每步只打印结果，由人工判断。
    steps: ["open", "send", "read", "anchor"] 的子集或全部
    """
    print("========== 流程原子性 · 真实窗口 E2E ==========")
    print(f"联系人: {contact}, 测试消息: {message}")
    print(f"执行步骤: {steps}")
    print("结果由人工判断，本脚本不自动断言成功/失败。\n")

    try:
        _ensure_ready()
        print("微信与配置自检通过。\n")
    except Exception as e:
        print(f"准备阶段失败: {e}")
        print("请确保微信已打开、配置正确后再运行。")
        return

    if "open" in steps:
        run_real_open_chat(contact)
    if "send" in steps:
        run_real_send_text_to_contact(contact, message)
    if "read" in steps:
        run_real_read_new_messages(contact=contact)
    if "anchor" in steps:
        run_real_get_initial_anchor(contact)

    print("========== 全部步骤已执行，请根据上方输出人工判断是否通过 ==========")


def main():
    parser = argparse.ArgumentParser(
        description="在真实微信窗口中执行 flow E2E 测试，结果由人工判断"
    )
    parser.add_argument(
        "--contact", "-c",
        default=DEFAULT_CONTACT,
        help=f"测试联系人（默认: {DEFAULT_CONTACT}）",
    )
    parser.add_argument(
        "--message", "-m",
        default=DEFAULT_MESSAGE,
        help="发送测试消息内容",
    )
    parser.add_argument(
        "--steps", "-s",
        default="all",
        help="要执行的步骤: open, send, read, anchor 的逗号分隔，或 all（默认: all）",
    )
    args = parser.parse_args()

    if args.steps.strip().lower() == "all":
        steps = ["open", "send", "read", "anchor"]
    else:
        steps = [s.strip().lower() for s in args.steps.split(",") if s.strip()]
        allowed = {"open", "send", "read", "anchor"}
        steps = [s for s in steps if s in allowed]
        if not steps:
            print("未指定有效步骤，使用: open,send,read,anchor 或 all")
            return

    run_all_real_flows(contact=args.contact, message=args.message, steps=steps)


if __name__ == "__main__":
    main()
