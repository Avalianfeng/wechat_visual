# 项目逻辑检查顺序与状态报告

本文档给出「从根本到枝叶」的推荐检查顺序，并标注各模块是否存在不该存在的调用、潜在错误及当前结论。

---

## Phase 0：项目边界审计（一次性）

**目的**：确认「它到底是不是一个工具，而不是半个系统」。

### 检查清单与结论

| 检查项 | 要求 | 结论 |
|--------|------|------|
| **项目中完全不存在** | 无 AI、policy、memory、history、conversation_state 等模块/包 | **通过**：扫描所有 import，无顶层包名包含上述关键词；仅有注释/文档中出现「AI」（说明不依赖）。 |
| **message_channel** | 不 import controller 之外的任何「高层」 | **有一处偏离**：`poll()` 内动态 `from element_locator import get_contact_name`。element_locator 为第 2 层，属「高层」；若严格要求「仅通过 controller 与外界交互」，可将「当前联系人」能力由 controller 暴露（如 `controller.get_current_contact()`），message_channel 只调 controller。 |
| **message_channel** | 不持有跨次运行状态，只读写文件 | **通过**：`_anchor_hashes` 从 `ANCHOR_STATE_FILE` 加载、`_save_anchor_state()` 写回；`_seen_hashes` 仅当次运行去重用，不持久化。 |
| **cli** | 不包含业务逻辑判断，只是参数→调用 | **通过**：各子命令为「解析 args → 调 controller / message_channel / contact_mapper / element_locator」；唯一分支为 read 未传 contact 时尝试用当前窗口联系人，属参数补全而非业务策略。 |
| **test_no_ai_dependency** | 扫描所有 import，断言无 ai/policy/memory（等）模块 | **已实现**：`tests/test_no_ai_dependency.py` 扫描项目内 .py 的顶层包名，断言不含 ai、policy、memory、history、conversation_state；已通过运行。 |

### 自动化测试

- 运行：`python test/test_no_ai_dependency.py`（或 `pytest test/test_no_ai_dependency.py -v`）。

---

## Phase 1：配置完整性与“假设显式化”

**目的**：把「必须成立的前提」变成启动前就失败的条件，防止“换一台机器全崩，但你不知道为什么”。

### 实现要点

| 项 | 说明 |
|----|------|
| **硬失败** | `WeChatAutomationConfig.validate_config(strict=False)` 未通过时**抛 `ConfigValidationError`**，不做 warning。 |
| **校验内容** | 必需模板缺失、窗口过小（&lt;800×600）、语言≠zh_CN → 均硬失败。 |
| **strict 区分** | `validate(strict=False)`：仅必需模板缺失报错；`validate(strict=True)`：可选模板缺失也报错。 |
| **调用点** | controller 在 `ensure_ready()` 中调用 `validate_config(strict=False)`，失败则转成 `WeChatNotReadyError`；CLI 在 read/send/current 入口先调 `validate_config(strict=False)`，失败则打印并 exit 1。 |

### 自动化测试

- `test/test_config_validation.py`：
  - `validate_config()` 在必需模板缺失、窗口过小、语言≠zh_CN 时抛 `ConfigValidationError`；
  - `validate(strict=False)` 在仅必需模板存在时通过；
  - `validate(strict=True)` 在可选模板缺失时失败，且 `validate_config(strict=True)` 抛 `ConfigValidationError`。
- 运行：`python test/test_config_validation.py`。

---

## Phase 2：屏幕与定位层的“可重复性”

**目的**：同一画面 → 同一结果；验证的不是“能不能定位”，而是可重复性（视觉自动化最容易藏雷的地方）。

### 核心测试思想

| 项 | 要求 | 测试 |
|----|------|------|
| **1. screen 纯函数** | 给截图/窗口状态 → 出确定结果 | `crop_region(image, region)` 同入同出；`get_window_client_bbox(hwnd)` 同 hwnd（mock）→ 同输出。 |
| **2. locator 不依赖上一帧** | 同一图+同一模板跑多次，结果在阈值内 | `match_template(image, template)` 跑 3 次，坐标差 ≤ 1 像素、置信度一致。 |
| **3. DPI 只是缩放** | 不改变逻辑，归一化后逻辑 ROI 一致 | `normalize_coords`：dpi=100/125/150 下同一逻辑点归一到 100% 后坐标一致；物理↔逻辑往返舍入误差 ≤ 1。 |

### 自动化测试

- `test/test_screen_locator_repeatability.py`：
  - `test_crop_region_same_input_same_output`
  - `test_get_window_client_bbox_same_hwnd_same_output`（mock win32gui）
  - `test_match_template_same_input_same_output_three_times`
  - `test_normalize_coords_dpi_100_125_150_same_logical_roi`
  - `test_normalize_coords_roundtrip_physical_to_logical`
- 运行：`python test/test_screen_locator_repeatability.py`。

---

## Phase 3：流程（flows）的“原子性检查”

**目的**：一个 flow 失败不应污染下一个 flow；要么成功完成，要么失败后界面仍可恢复。

### 检查原则

每个 flow 应满足：

- **要么成功完成**
- **要么失败后界面仍可恢复**（无残留焦点、输入框未污染、剪贴板可恢复等）

**测试描述（给 Cursor/人工）**：在任意一步抛异常后，再次调用同一个 flow，成功率不降低。

### open_chat

| 失败点 | 界面/状态 | 结论 |
|--------|-----------|------|
| 获取句柄 / 激活窗口失败 | 未做任何点击 | ✓ 无污染 |
| get_contact_name 失败 | 未点击列表 | ✓ 仍在当前聊天 |
| 未检测到红点（require_red_point=True） | 未点击列表 | ✓ 无污染 |
| profile_photo_in_list 未找到 | 未点击 | ✓ 无污染 |
| 点击头像失败 | 未切换聊天 | ✓ 仍在原聊天 |

**结论**：open_chat 失败路径上均未部分切换界面，原子性较好。

### send_message

| 失败点 | 界面/状态 | 结论 |
|--------|-----------|------|
| 输入框未找到 / 点击输入框失败 | 未改输入框、未改剪贴板 | ✓ 无污染 |
| Ctrl+A / Delete 失败 | 未粘贴，剪贴板未写入 | ✓ 无污染 |
| **paste_text 失败** | **剪贴板已被 pyperclip.copy(text) 覆盖** | ⚠ **剪贴板污染** |
| **Enter 失败** | **输入框内已有未发送内容，剪贴板为消息内容** | ⚠ **输入框 + 剪贴板污染** |

**结论**：send_message 在「粘贴之后、Enter 之前或 Enter 失败」时，会污染输入框和剪贴板；**当前 flows 未在失败时恢复剪贴板或清空输入框**。

### read_new_messages

| 失败点 | 界面/状态 | 结论 |
|--------|-----------|------|
| 激活 / 定位头像失败 | 未做复制 | ✓ 无污染 |
| 某条消息 copy_text_at 成功、后续步骤抛异常 | 剪贴板已被复制内容覆盖；可能留有选中状态 | ⚠ **剪贴板污染** |

**结论**：read_new_messages 中途失败时，剪贴板可能已被最后一次复制的内容覆盖；**当前未在失败时恢复剪贴板**。

### 建议（不在此次实现中修改，仅记录）

1. **send_message**：在入口保存 `clipboard_before = pyperclip.paste()`；在 `except` 或失败返回前，若已执行过 `paste_text`，则 `pyperclip.copy(clipboard_before)` 恢复；若已 Ctrl+A+Delete 但未发送成功，可考虑再发一次 Ctrl+A+Delete 清空输入框（需评估焦点是否仍在输入框）。
2. **read_new_messages**：失败路径上恢复剪贴板（同上，入口保存、失败时恢复）。
3. 自动化测试：可在 mock 某步抛异常后，再次调用同一 flow，断言成功率不降低（或断言剪贴板/界面状态被恢复）。当前仅提供文档化测试：`test/test_flow_atomicity.py`（测试描述见该文件 docstring）。

---

## 定位逻辑文档（element_locator）

元素定位的依赖与约束已单独整理，便于排查「某元素定位不了导致另一元素也无法定位」：

- **LOCATOR_LOGIC.md**：各元素定位顺序、依赖关系、ROI 依赖、可能问题与快速排查表；根据代码无法完整判断或可能存在问题处已标出，不修改实现，由后续人工确认。

---

## Phase 4：MessageReader 的“单条语义证明”

**目的**：MessageReader 是整个项目的心脏；若此层不稳，message_channel 再干净也没用。需验证 3 个性质。

### 需验证的 3 个性质

| 性质 | 含义 | 测试 |
|------|------|------|
| **1. read_next 不重复** | 连续两次 read_next() 不会返回同一条消息 | 两次都返回非 None 时，raw1.hash != raw2.hash（索引推进，不同条）。 |
| **2. reset 后行为可预测** | reset() 后从当前画面底部开始 | reset() 后 read_next() 返回的是 _avatars[0] 对应消息（最下面一条）。 |
| **3. read_until(anchor) 单调** | 遇锚点即停，锚点之后的消息不出现在列表中 | messages = read_until(anchor) 中不包含 hash==anchor 的消息，且无“锚点之后”的消息。 |

### 实现与逻辑调整

- **聊天区域头像定位**：由「全图用单模板 + 分布判断」改为**先取当前联系人名，再只匹配该联系人在聊天区域的头像**。  
  - MessageReader.reset()：先 `get_contact_name()` 得到当前窗口联系人；再 `locate_all_contact_avatars_in_chat(screenshot)`，过滤 `contact_name == current_contact`，用该列表作为 _avatars（按 y 从大到小排序）。  
  - 若无当前联系人名或该联系人头像未匹配到，回退到原逻辑：`locate_all_elements(screenshot, contact_name=..., contact_id=...)` 取 profile_photo_in_chat。
- **锚点状态按联系人区分**：message_channel 中 `_anchor_hashes`、`_seen_hashes`、`_readers` 均按联系人名分桶；锚点文件为 JSON 对象，键为联系人名，不同联系人状态互不污染。

### 自动化测试

- `test/test_message_reader_semantics.py`：文档化 3 个性质（无真实 UI 时仅作约定）；若需自动化断言，需 mock 窗口/截图/头像列表与 copy_text_at。

---

## Phase 4.5：message_channel 的“跨进程健壮性”

**目的**：与普通自动化脚本的分水岭——证明「每次 CLI 调用是独立进程、锚点靠文件同步」时，行为仍正确。必测三件事：

| 场景 | 要求 | 测试 |
|------|------|------|
| **1. 锚点文件损坏** | anchor file = {} 或缺失/无效 JSON → fallback to get_initial_anchor，不崩溃 | `_load_anchor_state` 在文件缺失或 JSON 异常时返回 `{}`；首次 poll 无锚点时调用 `_init_anchor`，返回 `[]`。 |
| **2. 锚点文件过旧** | UI 已滚动，锚点不在当前页 → 不 crash，至多重复一条（业务保证） | `_filter_new_messages_from_raw` 在整页都不含锚点时仍正常过滤、去重，不崩溃；返回多条时由上层保证至多重复一条。 |
| **3. 连续 CLI 调用** | cli read / cli read / cli read → 不重复、不跳读 | 模拟多进程：每次新进程从文件加载锚点；三次 poll 分别 初始化→返回 A/B→返回 C，全局 hash 无重复、无遗漏。 |

### 自动化测试

- `test/test_message_channel_robustness.py`：
  - **锚点损坏**：`test_anchor_file_empty_fallback_to_init_anchor`（空锚点首次 poll 走 _init_anchor）、`test_anchor_file_missing_treated_as_empty`、`test_anchor_file_corrupted_load_returns_empty`（JSON 异常返回 `{}`）。
  - **锚点过旧**：`test_stale_anchor_no_crash`（整页无锚点时 _filter 不崩溃，可返回多条）。
  - **连续调用**：`test_consecutive_polls_no_duplicate_no_skip`（同进程内三次 poll 无重复无跳读）、`test_consecutive_polls_dedup_by_seen_hashes`（_filter 跳过 _seen_hashes）、`test_consecutive_cli_calls_cross_process_no_duplicate_no_skip`（真实写锚点文件，三个“进程”依次加载并 poll，断言不重复不跳读）。
- 运行：`python test/test_message_channel_robustness.py`（无 pytest 时走 __main__ 分支）。

---

## 一、推荐检查顺序（从根到叶）

按依赖层级从底层到上层检查，避免漏掉被依赖模块的问题。

### 第 0 层：无项目内依赖

| 顺序 | 文件 | 职责 | 依赖（项目内） | 检查要点 |
|------|------|------|----------------|----------|
| 1 | `models.py` | 数据模型（WeChatConfig, Message, FlowResult, LocateResult 等） | 无 | 无项目内导入，仅被其他模块引用。 |
| 2 | `config.py` | 配置（路径、模板、OCR、DPI 等） | models | 仅 `from .models import WeChatConfig`（或 fallback）。 |

### 第 1 层：仅依赖第 0 层

| 顺序 | 文件 | 职责 | 依赖（项目内） | 检查要点 |
|------|------|------|----------------|----------|
| 3 | `contact_mapper.py` | 联系人↔用户映射（contact_config.json） | config | 仅配置与 JSON，无记忆/决策逻辑。 |
| 4 | `screen.py` | 窗口句柄、截图、DPI、坐标转换 | config | 无不该存在的调用。 |
| 5 | `locator.py` | 模板匹配、OCR、图像工具 | models, screen, config, ocr_aliyun | OCR 已用 try/except 兼容 `.` 与 `ocr_aliyun`。 |
| 6 | `ocr_aliyun.py` | 阿里云 OCR 封装 | config | 仅配置，无业务决策。 |
| 7 | `actions.py` | 点击、输入、剪贴板、热键、延迟 | screen, config, locator | 无记忆/决策逻辑。 |

### 第 2 层：依赖第 0–1 层

| 顺序 | 文件 | 职责 | 依赖（项目内） | 检查要点 |
|------|------|------|----------------|----------|
| 8 | `chat_state_manager.py` | 按联系人的聊天状态（hash、头像 y）用于「是否有新消息」 | 无 | 纯状态存储与比较，属于传输侧「视觉指纹」判断，不是记忆管理。 |
| 9 | `element_locator.py` | 元素定位、聊天区 ROI、新消息红点、get_contact_name | screen, locator, config, models, contact_mapper, chat_state_manager | 已用 try/except 兼容相对/绝对导入；**无**对 idle_tasks、memory 的引用。 |
| 10 | `flows.py` | 流程编排：open_chat, send_message, read_new_messages, get_initial_anchor | models, screen, actions, element_locator, contact_mapper | 已移除 ShortTermMemoryStore；锚点仅来自参数或当前界面。 |

### 第 3 层：依赖第 0–2 层

| 顺序 | 文件 | 职责 | 依赖（项目内） | 检查要点 |
|------|------|------|----------------|----------|
| 11 | `message_reader.py` | 按条读消息（reset, read_next, read_until） | models, screen, actions, element_locator | 已用 try/except 兼容 contact_mapper；**无** memory 相关。 |
| 12 | `controller.py` | 驱动层：open_chat, send_text, read_new_messages, has_new_message | flows, element_locator, screen, actions, locator, models, config | 不依赖 message_channel；**无**记忆/空闲任务。 |
| 13 | `message_channel.py` | 轮询、锚点、去重、消息事件流；锚点持久化到文件 | models, message_reader, config | 已移除短期记忆锚点逻辑；锚点仅来自文件或 MessageReader。 |

#### 第三层：依赖与功能/潜在问题检查（对照 README 44–49）

**依赖核对**

| 文件 | 实际导入（项目内） | 是否符合「仅依赖 0–2 层」 | 备注 |
|------|-------------------|---------------------------|------|
| **message_reader.py** | models, screen, actions, element_locator；reset() 内可选 contact_mapper | ✓ | 全部为 0–2 层；无 message_channel、无 memory。 |
| **controller.py** | flows, element_locator, screen, actions, locator, models, config | ✓ | 不依赖 message_channel；无记忆/空闲任务。 |
| **message_channel.py** | models, message_reader, config；poll() 内动态 element_locator.get_contact_name | ⚠ 一处偏离 | 见 Phase 0：若严格要求「只通过 controller」，需由 controller 暴露 get_current_contact()。 |

**功能与 README 对照**

| 文件 | README 描述 | 实现情况 | 潜在问题 |
|------|-------------|----------|----------|
| **message_reader.py** | 按条读消息；reset、read_next、read_until；为 message_channel 提供单条消息能力 | ✓ reset 先取当前联系人再只匹配该联系人头像；read_next 单条复制并推进索引；read_until 遇锚点停 | read_next 在复制失败时会递归调用自身跳过该条，极端情况下可能栈深；当前页无头像时 reset 抛异常，调用方需处理。 |
| **controller.py** | open_chat、send_text、read_new_messages、has_new_message；仅 UI 驱动与错误转换，不维护锚点/去重 | ✓ 四个接口均转调 flows/element_locator，无锚点/去重状态；错误统一映射为 ControllerResult/异常 | 无。 |
| **message_channel.py** | 轮询、去重、锚点管理；锚点从文件加载/保存；无短期/长期记忆 | ✓ _anchor_hashes 从文件加载/保存；_seen_hashes 仅当次运行；_init_anchor 仅用 MessageReader | _seen_hashes 不持久化，跨进程去重仅依赖锚点与当次 poll 的 _filter；跨进程连续调用见 Phase 4.5 测试。 |

**结论**：第三层依赖与 README 一致；功能实现符合描述；已知偏离与潜在点已记录，无需改代码即可通过人工/测试复核。

### 第 4 层：入口与上层业务

| 顺序 | 文件 | 职责 | 依赖（项目内） | 检查要点 |
|------|------|------|----------------|----------|
| 14 | `cli.py` | 命令行入口：read / send / contacts / current | controller, message_channel, element_locator, screen, actions, contact_mapper | 仅传输子命令，无 AI。 |
| 15 | `__init__.py` | 包导出，供 `from wechat import ...` 使用 | config, models, screen, actions, locator, controller, message_channel | 仅导出，无业务逻辑。 |

#### 第四层：CLI 指令与可扩展项（对照 README 52–56）

**当前子命令**

| 子命令 | 作用 | 入口函数 | 依赖 |
|--------|------|----------|------|
| **read** [contact] | 轮询并打印新消息；不填 contact 则用当前窗口联系人 | cmd_read | validate_config → controller + message_channel.poll |
| **send** &lt;contact&gt; &lt;text&gt; | 向指定联系人发送文本 | cmd_send | validate_config → controller + message_channel.send_message |
| **contacts** | 列出已配置联系人（contact_config.json） | cmd_contacts | contact_mapper |
| **current** | 显示当前聊天窗口联系人名称 | cmd_current | validate_config → element_locator.get_contact_name + screen + actions |

**校验**：read / send / current 启动前调用 `WeChatAutomationConfig.validate_config(strict=False)`，失败则打印并 exit 1；无业务逻辑判断，仅为「参数 → 调用」。

**可拓展指令（建议）**

| 候选子命令 | 用途 | 说明 |
|------------|------|------|
| **reset_anchor** [contact] | 重置某联系人的锚点（清空文件内该联系人锚点，下次 read 视为首次） | 调 message_channel.reset_anchor(contact)，便于重新拉全量或排错。 |
| **anchor** [contact] | 打印当前某联系人的锚点 hash | 调 message_channel.get_anchor_hash(contact)，便于调试。 |
| **validate** [--strict] | 仅做配置自检并退出 | 调 validate_config(strict=False/True)，不依赖窗口；便于 CI 或环境检查。 |
| **open** &lt;contact&gt; | 仅打开聊天窗口（不读不发） | 调 controller.open_chat(contact)，便于 E2E 或手动前置。 |

**结论**：第四层与 README 一致；cli 仅「参数→调用」、无 AI/记忆；__init__.py 导出 config、models、screen、actions、locator、controller、message_channel，满足文档描述。

**已删除**：`ai_service.py`（本工具仅做传输，不做 AI 自动回复）。`reply_policy/` 现无项目内引用，可按需保留或删除。

---

## 二、不应存在的模块调用（已清理）

- **idle_tasks**：已删除文件。
- **ai_service**：已删除文件（本工具仅做传输）。
- **memory 相关**（ShortTermMemoryStore, LongTermMemory, MemoryRouter, MemorySummarizer）：已从 message_channel、flows 中全部移除。
- **ConversationActivityTracker / activity_monitor**：**activity_monitor.py 仍存在但未被引用**（见下文「孤立模块」）。

---

## 三、已修复的问题

（无待修复项；ai_service 已整体删除。）

---

## 四、孤立模块（可选处理）

| 文件 | 说明 | 建议 |
|------|------|------|
| `activity_monitor.py` | 仅定义 `ConversationActivityTracker`，当前项目内无任何引用。 | 若确认不再做「空闲检测」类功能，可删除；否则保留以备后用。 |
| `reply_policy/` | 回复策略（文本、计划、提示词等），原仅被 ai_service 使用。 | ai_service 已删，现无引用；可按需保留或删除。 |

---

## 五、外部/可选依赖说明

- 本工具仅做传输（read/send/contacts/current），不依赖 chat_bot、db、api_providers、wechat_bot_main。

---

## 六、按该顺序检查时的自检清单

1. **第 0–1 层**：models、config、contact_mapper、screen、locator、ocr_aliyun、actions 中是否出现 `memory`、`idle_tasks`、`activity_monitor`、`wechat_bot_main`、`db` 等？  
   → **当前无。**

2. **第 2 层**：chat_state_manager、element_locator、flows 中是否仍有短期/长期记忆、记忆路由、空闲任务？  
   → **已无；** flows 仅用 contact_mapper 做联系人/contact_id。

3. **第 3 层**：message_reader、controller、message_channel 是否只做「传输+锚点」而不做记忆管理？  
   → **是；** 锚点仅来自文件或当前界面。

4. **第 4 层**：cli 是否仍引用 IdleTasks 或任意 memory 组件？  
   → **否；** ai_service 已删除。

5. **全局**：是否还有硬编码 `from wechat.xxx` 且未做 try/except fallback 的导入？  
   → **无；** 其余为文档或包内相对导入。

---

## 七、总结

- **推荐检查顺序**：按上文「第 0 层 → 第 1 层 → … → 第 4 层」依次看，每层确认无记忆/决策/不该存在的调用。
- **当前结论**：  
  - 已删除 idle_tasks、ai_service；已从 message_channel、flows 移除所有记忆相关调用。  
  - 仅剩 **activity_monitor.py**、**reply_policy/** 为未引用模块，可按需删除或保留。

**最近检查**：按本顺序逐层核对，未发现禁止引用（idle_tasks、ai_service、memory、activity_monitor）；各层依赖与文档一致；导入均含 try/except 兼容包内/独立运行。
