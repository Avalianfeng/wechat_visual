# 微信自动化模块

基于 Windows 微信 PC 客户端的 UI 自动化工具：**打开指定聊天 → 发送/读取消息**，适合作为「只做传输」的底层模块，供脚本或机器人按联系人轮询新消息、发送文本。

**状态**：纯传输工具，无 AI、无记忆、无决策逻辑。新消息采用「按次调用」模式，锚点持久化到本地文件，跨进程/连续 CLI 靠锚点与去重保证不重复、不跳读。

---

## 目录

- [功能特性](#功能特性)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [CLI 命令一览](#cli-命令一览)
- [项目结构](#项目结构)
- [核心逻辑与依赖](#核心逻辑与依赖)
- [开发与修改指南](#开发与修改指南)
- [测试与检查](#测试与检查)
- [相关文档](#相关文档)
- [上传到 GitHub](#上传到-github)

---

## 功能特性

- **读新消息**：按联系人轮询，只返回锚点之上的新消息并更新锚点；支持「有红点再读」、直接读当前页等模式。
- **发消息**：向指定联系人发送文本（先打开聊天再发送），或向当前窗口直接发送。
- **联系人管理**：通过 `contact_config.json` 配置显示名与 `contact_id` 映射，配合 `assets/contacts/` 头像图做列表/聊天区匹配。
- **视觉锚点**：每个联系人一条「最后已读」消息 hash，存于 `debug/message_anchor_state.json`，跨进程一致。
- **可选 OCR**：支持阿里云高精 OCR（需 `ALIYUN_OCR_APPCODE`）或本机 Tesseract。

---

## 环境要求

- **系统**：Windows（依赖 pywin32、窗口句柄与截图）
- **微信**：PC 客户端已登录，窗口存在且未被最小化到不可见
- **界面**：微信界面为**简体中文**，窗口大小 ≥ 800×600（推荐 1200×800）
- **Python**：3.9+（见 `requirements.txt`）
- **运行方式**：需有图形界面，本工具通过 UI 自动化（激活窗口、截图、模拟点击/输入）与微信交互

---

## 快速开始

### 1. 克隆与依赖

```bash
git clone <你的仓库地址>
cd wechat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

（若在 WSL 中开发，可在 Windows 侧 Python 环境下安装依赖，运行时需在 Windows 图形环境下执行。）

### 2. 配置文件

- **环境变量**：在项目根目录创建 `.env`（不会提交到 Git），例如：
  ```ini
  WECHAT_ME_CONTACT=你的微信昵称或配置中的显示名
  ALIYUN_OCR_APPCODE=你的阿里云OCR AppCode
  ```
  未配置 `ALIYUN_OCR_APPCODE` 时会回退到 Tesseract（需本机安装）。

- **联系人配置**：复制示例并改为自己的联系人：
  ```bash
  copy contact_config.example.json contact_config.json
  ```
  编辑 `contact_config.json`：在 `contact_mappings` 中填写「显示名 → user_id / contact_id」，在 `enabled_contacts` 中列出要启用的显示名。`contact_id` 需与 `assets/contacts/` 下头像文件名一致（如 `cylf_id_策月帘风.png` 中的 `cylf_id`）。

### 3. 资源与窗口

- 确保 `assets/templates/` 下必需模板图存在（见 `config.py` 中 `REQUIRED_TEMPLATES`）。
- 微信 PC 已登录，窗口可见；可选将窗口固定为配置中的大小（如 1200×800）。

### 4. 首次运行

从**项目根目录**执行（以便加载 `.env` 与 `contact_config.json`）：

```bash
python -m wechat.cli contacts
```

若能看到配置的联系人列表，说明配置与路径正常。再试：

```bash
python -m wechat.cli read 某个显示名
```

或 `send 某个显示名 你好`。详细命令见 [CLI 命令一览](#cli-命令一览)。

---

## 配置说明

| 配置 | 说明 |
|------|------|
| **`.env`** | 本地环境变量，不提交。常用：`WECHAT_ME_CONTACT`、`ALIYUN_OCR_APPCODE`；可选 `WECHAT_WATCH_INTERVAL_SECONDS`（watch 间隔秒数）。 |
| **`contact_config.json`** | 联系人映射与启用列表；由 `contact_config.example.json` 复制后修改，不提交。 |
| **`config.py`** | 窗口大小、模板路径、锚点文件路径、校验规则等；按需修改。 |
| **`assets/templates/`** | 必需/可选模板图；缺必需模板时 `validate_config` 会硬失败。 |
| **`assets/contacts/`** | 各联系人头像图，用于匹配左侧列表与聊天区头像。 |

---

## CLI 命令一览

| 命令 | 作用 |
|------|------|
| `read <contact>` | **推荐**：轮询该联系人的新消息并更新锚点。 |
| `read` | 用当前窗口联系人轮询并打印；**不更新锚点**，非幂等。 |
| `read-new` | 扫描新消息红点，对有红点的联系人逐个打开并读新消息。 |
| `read-direct <contact>` | 直接读当前可见页消息，不比对锚点、不去重，速度快。 |
| `send <contact> <text>` | 向指定联系人发送文本。 |
| `send-current <text>` | 向当前聊天窗口直接发送，不切换联系人。 |
| `contacts` | 列出已配置联系人。 |
| `current` | 打印当前聊天窗口联系人名称。 |
| `check-new [--no-open]` | 扫描红点并输出有红点的联系人；默认会打开，`--no-open` 仅扫描。 |
| `open <contact> [--method list\|search]` | 打开指定联系人聊天窗口；`search` 更稳妥。 |
| `update-hash` | 手动更新当前联系人的视觉 hash（写 debug/visual_state.json）。 |
| `watch <contact>` | 持续监视该联系人新消息（hash 检测），有新消息读出后退出。 |
| `help [topic]` | 详细帮助；topic 可选 overview、prereq、read、send、open 等。 |

**全局选项**：子命令前加 `--debug` 可输出详细日志。

推荐从项目根执行：`python -m wechat.cli <子命令> [参数...]`。执行 `read`/`send`/`current` 等前会做 `validate_config(strict=False)`，未通过则退出并打印错误。

### 脚本/机器人集成要点

- **进程模型**：每次调用为独立进程，无常驻服务；锚点与去重依赖本地文件 `debug/message_anchor_state.json`，跨进程一致。
- **推荐用法**：轮询新消息用 `read <contact>`；先扫红点再读可用 `check-new` 或 `read-new`；发消息用 `send <contact> <text>`；打开聊天用 `open <contact> --method search`。
- **工作目录**：设为项目根，以便加载 `.env`、`contact_config.json` 和 `assets/`。
- **返回码**：成功 0，失败 1；错误信息打印到 stdout，可根据返回码与输出做重试或告警。更多细节见 `python -m wechat.cli help prereq`。

---

## 项目结构

```
wechat/
├── .env                    # 本地环境变量（不提交）
├── contact_config.json     # 联系人配置（不提交，见 example）
├── contact_config.example.json
├── requirements.txt
├── config.py, models.py, contact_mapper.py
├── screen.py, locator.py, ocr_aliyun.py, actions.py
├── chat_state_manager.py, element_locator.py, flows.py
├── message_reader.py, controller.py, message_channel.py
├── cli.py, __init__.py
├── assets/
│   ├── templates/          # 搜索框、发送按钮、头像等模板图
│   ├── contacts/           # 各联系人头像图
│   └── ocr_keywords/
├── debug/                  # 运行时生成（锚点、视觉状态等，不提交）
└── test/                   # 单元与 E2E 测试
```

入口为 `cli.py`；调用前会加载 `.env` 与 `contact_config.json`。

---

## 核心逻辑与依赖

- **锚点**：每个联系人一条「最后已读消息」hash，存于 `debug/message_anchor_state.json`；首次读以当前最下一条为锚点，之后只返回锚点之上的新消息。
- **消息流**：`message_channel.poll(contact)`：打开聊天 → 视觉指纹判断是否有新消息 → MessageReader 读到锚点 → 过滤、去重 → 更新锚点写回。
- **依赖层次**：config/models → contact_mapper/screen/locator/ocr/actions → chat_state/element_locator/flows → message_reader/controller/message_channel → cli。详见 [依赖层次与文件职责](#依赖层次与文件职责) 及 **LOCATOR_LOGIC.md**。

### 依赖层次与文件职责

| 层 | 文件 | 职责 |
|----|------|------|
| 0 | models.py, config.py | 数据模型与全局配置、校验 |
| 1 | contact_mapper.py, screen.py, locator.py, ocr_aliyun.py, actions.py | 联系人、窗口/截图/DPI、模板与 OCR、点击/输入 |
| 2 | chat_state_manager.py, element_locator.py, flows.py | 视觉指纹、UI 元素与 ROI、流程编排 |
| 3 | message_reader.py, controller.py, message_channel.py | 按条读、驱动接口、轮询/去重/锚点 |
| 4 | cli.py, __init__.py | 子命令与包导出 |

---

## 开发与修改指南

| 要改/查的内容 | 主要文件 |
|---------------|----------|
| 配置项、必需模板、启动校验 | config.py |
| 窗口/截图/DPI | screen.py |
| 模板匹配、OCR | locator.py, ocr_aliyun.py |
| 元素定位顺序、ROI、约束 | element_locator.py, **LOCATOR_LOGIC.md** |
| 流程步骤与原子性 | flows.py |
| 按条读、锚点内读 | message_reader.py |
| 轮询、锚点文件、去重 | message_channel.py |
| CLI 子命令与参数 | cli.py |

---

## 测试与检查

- **test/**：单元/逻辑测试（mock）：`test_flow.py`、`test_config_validation.py`、`test_message_reader_semantics.py`、`test_message_channel_robustness.py` 等。
- **test_flow_atomicity.py**：真实窗口 E2E，建议 `python -m wechat.test.test_flow_atomicity`。
- **PROJECT_CHECK_ORDER.md**：Phase 0–4.5 检查顺序与结论。

---

## 相关文档

- **PROJECT_CHECK_ORDER.md**：检查顺序、Phase 清单、可拓展 CLI 建议。
- **LOCATOR_LOGIC.md**：元素定位顺序、ROI 与约束、回退逻辑与排查表。

---

## 上传到 GitHub

1. **不要提交的内容**（已由 `.gitignore` 排除）：
   - `.env`（环境变量与密钥）
   - `contact_config.json`（你的联系人配置）
   - `debug/` 下生成的 `*.json`、`*.png`（锚点与调试输出）
   - `__pycache__/`、虚拟环境、IDE 与系统临时文件

2. **首次推送前建议**：
   - 在项目根执行 `git status` 确认没有误加入 `.env` 或 `contact_config.json`。
   - 保留并提交 `contact_config.example.json`，方便他人复制为 `contact_config.json` 后修改。
   - 确保 `assets/templates/` 与 `assets/contacts/` 中**不包含个人隐私**后再提交；若仅作示例，可用占位图或说明在 README 中注明需自行准备。

3. **仓库描述建议**：可注明「Windows 微信 PC 端 UI 自动化：读消息/发消息，适合脚本与机器人集成」。

如需更详细的 CLI 返回码、机器人/后台调用方式、前置条件表，请运行：`python -m wechat.cli help` 或 `python -m wechat.cli help prereq`。
