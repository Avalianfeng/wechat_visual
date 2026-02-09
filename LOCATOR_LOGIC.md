# 元素定位逻辑与约束说明

本文档梳理 `element_locator.py` 中各元素的定位逻辑、依赖关系与约束条件，便于维护和排查「某元素定位不了导致另一元素也无法定位」的问题。  
**根据代码无法完整判断或可能存在问题的地方，仅指出不修改，由后续人工确认。**

---

## 一、元素定位顺序与依赖（ELEMENT_ORDER）

定位顺序在代码中由 `ELEMENT_ORDER` 决定，**顺序本身即约束**：后面的元素可能依赖前面已写入 `results` 的结果。

| 顺序 | 元素名 | 依赖的前置元素/条件 | 说明 |
|------|--------|----------------------|------|
| 1 | chat_message_icon | 无 | 全图匹配 topbar_chat_message |
| 2 | three_point_icon | 无 | 全图匹配 |
| 3 | pin_icon | 无 | **搜索区域**：全图上半部分 20% |
| 4 | search_bar | 无 | 全图，尝试 search_bar + search_bar_ing，只保留一个 |
| 5 | profile_photo_in_list | **search_bar**（可选） | 全图找所有头像，再按**分布规则**区分列表/聊天；若只有 1 个头像且无 search_bar，判为聊天中 |
| 6 | new_message_red_point | **profile_photo_in_list**（通过 locate_all_contact_avatars_in_list） | 先定位「联系人列表中的头像」，再在每个头像右上角小圆内搜红点 |
| 7 | profile_photo_in_chat | 与 profile_photo_in_list 同批计算 | 和 profile_photo_in_list 一起在一次「全图头像+分布判断」中产出，不单独再搜 |
| 8 | sticker_icon | 无 | 全图匹配 toolbar_sticker |
| 9 | save_icon | 无 | 全图 |
| 10 | file_icon | 无 | 全图 |
| 11 | screencap_icon | 无 | 全图 |
| 12 | tape_icon | 无 | 全图（微信更新后新增，在截图图标右侧） |
| 13 | voice_call_icon | 无 | 全图 |
| 14 | video_call_icon | 无 | 全图 |
| 15 | send_button | 无 | 全图，尝试 send_button + send_button_default，只保留一个 |
| 16 | input_box_anchor | **sticker_icon, send_button** | 无模板；坐标为两者中点，缺一不可 |

**约束小结：**

- **input_box_anchor** 依赖 sticker_icon 与 send_button；二者任一失败则 input_box_anchor 必失败。
- **new_message_red_point** 依赖「联系人列表中的头像」；若 `locate_all_contact_avatars_in_list` 无结果，则红点必失败。
- **profile_photo_in_list / profile_photo_in_chat** 依赖 search_bar 仅用于「分布判断」：有 search_bar 时用「搜索框左下方」区分列表/聊天；无 search_bar 时单头像判为聊天、多头像仍按 x/y 分布判断。

---

## 二、各元素定位逻辑与约束

### 2.1 顶部栏（用于 ROI 上界/联系人名区域）

- **chat_message_icon**  
  - 模板：topbar_chat_message，全图匹配。  
  - **get_contact_name_roi**、**get_chat_area_roi** 依赖它；缺失则联系人名 ROI、聊天区上界不可用。

- **three_point_icon**  
  - 全图匹配，当前未参与 ROI 计算，仅作为可定位元素。

- **pin_icon**  
  - 模板：topbar_pin；**搜索区域**：图像上半部分 20%（`screenshot[0:search_height, 0:w]`）。  
  - **get_contact_name_roi** 依赖：有 pin_icon 用其下界作为 ROI 上界，无则用 chat_message_icon 上界回退。  
  - **可能问题**：若置顶图标不在上半 20% 或样式变化，会漏检；代码未对「上半 20%」是否覆盖所有客户端布局做说明。

### 2.2 搜索框与头像（列表/聊天区分）

- **search_bar**  
  - 全图，search_bar 与 search_bar_ing 二选一保留一个结果。  
  - 约束：**必须在 profile_photo 之前定位**（ELEMENT_ORDER 已保证），供头像分布判断使用。

- **profile_photo_in_list / profile_photo_in_chat**  
  - 同一套逻辑：全图 matchTemplate 找所有头像 → NMS 去重（30px）→ 按 **X 优先** 规则分为「列表中」与「聊天中」（`_classify_avatar_matches`）。  
  - **分布规则（正确逻辑）**：  
    - **1 个头像**：  
      - 若列表区域边界已明确（list_left/list_right）：仅当落在列表区域（list_left ≤ x < list_right 且 y > search_bar_y）才判为列表；否则 **清空（不回退为聊天，不往下传递）**。  
      - 若列表区域边界不明确：用 search_bar_x/search_bar_y 的“左下方”规则粗判列表/聊天。  
    - **2 个及以上**：先按 X 分组（10px 容差）。同 X 上有不同 y（1 个 X 组）→ 均为**聊天**；两个不同 X → 左列表、右聊天；**不同 X 数量 ≥ 3 → 中止并打严重告警**，清空结果（不往下传递）。  
  - **列表区域**：左界 = search_bar_x - search_bar宽度×0.6（即 宽度×1/2×120%），右界 = search_bar_x。`get_list_area_roi` 按此计算。  
  - **列表中必须落在区域内**：联系人列表头像区域确定后，凡判为「列表中」的头像必须满足落在该搜索/列表区域（list_left ≤ x < list_right 且 y > search_bar_y）；不满足则 **直接丢弃**（区域只做减法，不回退为聊天）。  
  - **错误来源已修正**：原「先按 y 分组、同 y ≥2 判聊天」已删除，改为「先按 X 分组、同 X=聊天、两 X=左列表右聊天」。

- **new_message_red_point**  
  - 依赖：先调用 `locate_all_contact_avatars_in_list`（内部再依赖 search_bar + 各联系人头像模板）。  
  - 在每个列表头像的「右上角」小圆（半径 10px）内做红点模板匹配；红点中心到头像右上角距离须 ≤ search_radius(10)。  
  - **约束**：无联系人列表头像则红点必失败；红点模板尺寸若大于 20x20 与小区域可能不适配（代码有 region 与 template 尺寸检查）。

### 2.3 工具栏与输入框

- **sticker_icon, save_icon, file_icon, screencap_icon, tape_icon, voice_call_icon, video_call_icon**
  - 均为全图单模板匹配，无前置元素依赖。tape_icon 为微信更新后在聊天界面新增元素（位于 screencap_icon 右侧，大小相近）。
  - **get_chat_area_roi** 依赖 **sticker_icon**（左界、上界）和 **video_call_icon**（右界）；**get_contact_name_roi** 依赖 **sticker_icon**（左界）、**chat_message_icon**、**pin_icon**。

- **send_button**  
  - 全图，send_button 与 send_button_default 二选一。  
  - **input_box_anchor** 依赖 send_button 与 sticker_icon。

- **input_box_anchor**  
  - 无模板；坐标 = (sticker_icon 与 send_button 的坐标中点)。  
  - **强约束**：sticker_icon 或 send_button 任一失败则 input_box_anchor 失败，且无回退逻辑。

---

## 三、ROI 计算的元素依赖

| ROI 函数 | 依赖元素 | 说明 |
|----------|----------|------|
| **get_contact_name_roi** | sticker_icon（必要）, chat_message_icon（必要）, pin_icon（可选，无则用 chat_message 上界） | 左：sticker 左界-5；右：chat_message 左界；上：pin 下界或 chat_message 上界；下：chat_message 下界+expand_y。 |
| **get_chat_area_roi** | sticker_icon（必要）, chat_message_icon（必要）, video_call_icon 或 image_width | 左：sticker 左界；右：video_call 右界，**若未找到 video_call_icon 且传入 image_width，则右界为界面最右（image_width）**；上：(chat_message 下界 + sticker 上界)/2；下：sticker 上界。 |

**可能问题：**

- **get_contact_name_roi** 的 docstring 写的是「左界：sticker_icon 的左界再往左 5 像素」，与实现一致；但若 sticker 未找到则直接返回 None，无备选左界。
- **get_chat_area_roi**：当 video_call_icon 未定位到（例如界面折叠该图标）时，若调用方传入 `image_width`（窗口/截图宽度），则右界使用界面最右边缘，ROI 仍可用。

---

## 四、其他依赖与可能问题（仅指出）

1. **locate_all_contact_avatars_in_list**  
   - 内部先找 search_bar，再按联系人逐个用头像模板匹配。  
   - **按联系人单独计算与判断**：对每个联系人先单独做 NMS 去重（`_nms_avatar_matches`），再单独做列表/聊天分类（`_classify_avatar_matches`），得到该联系人的「列表头像数」「聊天头像数」后，再汇总返回列表区域结果；不与其它联系人的匹配合并后再分类，避免跨联系人误判。  
   - 若 contact_mapper 未配置或无启用联系人，返回空，进而导致 **new_message_red_point** 无法基于列表头像做红点检测。

2. **locate_all_contact_avatars_in_chat**  
   - 同样依赖 search_bar 做分布判断。  
   - **按联系人单独计算与判断**：与 locate_all_contact_avatars_in_list 一致，每个联系人单独 NMS、单独列表/聊天分类，再汇总返回聊天区域结果。

3. **get_contact_name**  
   - 依赖 locate_all_elements → get_contact_name_roi → ocr_region。  
   - 因此间接依赖 sticker_icon、chat_message_icon、pin_icon；任一定位失败则无法得到联系人名 ROI，OCR 不执行。

4. **save_chat_state / has_new_message**  
   - 依赖 get_chat_area_roi 与 profile_photo_in_chat 的 y 位置；若 get_chat_area_roi 因 video_call_icon 等缺失而为 None，则无法保存/比较聊天区状态。

5. **头像模板**  
   - profile_photo_in_list 可使用联系人专属模板（contact_name/contact_id），若未配置则用默认头像；不同联系人共用同一默认模板时，列表中存在多个相似头像可能增加误匹配或 NMS 合并错误的风险，逻辑上未单独说明。

---

## 五、快速排查表（某元素失败时可能原因）

| 元素失败 | 优先检查 |
|----------|----------|
| input_box_anchor | sticker_icon、send_button 是否都成功 |
| new_message_red_point | 是否有联系人列表头像（search_bar + contact_mapper + 头像模板）；红点模板是否过大致小区域无法匹配 |
| profile_photo_in_list 为空 | search_bar 是否成功；头像模板是否存在；全图是否有匹配（阈值、分辨率） |
| profile_photo_in_chat 为空 | 同上；且当前界面是否在「聊天」内（有聊天头像分布） |
| get_contact_name_roi 为 None | sticker_icon、chat_message_icon 是否成功 |
| get_chat_area_roi 为 None | sticker_icon、chat_message_icon 是否成功；若无 video_call_icon，是否传入 image_width |
| pin_icon | 是否在窗口上半 20% 内；模板是否与当前主题一致 |

以上为根据当前代码梳理的定位逻辑与约束；涉及「可能问题」或「未在代码中明确」的部分，仅作标注，不修改实现，后续可由你根据实际 UI 和需求调整判断逻辑与定位策略。
