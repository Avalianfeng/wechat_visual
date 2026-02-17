"""微信独立工具 - 命令行入口（纯净工具，不依赖本仓库内 AI 配置）

本模块提供按次调用的 CLI：每次执行为独立进程，跨进程状态通过 debug/ 下的
message_anchor_state.json、visual_state.json 等持久化，适合机器人/后台轮询与发送。

推荐入口：
    python -m wechat.cli <子命令> [参数...]
    python -m wechat.cli --debug <子命令>   # 输出详细日志

常用示例：
    python -m wechat.cli read 张三           # 轮询并打印张三的新消息（安全模式，更新锚点）
    python -m wechat.cli read-new            # 有红点则打开并读，输出联系人及新消息
    python -m wechat.cli send 张三 你好      # 向张三发送文本
    python -m wechat.cli send-current 你好   # 向当前聊天窗口直接发送（不切换联系人）
    python -m wechat.cli contacts            # 列出已配置联系人
    python -m wechat.cli current             # 显示当前聊天窗口联系人
    python -m wechat.cli check-new           # 仅扫描红点，输出有红点的联系人名
    python -m wechat.cli open 张三 --method search  # 打开张三聊天（搜索方式）
    python -m wechat.cli update-hash         # 手动更新当前联系人的视觉 hash
    python -m wechat.cli watch 张三          # 持续监视张三新消息（基于 hash 检测）
    python -m wechat.cli help [topic]        # 详细帮助（topic: overview/prereq/read/...）
"""

import sys
import argparse
import logging
from pathlib import Path

# 确保项目根目录在路径中（wechat 目录本身，适配从大项目复制出的独立目录）
_project_root = Path(__file__).resolve().parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

logger = logging.getLogger(__name__)

def _configure_logging(debug: bool) -> None:
    """
    配置根日志级别与格式。

    - debug=False（默认）：仅 CRITICAL，使命令输出尽量静默，只保留最终 print 结果。
    - debug=True：INFO 级别，便于排查定位/流程问题。使用 force=True 覆盖已有 handler，
      适配被外部进程或测试框架导入时的重复 basicConfig。
    """
    level = logging.INFO if debug else logging.CRITICAL
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - [%(levelname)s] - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,  # 覆盖可能已存在的 handler（适配被外部进程/测试框架导入）
    )
    # 明确设置根 logger 等级（双保险）
    logging.getLogger().setLevel(level)

# 详细帮助文本：供 help 子命令与机器人/后台集成查阅，比 argparse -h 更完整（含前置条件、行为、返回码）。
_DETAILED_HELP = {
    "overview": """\
微信 CLI（纯传输工具）详细说明

定位：只做「打开聊天 → 发消息 / 读消息」的 UI 自动化，不包含 AI、记忆与决策。
特点：按次调用（一次命令一次进程）；跨进程状态通过 debug/ 下的状态文件持久化。

推荐入口：
  python -m wechat.cli <子命令> [参数...]
  python -m wechat.cli --debug <子命令> [参数...]   # 输出详细日志

常用场景（机器人/后台）：
  - 轮询：python -m wechat.cli read <contact>
  - 有红点则打开并读：python -m wechat.cli read-new
  - 发送：python -m wechat.cli send <contact> <text>
  - 直接向当前窗口发送：python -m wechat.cli send-current <text>
  - 发送文件：python -m wechat.cli send-file <contact> <路径>
  - 打开：python -m wechat.cli open <contact> --method search
  - 检查是否有新消息红点：python -m wechat.cli check-new（默认打开有红点联系人；加 --no-open 仅扫描）
  - 直接读新消息（用锚点停止，读后更新锚点与画面 hash）：python -m wechat.cli read-direct <contact>
  - 手动刷新视觉 hash：python -m wechat.cli update-hash
  - 持续监视某个联系人：python -m wechat.cli watch <contact>
""",
    "prereq": """\
前置条件（运行环境必须满足）

1) 微信 PC 客户端已登录且窗口存在（标题含“微信”），且能被激活到前台。
2) 必须能访问图形界面/屏幕：本工具通过截图、模板匹配、模拟点击/输入与微信交互。
3) 模板文件齐全：assets/templates/ 下必须存在 config.REQUIRED_TEMPLATES 对应文件。
4) 微信界面语言：必须为简体中文（zh_CN）。
5) 窗口大小：>= 800x600（过小会导致定位失败）。

环境变量与 .env（推荐）
  - 项目根目录的 .env 会在导入 config 时自动加载（python-dotenv）。
  - WECHAT_ME_CONTACT：把某个联系人声明为“我”（用于部分测试/逻辑过滤）。
  - ALIYUN_OCR_APPCODE：可选，阿里云 OCR APPCODE；未配置则回退到 Tesseract（如已安装）。
""",
    "read": """\
read：轮询并打印新消息（不调用 AI）

用法：
  python -m wechat.cli read <contact>
  python -m wechat.cli read              # 不安全模式：使用当前窗口联系人

行为：
  - read <contact>：安全模式（推荐）。会打开到目标联系人，读取锚点之上的新消息，并更新锚点。
  - read（不带 contact）：不安全模式。仅用于临时手动查看：不更新锚点，UI 切换会丢弃本轮。

输出（stdout）：
  - 有新消息：逐行输出 “[联系人] role: content”
  - 无新消息：输出 “[联系人] 暂无新消息”

返回码：
  - 0：命令执行成功（即使无新消息）
  - 1：失败（配置校验失败 / 打开窗口失败 / 读取异常等）
""",
    "read-new": """\
read-new：先获取有红点的联系人，再打开并读新消息，输出联系人姓名和新消息

用法：
  python -m wechat.cli read-new

行为：
  - 调用 check-new 逻辑获取存在新消息红点的联系人列表
  - 对每个联系人：打开其聊天窗口 → 执行 poll 读取新消息并更新锚点
  - 输出：对每个联系人先打印「联系人: <名称>」，再逐行打印 "[名称] role: content"

返回码：
  - 0：执行成功（无红点时输出「暂无新消息」）
  - 1：配置/窗口/定位异常
""",
    "send": """\
send：向指定联系人发送文本

用法：
  python -m wechat.cli send <contact> <text>

建议用法：
  - 机器人/后台推荐使用此命令：它会通过 open_chat(contact) 确保窗口切到目标联系人再发送。

返回码：
  - 0：发送成功
  - 1：发送失败
""",
    "send-current": """\
send-current：向「当前聊天窗口」直接发送文本（不检查联系人）

用法：
  python -m wechat.cli send-current <text>

行为与建议：
  - 不会尝试 open_chat，也不会校验当前联系人是否为某个目标，只是：
      * 激活微信窗口
      * 定位输入框
      * 清空并粘贴文本
      * 按 Enter 发送
  - 适合：你已经手动把聊天窗口切到目标联系人时的快速调试 / 手工辅助。
  - 不建议在「机器人后台」盲目使用（那里更推荐显式使用 send <contact> <text>）。

返回码：
  - 0：发送成功
  - 1：失败（无法激活窗口 / 找不到输入框 / 粘贴或发送出错）
""",
    "send-file": """\
send-file：向指定联系人发送文件（统一复制粘贴，支持图片与普通文件）

用法：
  python -m wechat.cli send-file <contact> <路径>

行为：
  - 会先通过 open_chat(contact) 确保窗口切到目标联系人
  - 定位输入框并点击，按类型复制到剪贴板（CF_DIB/CF_HDROP）
  - 粘贴（Ctrl+V）后按 Enter 发送
  - 发送成功后自动更新 UI hash

支持：JPG/PNG/PDF/DOCX/MD 等，路径含中文或空格时建议加引号

返回码：
  - 0：发送成功
  - 1：发送失败（文件不存在、定位失败等）

示例：
  python -m wechat.cli send-file 张三 "D:\\学习\\人像摄影.md"
""",
    "contacts": """\
contacts：列出 contact_config.json 中配置的联系人

用法：
  python -m wechat.cli contacts

备注：
  - 该命令不做模板/窗口等硬校验；仅依赖 contact_config.json 可读。
""",
    "current": """\
current：显示当前聊天窗口联系人名称

用法：
  python -m wechat.cli current

备注：
  - 依赖当前窗口处于聊天界面，且 OCR/定位成功。
""",
    "check-new": """\
check-new：扫描新消息红点，输出存在红点的联系人名称

用法：
  python -m wechat.cli check-new
  python -m wechat.cli check-new --no-open

行为：
  - 直接搜索联系人列表中的新消息红点（头像右上角），逐行输出对应联系人名称；无则输出「暂无新消息红点」。
  - 默认会打开有红点的联系人（点击一下进入聊天）；加 --no-open 则只扫描不打开。

返回码：
  - 0：执行成功（无论是否有红点）
  - 1：配置/窗口/定位异常
""",
    "read-direct": """\
read-direct：直接读当前可见页的新消息（用信息锚点做停止，读后自动更新锚点与画面 hash）

用法：
  python -m wechat.cli read-direct <联系人>

行为：
  - 打开该联系人聊天窗口后，从底部开始读，遇到已有锚点（信息 hash）即停止，只返回新消息。
  - 无锚点时读满当前页；读完后自动更新该联系人的信息锚点与画面区域 hash，下次只读增量。
  - 输出格式与 read 相同：[联系人] role: content，顺序为先发→后发。

返回码：
  - 0：成功
  - 1：配置/打开/读取异常
""",
    "open": """\
open：打开指定联系人的聊天窗口（两种方式）

用法：
  python -m wechat.cli open <contact> --method list
  python -m wechat.cli open <contact> --method search

说明：
  - list：列表头像点击方式（依赖左侧列表头像定位；联系人不在可视列表时可能失败）
  - search：搜索框方式（更“保险”）：点击搜索框→输入联系人→回车
""",
    "update-hash": """\
update-hash：手动更新“当前联系人”的视觉 hash（含截图与状态信息），并返回当前联系人名

用法：
  python -m wechat.cli update-hash

输出（stdout，三行，便于机器人解析）：
  1) <当前联系人名>
  2) hash=<pHash字符串或空>
  3) screenshot=<debug目录下截图路径>

返回码：
  - 0：hash 计算成功并写入 debug/visual_state.json
  - 1：失败（无法识别联系人 / 无法计算 hash 等）
""",
    "watch": """\
watch：持续监视指定联系人的新消息（基于 UI hash 检测）

用法：
  python -m wechat.cli watch <contact>
  python -m wechat.cli --debug watch <contact>

行为：
  1) 启动时，先执行一次完整的轮询（等价于 read <contact>，含锚点与视觉状态更新）。
  2) 之后进入循环，仅使用“视觉 hash 检测”来判断是否有新消息：
     - 每隔一段时间（默认 2 秒，可通过环境变量 WECHAT_WATCH_INTERVAL_SECONDS 调整）
     - 调用 has_new_message(contact) 判断聊天区域是否发生变化
     - 若未变化则继续等待
     - 若发生变化，则再调用一次 poll(contact) 读取真正的新消息并退出

输出与返回：
  - 默认（无 --debug）：启动后静默等待，直到检测到新消息并读出，最后只打印新消息行并退出。
  - 加 --debug：在等待过程中会打印 hash 检测与轮询状态日志，方便排查。
  - 返回码：0 表示执行成功（即使最终无新消息，也视为成功结束），1 表示执行过程出错。
""",
}


def cmd_read(args):
    """
    轮询新消息并打印（不调用 AI）。

    - 安全模式（推荐）：read <contact>，会打开目标聊天、读取锚点之上的新消息并更新锚点。
    - 不安全模式：read 不传 contact，使用当前窗口联系人，仅读取不更新锚点；适合临时查看。
    返回码：0 成功（含无新消息），1 配置/窗口/读取异常。
    """
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    from controller import WeChatController
    from message_channel import WeChatMessageChannel

    contact = args.contact
    update_anchor = True  # 安全模式：更新锚点
    if not contact:
        # 不安全模式：从当前窗口推断联系人，仅读取、不更新锚点；UI 不一致则 message_channel 内丢弃
        try:
            from element_locator import get_contact_name
            from screen import get_wechat_hwnd
            from actions import activate_window
            import time
            hwnd = get_wechat_hwnd()
            if activate_window(hwnd):
                time.sleep(0.3)
                contact = get_contact_name()
                if contact:
                    contact = contact.strip()
            if contact:
                update_anchor = False
                logger.info("read 未指定 contact，使用当前窗口联系人（不安全模式：不更新锚点）")
        except Exception as e:
            logger.warning("无法获取当前联系人: %s", e)
        if not contact:
            print("错误: 请指定联系人，例如: python -m wechat.cli read 张三")
            return 1

    try:
        controller = WeChatController()
        channel = WeChatMessageChannel(controller)
        events = channel.poll(contact, update_anchor=update_anchor)
        if not events:
            print(f"[{contact}] 暂无新消息")
            return 0
        for ev in events:
            print(f"[{contact}] {ev.role}: {ev.content}")
        return 0
    except Exception as e:
        logger.exception("read 失败")
        print(f"错误: {e}")
        return 1


def cmd_send(args):
    """向指定联系人发送文本。会先 open_chat(contact) 再发送。返回码：0 成功，1 失败。"""
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    from controller import WeChatController
    from message_channel import WeChatMessageChannel

    contact = args.contact
    text = args.text
    if not contact or not text:
        print("用法: python -m wechat.cli send <联系人> <消息内容>")
        return 1
    try:
        controller = WeChatController()
        channel = WeChatMessageChannel(controller)
        ok = channel.send_message(contact, text)
        if ok:
            print(f"已发送给 {contact}: {text[:50]}{'...' if len(text) > 50 else ''}")
            return 0
        print("发送失败")
        return 1
    except Exception as e:
        logger.exception("send 失败")
        print(f"错误: {e}")
        return 1


def cmd_send_current(args):
    """
    向当前聊天窗口直接发送文本（不检查联系人、不调用 open_chat）。
    
    适合：
      - 已经手动把微信窗口切到目标聊天时的快速发送。
    不适合：
      - 机器人后台在多个联系人之间切换时（推荐用 send <contact> <text>）。
    """
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    text = args.text
    if not text:
        print("用法: python -m wechat.cli send-current <消息内容>")
        return 1

    try:
        from flows import send_message

        cfg = WeChatAutomationConfig.get_config()
        result = send_message(text, config=cfg)
        if result.success:
            print(f"已向当前聊天窗口发送: {text[:50]}{'...' if len(text) > 50 else ''}")
            return 0
        print(f"发送失败: {result.error_message or '未知错误'}")
        return 1
    except Exception as e:
        logger.exception("send-current 失败")
        print(f"错误: {e}")
        return 1


def cmd_send_file(args):
    """向指定联系人发送文件/图片（统一复制粘贴）。返回码：0 成功，1 失败。"""
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    from controller import WeChatController
    from message_channel import WeChatMessageChannel

    contact = args.contact
    file_path = args.file_path
    if not contact or not file_path:
        print("用法: python -m wechat.cli send-file <联系人> <文件路径>")
        return 1
    try:
        controller = WeChatController()
        channel = WeChatMessageChannel(controller)
        ok = channel.send_file(contact, file_path)
        if ok:
            print(f"已发送给 {contact}: {file_path}")
            return 0
        print("发送文件失败")
        return 1
    except Exception as e:
        logger.exception("send-file 失败")
        print(f"错误: {e}")
        return 1


def cmd_watch(args):
    """
    持续监视指定联系人的新消息（基于 UI hash 检测）。

    行为：
      1) 先执行一次标准 read <contact>（含锚点与视觉状态更新）。
      2) 之后进入循环，仅调用 has_new_message(contact) 做 hash 检测；
         检测到有新消息时，再调用一次 poll(contact) 真正读取并退出。
    """
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    from controller import WeChatController
    from message_channel import WeChatMessageChannel
    import time
    import os

    contact = (args.contact or "").strip()
    if not contact:
        print("用法: python -m wechat.cli watch <联系人>")
        return 1

    debug = getattr(args, "debug", False)

    # 解析轮询间隔（秒），默认 2 秒，可通过环境变量覆盖
    interval_env = os.getenv("WECHAT_WATCH_INTERVAL_SECONDS", "").strip()
    try:
        interval = float(interval_env) if interval_env else 2.0
    except ValueError:
        interval = 2.0
    if interval <= 0:
        interval = 2.0

    try:
        controller = WeChatController()
        channel = WeChatMessageChannel(controller)

        # 第一步：执行一次完整的 poll，相当于 read <contact>
        if debug:
            print(f"[watch] 初次轮询并更新锚点/视觉状态: contact={contact}")
        events = channel.poll(contact, update_anchor=True)
        if events:
            for ev in events:
                print(f"[{contact}] {ev.role}: {ev.content}")

        if debug:
            print(f"[watch] 进入 hash 监视循环，间隔 {interval:.2f}s")

        # 第二步：仅用 hash 检测是否有新消息
        while True:
            has_new = controller.has_new_message(contact, hash_threshold=8)
            if has_new:
                if debug:
                    print(f"[watch] 检测到 UI hash 变化，准备读取新消息: {contact}")
                # 再次调用 poll 读取真正的新消息并更新锚点/视觉状态
                events = channel.poll(contact, update_anchor=True)
                if not events:
                    if debug:
                        print(f"[watch] hash 指示有变化，但未读到新消息（可能是 UI 抖动），继续监视")
                    # 继续下一轮
                else:
                    for ev in events:
                        print(f"[{contact}] {ev.role}: {ev.content}")
                    return 0
            else:
                if debug:
                    print(f"[watch] 无新消息，{interval:.2f}s 后重试")

            time.sleep(interval)

    except Exception as e:
        logger.exception("watch 失败")
        print(f"错误: {e}")
        return 1


def cmd_contacts(args):
    """列出 contact_config.json 中的联系人（含 user_id、启用标记）。不做模板/窗口校验。返回码：0 成功，1 异常。"""
    try:
        from contact_mapper import ContactUserMapper
        mapper = ContactUserMapper()
        enabled = mapper.get_enabled_contacts()
        all_contacts = mapper.get_all_contacts()
        if not all_contacts:
            print("未配置任何联系人，请编辑 wechat/contact_config.json")
            return 0
        print("已配置联系人:")
        for name in all_contacts:
            user_id = mapper.get_user_id(name)
            mark = " [启用]" if (not enabled or name in enabled) else ""
            print(f"  - {name} (user_id={user_id}){mark}")
        return 0
    except Exception as e:
        logger.exception("contacts 失败")
        print(f"错误: {e}")
        return 1


def cmd_current(args):
    """显示当前聊天窗口的联系人名称（依赖 OCR/定位，当前界面须为聊天页）。返回码：0 成功，1 未检测到窗口或识别失败。"""
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    try:
        from element_locator import get_contact_name
        from screen import get_wechat_hwnd
        from actions import activate_window
        import time
        hwnd = get_wechat_hwnd()
        if not hwnd:
            print("未检测到微信窗口，请先打开微信")
            return 1
        if not activate_window(hwnd):
            print("无法激活微信窗口")
            return 1
        time.sleep(0.3)
        name = get_contact_name()
        if name:
            print(name.strip())
            return 0
        print("无法识别当前联系人（可能不在聊天界面）")
        return 1
    except Exception as e:
        logger.exception("current 失败")
        print(f"错误: {e}")
        return 1


def cmd_check_new(args):
    """扫描联系人列表中的新消息红点（头像右上角），有红点则每行输出联系人名；可选读后是否打开对应联系人（默认打开/点击一下）。返回码：0 成功，1 异常。"""
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    try:
        from element_locator import get_contacts_with_new_message_red_point
        names = get_contacts_with_new_message_red_point()
        if not names:
            print("暂无新消息红点")
            return 0
        for name in names:
            print(name)
        do_open = not getattr(args, "no_open", False)
        if do_open and names:
            from controller import WeChatController
            controller = WeChatController()
            for contact in names:
                res = controller.open_chat(contact)
                if not res.success:
                    logger.warning("check-new 打开联系人失败: %s, %s", contact, res.error_message)
        return 0
    except Exception as e:
        logger.exception("check-new 失败")
        print(f"错误: {e}")
        return 1


def cmd_read_direct(args):
    """直接读新消息：用信息锚点做停止条件，读后更新锚点与画面 hash。返回码：0 成功，1 异常。"""
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    contact = (args.contact or "").strip()
    if not contact:
        print("用法: python -m wechat.cli read-direct <联系人>")
        return 1

    try:
        from controller import WeChatController
        from message_channel import WeChatMessageChannel
        controller = WeChatController()
        res = controller.open_chat(contact)
        if not res.success:
            print(f"打开失败: {res.error_message or '未知错误'}")
            return 1
        channel = WeChatMessageChannel(controller)
        events = channel.read_direct(contact)
        if not events:
            print(f"[{contact}] 暂无消息")
        else:
            for ev in events:
                print(f"[{contact}] {ev.role}: {ev.content}")
        return 0
    except Exception as e:
        logger.exception("read-direct 失败")
        print(f"错误: {e}")
        return 1


def cmd_read_new(args):
    """先调用 check-new 逻辑获取有红点的联系人，再逐个打开聊天、poll 读新消息并更新锚点，输出「联系人: 名」及 [名] role: content。返回码：0 成功，1 异常。"""
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    try:
        from element_locator import get_contacts_with_new_message_red_point
        from controller import WeChatController
        from message_channel import WeChatMessageChannel

        names = get_contacts_with_new_message_red_point()
        if not names:
            print("暂无新消息")
            return 0

        controller = WeChatController()
        channel = WeChatMessageChannel(controller)
        for contact in names:
            res = controller.open_chat(contact)
            if not res.success:
                logger.warning("read-new 打开联系人失败: %s, %s", contact, res.error_message)
                continue
            events = channel.poll(contact, update_anchor=True)
            print(f"联系人: {contact}")
            if not events:
                print(f"[{contact}] 暂无新消息")
            else:
                for ev in events:
                    print(f"[{contact}] {ev.role}: {ev.content}")
        return 0
    except Exception as e:
        logger.exception("read-new 失败")
        print(f"错误: {e}")
        return 1


def cmd_open(args):
    """打开指定联系人的聊天窗口。--method list：点击左侧列表头像；--method search：搜索框输入后回车（更稳妥）。返回码：0 成功，1 失败或 method 不支持。"""
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    contact = (args.contact or "").strip()
    method = (args.method or "list").strip().lower()
    if not contact:
        print("用法: python -m wechat.cli open <联系人> [--method list|search]")
        return 1

    try:
        if method == "search":
            from flows import open_chat_via_search
            result = open_chat_via_search(contact)
            if result.success:
                opened = bool(result.data.get("opened")) if isinstance(result.data, dict) else False
                cur = result.data.get("current_contact") if isinstance(result.data, dict) else None
                print(f"已尝试通过搜索框打开: target={contact}, current={cur or ''}, opened={opened}")
                return 0 if opened else 1
            print(f"打开失败: {result.error_message or '未知错误'}")
            return 1

        if method != "list":
            print("错误: --method 仅支持 list 或 search")
            return 1

        from controller import WeChatController
        controller = WeChatController()
        res = controller.open_chat(contact)
        if res.success:
            print(f"已打开聊天窗口: {contact}")
            return 0
        print(f"打开失败: {res.error_message or '未知错误'}")
        return 1
    except Exception as e:
        logger.exception("open 失败")
        print(f"错误: {e}")
        return 1


def cmd_update_hash(args):
    """
    手动更新当前联系人的视觉 hash（含截图与元素信息）。

    - 自动识别当前聊天窗口联系人名
    - 计算并写入 debug/visual_state.json（用于后续轮询前的 UI hash 对比）
    - 保存截图到 debug/ 便于排查
    - 返回当前联系人名字
    """
    from config import WeChatAutomationConfig, ConfigValidationError
    try:
        WeChatAutomationConfig.validate_config(strict=False)
    except ConfigValidationError as e:
        print(f"配置验证失败: {e}")
        return 1

    try:
        from screen import get_wechat_hwnd, capture_window, save_screenshot
        from actions import activate_window
        from element_locator import get_contact_name, locate_all_elements, get_current_chat_hash, save_chat_state
        import json
        import time
        from pathlib import Path

        hwnd = get_wechat_hwnd()
        if not hwnd:
            print("未检测到微信窗口，请先打开微信")
            return 1
        if not activate_window(hwnd):
            print("无法激活微信窗口")
            return 1
        time.sleep(0.3)

        # 当前联系人
        current = get_contact_name()
        if current:
            current = current.strip()
        if not current:
            print("无法识别当前联系人（可能不在聊天界面）")
            return 1

        # 截图 + 定位 + hash
        screenshot = capture_window(hwnd)
        positions = locate_all_elements(screenshot, contact_name=current)
        ui_hash = get_current_chat_hash(contact_name=current, screenshot=screenshot, positions=positions)

        # 保存截图（便于排查）
        shot_path = save_screenshot(
            screenshot,
            "cli_update_hash",
            task_id="cli",
            step_name=current,
            error_info=None,
        )

        # 保存“状态信息”（头像 y 列表等；用于 has_new_message 内部状态）
        save_chat_state(positions=positions, screenshot=screenshot, contact_name=current)

        # 写入持久化视觉 hash 文件（MessageChannel 读取该文件做跨进程比较）
        state_path = WeChatAutomationConfig.VISUAL_STATE_FILE
        data = {}
        if state_path.exists():
            try:
                with open(state_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
            except Exception:
                data = {}

        if ui_hash:
            data[current] = ui_hash
            state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        # 输出：返回当前联系人名字（并附带 hash / 截图路径方便机器人解析）
        print(current)
        print(f"hash={ui_hash or ''}")
        print(f"screenshot={shot_path}")
        return 0 if ui_hash else 1

    except Exception as e:
        logger.exception("update-hash 失败")
        print(f"错误: {e}")
        return 1


def cmd_help(args):
    """输出详细帮助（比 -h 更完整）。topic 可选：overview, prereq, read, read-new, read-direct, send, send-current, send-file, contacts, current, check-new, open, update-hash, watch。默认 overview。"""
    topic = (args.topic or "overview").strip()
    text = _DETAILED_HELP.get(topic)
    if not text:
        # 允许用户输入子命令名作为 topic（如 update_hash vs update-hash）
        normalized = topic.replace("_", "-")
        text = _DETAILED_HELP.get(normalized) or _DETAILED_HELP.get("overview")
    if not text:
        text = "未找到帮助内容。"
    print(text.rstrip())
    if topic not in _DETAILED_HELP:
        # 提示可用主题
        topics = ", ".join(sorted(_DETAILED_HELP.keys()))
        print("\n可用 help 主题：")
        print(f"  {topics}")
    return 0


def main():
    """解析全局与子命令参数，配置日志，派发到对应 cmd_* 并返回退出码（0 成功，1 失败）。"""
    parser = argparse.ArgumentParser(
        description="微信独立工具（纯净版）：读消息、发消息、查联系人等，默认不依赖 AI。使用子命令执行具体功能。",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python -m wechat.cli read 张三       # 轮询并打印张三的新消息（安全模式，更新锚点）
  python -m wechat.cli read-new        # 有红点则打开并读，输出联系人及新消息
  python -m wechat.cli send 张三 你好  # 给张三发送「你好」
  python -m wechat.cli send-current 你好 # 向当前聊天窗口直接发送（不切换联系人）
  python -m wechat.cli contacts       # 列出已配置联系人
  python -m wechat.cli current        # 显示当前聊天窗口联系人
  python -m wechat.cli check-new      # 扫描红点，输出有红点的联系人名（每行一个）
  python -m wechat.cli open 张三 --method list    # 打开张三聊天（列表头像方式）
  python -m wechat.cli open 张三 --method search  # 打开张三聊天（搜索框方式，推荐）
  python -m wechat.cli send-file 张三 <路径>  # 发送文件或图片
  python -m wechat.cli update-hash    # 手动更新当前联系人的视觉 hash（含截图与状态）
  python -m wechat.cli help [topic]    # 详细帮助（topic: overview/prereq/read/...）
  python -m wechat.cli watch 张三     # 持续监视张三的新消息（基于 hash 检测）
  python -m wechat.cli --debug read 张三          # 开启详细日志
        """,
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="输出详细日志（默认静默，只输出命令最终结果）",
    )
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # read
    p_read = subparsers.add_parser("read", help="轮询并打印新消息（不调用 AI）")
    p_read.add_argument("contact", nargs="?", default=None, help="联系人名称；不填则使用当前窗口联系人")
    p_read.set_defaults(func=cmd_read)

    # send
    p_send = subparsers.add_parser("send", help="向指定联系人发送文本")
    p_send.add_argument("contact", help="联系人名称")
    p_send.add_argument("text", help="消息内容")
    p_send.set_defaults(func=cmd_send)

    # send-current
    p_send_cur = subparsers.add_parser(
        "send-current",
        help="向当前聊天窗口直接发送文本（不检查联系人）",
    )
    p_send_cur.add_argument("text", help="消息内容")
    p_send_cur.set_defaults(func=cmd_send_current)

    # send-file
    p_send_file = subparsers.add_parser("send-file", help="向指定联系人发送文件（支持图片与普通文件）")
    p_send_file.add_argument("contact", help="联系人名称")
    p_send_file.add_argument("file_path", help="文件路径")
    p_send_file.set_defaults(func=cmd_send_file)

    # contacts
    p_contacts = subparsers.add_parser("contacts", help="列出已配置的联系人")
    p_contacts.set_defaults(func=cmd_contacts)

    # current
    p_current = subparsers.add_parser("current", help="显示当前聊天窗口的联系人名称")
    p_current.set_defaults(func=cmd_current)

    # check-new
    p_check_new = subparsers.add_parser(
        "check-new",
        help="扫描新消息红点，输出存在红点的联系人名称（每行一个）；默认会打开有红点的联系人",
    )
    p_check_new.add_argument(
        "--no-open",
        action="store_true",
        help="不打开有红点的联系人（默认会点击打开对应聊天）",
    )
    p_check_new.set_defaults(func=cmd_check_new)

    # read-new
    p_read_new = subparsers.add_parser(
        "read-new",
        help="先获取有红点的联系人，再打开并读新消息，输出联系人姓名和新消息",
    )
    p_read_new.set_defaults(func=cmd_read_new)

    # read-direct
    p_read_direct = subparsers.add_parser(
        "read-direct",
        help="直接读新消息（用锚点停止，读后更新锚点与画面 hash）",
    )
    p_read_direct.add_argument("contact", help="联系人名称")
    p_read_direct.set_defaults(func=cmd_read_direct)

    # open
    p_open = subparsers.add_parser("open", help="打开指定联系人的聊天窗口（list/search 两种方式）")
    p_open.add_argument("contact", help="联系人名称")
    p_open.add_argument("--method", choices=["list", "search"], default="list", help="打开方式：list=列表头像，search=搜索框")
    p_open.set_defaults(func=cmd_open)

    # update-hash
    p_upd = subparsers.add_parser("update-hash", help="手动更新当前联系人的视觉 hash（含截图与状态）")
    p_upd.set_defaults(func=cmd_update_hash)

    # help
    p_help = subparsers.add_parser("help", help="输出更详细的帮助说明（比 -h 更详细）")
    p_help.add_argument(
        "topic",
        nargs="?",
        default="overview",
        help="帮助主题：overview/prereq/read/read-new/read-direct/send/send-current/send-file/contacts/current/check-new/open/update-hash/watch",
    )
    p_help.set_defaults(func=cmd_help)

    # watch
    p_watch = subparsers.add_parser(
        "watch",
        help="持续监视指定联系人的新消息（先完整读一次，之后基于 hash 轮询）",
    )
    p_watch.add_argument("contact", help="联系人名称")
    p_watch.set_defaults(func=cmd_watch)


    args = parser.parse_args()
    _configure_logging(getattr(args, "debug", False))
    if not args.command:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
