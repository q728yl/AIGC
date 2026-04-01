# Seedance AI 导演工作流 — 项目文档

> 最后更新: 2026-03-30

## 一、项目概述

本项目是一个 **AI 驱动的游戏视频生成工作流系统**，核心目标是：给定一张游戏截图（首帧）和一个简单指令，自动完成「感知画面 → 规划素材 → 生成资产 → 编排时间轴 → 提交视频生成」的完整流水线，最终通过Seedance 2.0 API 输出一段高质量的游戏短视频。

系统支持三条流水线路径，并配有 Web UI 前端和多个辅助 CLI 工具。

---

## 二、系统架构总览

```
用户输入 (首帧图 + 创意指令)
        │
        ▼
┌──────────────────────────────────────────────┐
│           app.py (Flask Web Server)          │
│  - 前端交互、文件上传、API 路由、任务轮询      │
└──────────┬───────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│        director_agent.py (核心引擎)           │
│                                              │
│  ┌─────────────┐  ┌──────────────────────┐   │
│  │ 导演 Agent   │  │ 画师 Agent           │   │
│  │ (GPT-5.4)   │  │ (GPT-Image-1.5)     │   │
│  │             │  │                      │   │
│  │ · 视觉感知  │  │ · Sprite Sheet 生成   │   │
│  │ · 元素清点  │  │ · UI 元素生成         │   │
│  │ · 需求分析  │  │ · VFX 特效生成        │   │
│  │ · Timeline  │  │ · 风格一致性约束      │   │
│  │   编排      │  │                      │   │
│  └──────┬──────┘  └──────────┬───────────┘   │
│         │                    │               │
│  ┌──────┴────────────────────┴───────────┐   │
│  │    VideoReferenceScraper (视频爬虫)     │   │
│  │  · TapTap 自动搜索 + yt-dlp 下载      │   │
│  │  · MLLM 多模态视频理解 + 关键帧抽取    │   │
│  │  · ffmpeg 自动裁剪最佳片段             │   │
│  └───────────────────────────────────────┘   │
└──────────┬───────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────────────────┐
│         seedance_api.py (API 层)             │
│  · 图片 Base64 编码 + 视频公网上传           │
│  · 构造多模态 payload 提交火山引擎 API        │
│  · 轮询任务状态 + 下载生成视频               │
└──────────────────────────────────────────────┘
           │
           ▼
    Seedance 2.0 Fast (doubao-seedance-2-0-fast-260128)
           │
           ▼
      生成的 .mp4 视频
```

---

## 三、使用的大模型


| 角色       | 模型                                | 用途                               | 可配置                            |
| -------- | --------------------------------- | -------------------------------- | ------------------------------ |
| 导演 Agent | `gpt-5.4`                         | 视觉感知、元素清点、需求分析、Timeline 编排       | 环境变量 `MODEL_DIRECTOR`          |
| 画师 Agent | `gpt-image-1.5`                   | 素材图片生成 (Sprite Sheet / UI / VFX) | 环境变量 `MODEL_ARTIST`            |
| 视频理解     | `gpt-4o`                          | 多模态视频关键帧分析、最佳片段选择                | `mllm_video_extractor.py` 内硬编码 |
| 视频生成     | `doubao-seedance-2-0-fast-260128` | 火山引擎 Seedance 2.0 Fast 视频生成      | API 调用参数                       |


---

## 四、文件结构

```
code/
├── app.py                    # Flask Web 服务器 (前端 + API 路由)
├── director_agent.py         # 核心引擎: 导演Agent + 画师Agent + 视频爬虫
├── seedance_api.py           # Seedance 2.0 API 封装 (提交/轮询/下载)
├── direct_seedance.py        # 直出对比脚本 (单图+Prompt, 无工作流)
├── quick_submit.py           # 快速重传工具 (从已有 plan 直接提交 API)
├── check_task.py             # 任务状态查询工具
├── run_test.py               # 三条路径的测试入口 (Path A/B/C)
├── mllm_video_extractor.py   # 多模态视频理解模块 (关键帧抽取+分析)
├── test_taptap_scraper.py    # TapTap 视频爬虫 (Playwright + yt-dlp)
├── requirements.txt          # Python 依赖
├── keys/
│   └── seedance_key.txt      # 火山引擎 API Key
├── direct_output/            # 直出对比脚本的输出目录
├── seedance_project/
│   ├── docs/
│   │   └── seedance_guide.txt    # 全局 Seedance 生成指南
│   ├── static/
│   │   ├── index.html            # Web 前端页面
│   │   ├── script.js             # 前端交互逻辑
│   │   └── style.css             # 前端样式
│   └── games/
│       └── <game_name>/          # 每个游戏独立目录
│           ├── assets/           # AI 生成的素材图 (Sprite Sheet/VFX/UI)
│           ├── references/       # 用户上传的首帧图 + 下载的参考视频
│           ├── output/           # 生成的计划文件 (.md/.json) + 最终视频
│           └── docs/
│               └── game_context.txt  # 游戏专属上下文 (美术风格/玩法说明)
```

---

## 五、三条流水线路径详解

### Path A: `image_only` — 纯图片素材生成

适用场景：不需要外部参考视频，纯依赖 AI 生图 + 编排。

```
首帧图 + 指令
    │
    ├─ Step 1: 视觉感知 (_analyze_visual_style)
    ├─ Step 2: 需求分析 (analyze_needs)
    ├─ Step 3: 素材生成 (AssetGenerator)
    ├─ Step 4: Timeline 编排 (generate_final_plan)
    └─ Step 5: Web UI 拦截与人工审查 (Prompt Review)
```

#### Step 1: 视觉感知 `_analyze_visual_style`

**实现方式**: 将首帧图片编码为 Base64 Data URL，连同一段结构化分析指令一起发送给 GPT-5.4 的多模态接口（Chat Completions + `image_url`），要求返回 `json_object` 格式。

在这个步骤中，大模型作为“导演”的眼睛，首先“看”一眼用户上传的参考图。它需要理解这是一张什么样的图（比如是横版战斗还是竖版抽卡），当前图里正在发生什么（比如正在砍怪），图里到底有哪些人、特效和UI，甚至还要推断“图里缺什么但接下来应该发生什么”。这个“看到”的内容会作为绝对的 Ground Truth (基础事实)，在后续所有步骤中锁定，确保不会因为 AI 幻觉凭空捏造出图里没有的角色。

```python
# 1. 构造多模态请求，包含系统提示词和首图的 Base64
response = client.chat.completions.create(
    model=MODEL_DIRECTOR,
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": """你是一个资深游戏美术总监和视频导演。
你的任务是极其精确地分析提供的首帧截图，并返回结构化的 JSON。
1. 提取画面的构图法则 (image_type, layout, camera_angle)
2. 清点所有存在的元素 (visible_characters, visible_enemies, visible_effects, ui_elements)
3. 状态推演 (scene_state, next_logical_actions)
..."""},
        {"role": "user", "content": [
            {"type": "text", "text": "请分析这张首帧截图的特征与包含元素。"},
            {"type": "image_url", "image_url": {"url": image_data_url}}
        ]}
    ]
)
# 2. 将解析结果存入 self.reference_analysis，作为后续步骤的锚点
self.reference_analysis = json.loads(response.choices[0].message.content)
```

#### 附：构图锁定规则

在 Step 1 完成后，系统调用 `_build_composition_lock()` 将解析出的 JSON 转化为一段 Prompt 约束规则。核心目的是：**防止 AI 在后续生成 Timeline 或图片素材时产生幻觉，强迫 AI 必须基于这张首图的客观事实来延展。**

这段规则包含 4 个维度的限制：

1. **构图与视角锁定**：锁定画面的物理骨架（如：横版、仰视），防止后续分镜突变。
2. **场景状态与逻辑推演**：锁定当前的“时间状态”（如：战斗中），强制后续动作顺着逻辑推演。
3. **精确的资产清单锁定**：给画面上已有的角色、敌人、特效、UI 登记造册，后续生成“只能在这个清单里找，不能随便发明新东西”。
4. **缺失元素防幻觉警告**：明确指出图里**没有**的东西（如：没有第二个敌人），极大地抑制大模型随意脑补。

```python
    def _build_composition_lock(self):
        # ... 提取 Step 1 解析出的各个字段 ...
        return f"""## Composition & Image Type Lock From Reference Frame
- image_type: {image_type}
- layout_axis: {layout_axis}
- primary_focus_anchor: {primary_focus}
- camera_angle: {camera_angle}
...

## Scene State & Logic Perception
- scene_state: {scene_state}
- game_logic_plan: {game_logic_plan}

## Precise Element Inventory Lock (MUST NOT VIOLATE)
1. Characters Present: {chars_str}
2. Enemies Present: {enemies_str}
3. Active Effects: {effects_str}
4. UI Elements: {ui_str}

CRITICAL ABSENT ELEMENTS WARNING (Do NOT assume these exist):
{absent_str}
"""
```

*注：这段文本在 Step 2（需求分析）和 Step 4（Timeline编排）中，都会作为 System Prompt 的核心规则注入给大模型。*

#### Step 2: 需求分析 `analyze_needs`

**实现方式**: 调用 GPT-5.4 的 Chat Completions（纯文本，不带图片），将 Step 1 产出的构图锁定规则 + Seedance 全局指南（来源） + 游戏专属上下文一起注入 system prompt，用户的创意指令作为 user message。

有了第一步的“看见”，这一步是“思考怎么做”。导演会根据用户的要求（比如：“生成一段大招战斗视频”），结合第一步看到的首图内容，开始思考：“如果我要完成这个动作，画面上还缺什么素材？”比如，首图上只有拿剑的人，要发大招，那就缺“剑气特效”、“屏幕受击红光”、“全屏秒杀大字”等。导演会列出一份采购清单（`missing_assets`），最多列出 6 个必须补充生成的图片素材。

```python
# 1. 拼装之前分析出的构图锁定信息，确保规划不偏离首图
style_guide = self._build_style_reference()

system_prompt = f"""你是一个高级游戏视频导演的规划模块。
基于 Seedance 2.0 API 和当前项目上下文，拆解用户的指令。
{style_guide}

你的任务：
分析为了实现用户指令，【额外需要】哪些素材图层。
请注意：不要列出首图已经有的东西，只列出需要“无中生有”生成的新特效或状态。
返回 JSON:
{{
  "missing_assets": [
    {{"filename_hint": "比如 slash_vfx", "description": "详细描述，给AI画师看"}}
  ]
}}
"""

response = client.chat.completions.create(
    model=MODEL_DIRECTOR,
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"用户输入指令：{user_instruction}"}
    ]
)
```

#### Step 3: 素材生成 `AssetGenerator.generate_image`

**实现方式**: 遍历 Step 2 产出的 `missing_assets` 列表，逐个调用 GPT-Image-1.5 生成图片。如果有首帧图片则使用 `images.edit`（图生图），否则使用 `images.generate`（纯文生图）。

这一步由“画师Agent”来执行。它拿到导演刚才开出的“素材采购清单”，开始一张张作画。在这个过程中，代码会智能判断这个素材是什么类型的——如果是特效或角色动作，它会偷偷在提示词里加上指令，让大模型画成 `2x2 的序列帧拼图 (Sprite Sheet)`；如果是 UI，就让它画成 `扁平化 UI 样式`。最关键的是，代码会强制加入“一致性约束”，要求画出来的素材必须跟首图保持完全相同的画风和角色设定。

```python
# 1. 智能格式控制
format_instruction = ""
lower_prompt = prompt.lower()
if "ui" in lower_prompt or "text" in lower_prompt:
    format_instruction = "格式要求：必须生成为纯正的 2D 游戏 UI 元素，黑底，居中。"
else:
    format_instruction = "格式要求：请将这些特效生成在一张图里，类似 2x2 的 Sprite Sheet 序列帧，包含：准备、爆发、消散。"

# 2. 强制的一致性约束
consistency_instruction = """
CRITICAL CONSISTENCY REQUIREMENT:
- You MUST maintain PERFECT visual consistency with the provided reference image.
- DO NOT alter the core character design, costume, or color palette.
"""

# 3. 调用图像模型 (图生图 edit 模式)
response = self.client.images.edit(
    model=MODEL_ARTIST,
    image=open(ref_image_path, "rb"),
    prompt=f"Style Reference: {style_guide}\n\nTask: {prompt}\n{consistency_instruction}\n{format_instruction}",
    size="1024x1024"
)
```

#### Step 4: Timeline 编排 `generate_final_plan`

**实现方式**: 调用 GPT-5.4 的 Chat Completions，将所有前序信息汇总为一个 system prompt，用户创意指令作为 user message，要求返回 `json_object` 格式。

到了最后一步，导演手里已经有了首图（底底）和画师刚刚画好的特效、UI 图（图层）。现在他要写剧本了。他会根据 Seedance 的标准格式，按时间段（比如 `[00s-02s]`）排兵布阵。他会用特殊的语法（如 `@slash_vfx.png`）将素材放到特定的层级里（背景层、角色层、VFX层等），并用描述性语言控制这几秒内图片应该怎么动、特效应该怎么爆。这会产出最终提交给 API 的提示词（Prompt）。

**对应代码解释** (`director_agent.py` 中的 `generate_final_plan` 方法截取):

```python
# 1. 提供素材库列表，导演只能从这里面挑东西用
available_files = [os.path.basename(ref_image_path)] + new_assets
asset_manifest = "可用素材库（只能使用这里的图片）:\n" + "\n".join([f"- {f}" for f in available_files])

system_prompt = f"""你是一个高级游戏视频编排导演。
你需要生成最终的 Seedance Timeline Prompt。
{asset_manifest}

请严格遵守时间轴格式:
[00s-03s]
Background: 描述背景运动
Character Action: 描述角色动作，如果使用素材，请用 @素材名.png
VFX: 描述特效产生，如果使用素材，请用 @素材名.png

输出 JSON 包含 `prompt_en` 和 `prompt_zh`。
"""

response = client.chat.completions.create(
    model=MODEL_DIRECTOR,
    response_format={"type": "json_object"},
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"指令：{user_instruction}"}
    ]
)
```

#### Step 5: Web UI 拦截与人工审查 (Prompt Review)

**实现方式**: 后端 `app.py` 不再直接调用视频生成 API，而是将中间结果（草稿状态）返回给前端，由前端展示为可编辑的文本框。用户确认后再调用专门的提交接口。

**文字解释**:
在此前的流程中，大模型生成 Timeline 剧本后，会直接发往火山引擎生成视频，导致容错率低。现在的流程将这一步拆分为两段：先生成草稿返回前端 `draft_submission`，用户在网页上看到“编辑与确认 Prompt”卡片，可以手动微调参数（如动作时间点、特效强度）。用户点击确认后，前端才将最终的 Prompt 和图片素材等一并 POST 到 `/api/submit_task`，随后开启轮询直至下载视频。

**对应代码解释** (`app.py` 中 `/api/generate` 路由截取):

```python
if result["status"] == "success":
    # 1. 动态提取视频时长和长宽比
    duration = max(4, min(15, max_time)) 
    ratio = get_closest_ratio(width, height)
    
    # 2. 不再立即提交到 Seedance，而是构建 draft_submission 暂存数据发给前端
    result["draft_submission"] = {
        "prompt_text": prompt_text,
        "image_paths": image_paths,
        "best_video_path": result.get("best_video_path"),
        "duration": duration,
        "ratio": ratio
    }
    result["logs"].append("✅ 编排完成，等待用户确认 Prompt...")
return jsonify(result)
```

前端 (`script.js`) 收到后，会展示编辑框，用户确认后再向后端的 `/api/submit_task` 发起真正的生成请求。

---

### Path B: `video_only` — 仅视频参考调试

适用场景：跳过生图步骤，专注于调试外部视频参考的分析与融合。

```
首帧图 + 指令
    │
    ├─ Step 1: 视觉感知 (同 Path A Step 1)
    ├─ Step 2: 需求分析 → 提取 reference_video_keywords
    ├─ Step 3: [跳过生图]
    ├─ Step 4: TapTap 爬虫搜索+下载参考视频 (Playwright + yt-dlp)
    ├─ Step 5: MLLM 多模态视频评比 (OpenCV 抽帧 → GPT-5.4 选择最佳)
    ├─ Step 6: ffmpeg 裁剪最佳片段 (3-8秒)
    ├─ Step 7: 融合视频动作特征的 Timeline 编排 (_regenerate_plan_with_video_refs)
    └─ Step 8: 输出 plan (.md + .json)
```

Step 1-2 与 Path A 相同。Step 3 被跳过（`pipeline_mode="video_only"` 时不进入生图分支）。

#### Step 4: TapTap 视频爬虫

**实现方式**: `VideoReferenceScraper.simulate_search_and_download` → 调用 `test_taptap_scraper.py` 中的 `search_and_download_taptap_video`，底层使用 Playwright (Chromium 浏览器自动化) 访问 TapTap 搜索页，定位视频帖子，提取视频 URL 后用 yt-dlp 下载到本地。

#### Step 5-6: 视频分析与裁剪

**实现方式**: `_select_and_analyze_best_video` 用 OpenCV 从每个候选视频均匀抽取 5 帧关键帧，Base64 编码后发送给 GPT-5.4 多模态接口评比，选出最佳视频 + 最佳时间段 + Motion Reference Profile（只提取可复用的动画技法，不搬运剧情）。然后用 ffmpeg 裁剪出指定片段。

#### Step 7: 融合编排

**实现方式**: `_regenerate_plan_with_video_refs` 将视频的 Motion Analysis 注入 system prompt，但严格要求只使用其动画技法（节奏、物理、镜头运动），不照搬视频中的角色或剧情。

---

### Path C: `full_hybrid` — 全混合工作流

适用场景：完整自动化流程，图片素材 + 视频参考同时使用。

```
首帧图 + 指令 (+ 可选本地参考视频)
    │
    ├─ Step 1: 视觉感知 + 元素清点 (同 Path A Step 1)
    ├─ Step 2: 需求分析 (同 Path A Step 2, 同时提取视频关键词)
    ├─ Step 3: [前置] 视频参考获取与分析
    │   ├─ 用户提供本地视频 → 直接 MLLM 分析 + ffmpeg 裁剪
    │   └─ 未提供 → TapTap 爬虫搜索下载 → MLLM 评比 → ffmpeg 裁剪
    ├─ Step 4: AI 素材生成 (同 Path A Step 3, 最多6张)
    ├─ Step 5: 融合视频特征的最终 Timeline 编排 (_regenerate_plan_with_video_refs)
    └─ Step 6: 输出 plan (.md + .json)
```

Path C 的关键区别是 **视频分析在生图之前完成**（前置），这样视频的动作特征可以在后续素材生成和编排阶段被参考。但注意：视频特征**不会注入到生图的 style_dna**（已被移除），以确保生图完全基于首帧风格，只在最终 Timeline 编排时才融合视频的动画技法。

---

## 六、辅助工具


| 脚本                        | 功能                                          |
| ------------------------- | ------------------------------------------- |
| `quick_submit.py`         | 从已有 `.md` 计划文件直接解析并提交 Seedance API          |
| `check_task.py`           | 通过 Task ID 查询任务状态并等待下载                      |
| `run_test.py`             | 三条路径的命令行测试入口 (`--mode a/b/c`)               |
| `mllm_video_extractor.py` | 独立的多模态视频理解模块 (场景检测 + 关键帧分析)                 |
| `test_taptap_scraper.py`  | TapTap 视频爬虫 (Playwright 浏览器自动化 + yt-dlp 下载) |


---

## 七、Web 前端与模式联动 (UI Logic)

**入口**: `http://127.0.0.1:5050` (Flask, `app.py`)

**UI 模式切换机制：**  
前端页面现在提供了明确的“模式选择”单选框。当用户选择“纯图生图 (Plan A)”时，JavaScript 会动态隐藏视频上传框，并向后端传递 `pipeline_mode = 'image_only'`；当选择“视频参考混合 (Plan C)”时，视频上传框出现，向后端传递 `pipeline_mode = 'full_hybrid'`。后端根据这个字段决定是否跳过视频爬虫和视频特征提取环节。同时，前端会根据所选模式，在“视频与生成结果”区域正确地显示“纯图生图模式无需参考视频”或对应的视频占位符，避免视觉歧义。

```javascript
// 前端 script.js: 动态切换 UI
function toggleVideoInput() {
    const pipelineMode = document.querySelector('input[name="pipelineMode"]:checked').value;
    const videoGroup = document.getElementById('videoUploadGroup');
    if (pipelineMode === 'image_only') {
        videoGroup.style.display = 'none'; // 纯图生图隐藏视频上传
    } else {
        videoGroup.style.display = 'block'; // 混合模式显示视频上传
    }
}

// 前端传递参数
formData.append('pipeline_mode', pipelineMode);
```

```python
# 后端 app.py: 接收模式并传给 Director
pipeline_mode = request.form.get('pipeline_mode', 'full_hybrid')

if 'video' in request.files and pipeline_mode != 'image_only':
    # 只有在非纯图生图模式下，才去保存和处理视频
    ...

result = director.run_pipeline(
    instruction, 
    ref_image_path=ref_image_path, 
    pipeline_mode=pipeline_mode, 
    provided_video=ref_video_path
)
```

**功能概览**:

1. 选择游戏项目
2. 选择流水线模式 (image_only / full_hybrid)
3. 动态显隐上传区域：上传首帧图片 + 可选参考视频
4. 输入创意指令
5. 实时查看编排日志
6. 编辑 AI 生成的 Prompt (可修改后再提交)
7. 提交 Seedance API + 轮询等待 + 视频直接播放与下载

**API 路由**:

- `POST /api/generate` — 运行工作流，返回编排草稿
- `POST /api/submit_task` — 接收用户确认的草稿，提交到 Seedance
- `GET /api/check_task/<game>/<task_id>` — 轮询任务状态并下载生成好的 mp4
- `GET /api/games` — 获取游戏列表
- `GET /api/view/<game>/<file>` — 静态文件路由，用于查看素材和生成的视频

---

## 八、环境配置

### 依赖安装

```bash
pip install openai python-dotenv playwright pyautogui pyperclip
pip install opencv-python scenedetect Pillow requests flask
playwright install chromium
```

### 环境变量 (`.env`)

```
OPENAI_API_KEY=your_openai_key
MODEL_DIRECTOR=gpt-5.4          # 可选，默认 gpt-5.4
MODEL_ARTIST=gpt-image-1.5      # 可选，默认 gpt-image-1.5
```

### Seedance API Key

```
keys/seedance_key.txt  ← 填入火山引擎 API Key
```

### 启动 Web 服务

```bash
python app.py
# → http://127.0.0.1:5050
```

