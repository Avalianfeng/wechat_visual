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

---

## 功能特性

按联系人轮询读新消息（锚点之上的才返回并更新锚点）、发消息；`contact_config.json` + `assets/contacts/` 头像做联系人匹配；锚点存 `debug/message_anchor_state.json` 跨进程一致。OCR 可用阿里云（`ALIYUN_OCR_APPCODE`）或 Tesseract。

---

## 环境要求

Windows；微信 PC 已登录、窗口可见；界面简体中文，窗口 ≥ 800×600；Python 3.9+。需有图形界面（UI 自动化：激活窗口、截图、点击/输入）。

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

### 2. 配置文件

项目根建 `.env`，例如：
```ini
WECHAT_ME_CONTACT=你的微信昵称或配置中的显示名
ALIYUN_OCR_APPCODE=你的阿里云OCR AppCode
```
无 `ALIYUN_OCR_APPCODE` 时回退到 Tesseract。

`copy contact_config.example.json contact_config.json`，再编辑：`contact_mappings` 里写显示名 → user_id / contact_id，`enabled_contacts` 里列启用名；`contact_id` 与 `assets/contacts/` 下头像文件名对应（如 `cylf_id_策月帘风.png` → `cylf_id`）。

### 3. 资源与窗口

`assets/templates/` 下必需模板见 `config.py` 的 `REQUIRED_TEMPLATES`。微信已登录、窗口可见即可。

### 4. 首次运行

在项目根执行：

```bash
python -m wechat.cli contacts
```

能看到联系人列表即正常。再试 `read 某个显示名` 或 `send 某个显示名 你好`。命令见 [CLI 命令一览](#cli-命令一览)。

---

## 配置说明

| 配置 | 说明 |
|------|------|
| `.env` | `WECHAT_ME_CONTACT`、`ALIYUN_OCR_APPCODE`；可选 `WECHAT_WATCH_INTERVAL_SECONDS` |
| `contact_config.json` | 联系人映射与启用列表，从 example 复制后改 |
| `config.py` | 窗口、模板路径、锚点文件、校验 |
| `assets/templates/` | 模板图，缺必需项时校验失败 |
| `assets/contacts/` | 联系人头像，匹配列表与聊天区 |

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

`--debug` 输出详细日志。从项目根执行：`python -m wechat.cli <子命令> [参数...]`。`read`/`send`/`current` 等执行前会做 `validate_config(strict=False)`，不通过则退出。

通过**定时轮询** `python -m wechat.cli check-new --no-open` 检测新消息（仅扫描不打开聊天），对有红点的联系人执行 `read-direct <联系人>` 并输出读到的内容，可常驻、稳定地持续获取新消息。

集成时：工作目录设为项目根；成功返回 0、失败 1，stdout 为输出与错误信息。`python -m wechat.cli help prereq` 可查前置条件与返回码。

---

## 项目结构

```
wechat/
├── .env                    # 本地环境变量
├── contact_config.json     # 联系人配置（见 example）
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
├── debug/                  # 运行时生成（锚点、视觉状态等）
└── test/                   # 单元与 E2E 测试
```

入口 `cli.py`，会加载 `.env` 与 `contact_config.json`。

---

## 核心逻辑与依赖

锚点：每联系人一条「最后已读」hash 存 `debug/message_anchor_state.json`，首次读取当前最下一条为锚点，之后只返回锚点之上。消息流：打开聊天 → 视觉指纹判新消息 → MessageReader 读到锚点 → 过滤去重 → 写回。依赖层次见下表与 **LOCATOR_LOGIC.md**。

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

test/ 下单元与 mock 测试；`test_flow_atomicity.py` 为真实窗口 E2E（`python -m wechat.test.test_flow_atomicity`）。PROJECT_CHECK_ORDER.md 为 Phase 0–4.5 检查顺序。

---

## 相关文档

PROJECT_CHECK_ORDER.md（检查顺序、Phase、CLI 拓展）；LOCATOR_LOGIC.md（元素定位、ROI、回退与排查）。

