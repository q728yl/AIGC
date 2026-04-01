import os
import json
import datetime
import requests
import base64
import re
import asyncio
import time
from openai import OpenAI
from dotenv import load_dotenv

# 导入真实爬虫逻辑 (需要 playwright 和 yt-dlp)
from test_taptap_scraper import search_and_download_taptap_video

# 1. 环境加载
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

# 模型定义
MODEL_DIRECTOR = os.getenv("MODEL_DIRECTOR", "gpt-5.4") 
MODEL_ARTIST = os.getenv("MODEL_ARTIST", "gpt-image-1.5")

if not api_key:
    print("❌ 错误：请先设置 OPENAI_API_KEY")
    # exit(1) # Don't exit if imported as module

client = OpenAI(api_key=api_key, timeout=120.0)

# 2. 工具函数 (保留 Data URL 用于 Chat 分析)
def encode_image_to_data_url(image_path):
    mime_type = "image/png"
    if image_path.lower().endswith(('.jpg', '.jpeg')): mime_type = "image/jpeg"
    elif image_path.lower().endswith('.webp'): mime_type = "image/webp"
    
    with open(image_path, "rb") as f:
        return f"data:{mime_type};base64,{base64.b64encode(f.read()).decode('utf-8')}"

# 3. 画师 Agent
class AssetGenerator:
    def __init__(self, output_dir):
        self.output_dir = output_dir
        if not os.path.exists(output_dir): os.makedirs(output_dir)

    def generate_image(self, prompt, style_guide, filename_hint="generated", ref_image_path=None):
        """调用 GPT-Image-1.5 绘图"""
        
        # --- 核心优化：注入 Sprite Sheet 或 UI 强制指令与一致性约束 ---
        is_ui = any(k in prompt.lower() for k in ["ui", "hud", "bar", "text", "number", "damage", "icon", "floating combat text", "飘字"])
        is_static_bg = "background" in prompt.lower()
        
        consistency_instruction = """
CRITICAL CONSISTENCY REQUIREMENT:
- You MUST maintain PERFECT visual consistency with the provided reference image.
- DO NOT alter the core character design, costume, or color palette.
- The generated assets (effects, UI, or character states) must look like they were extracted from the EXACT same game engine and exact same character as the reference image.
- Avoid introducing new 3D styles if the reference is 2D pixel art, and vice versa. Match the rendering style meticulously.
"""
        
        format_instruction = ""
        
        if is_ui:
            format_instruction = """
FORMAT REQUIREMENT (GAME UI):
- Generate a FLAT, 2D Game UI Element.
- Frontal view, NO perspective distortion.
- Isolated on a plain background (ready for removal).
- Style: High-quality game interface art.
"""
            if any(k in prompt.lower() for k in ["anim", "sequence", "damage", "text", "floating", "飘字"]):
                format_instruction += """
- Layout: Create a SPRITE SHEET with exactly 3 to 4 frames.
- Composition: Arrange the frames in a 2x2 GRID (e.g., top-left, top-right, bottom-left, bottom-right) rather than a single wide horizontal row to fit the square canvas.
- Saftey Margin: Keep the UI elements fully visible. Leave a moderate empty border (about 10% padding) around the grid so nothing touches the edges or gets cropped, but keep the elements clearly readable.
"""

        elif not is_static_bg:
            format_instruction = """
FORMAT REQUIREMENT (SPRITE):
- Generate a SPRITE SHEET showing an action sequence (Preparation -> Impact -> Follow-through).
- Layout: Arrange the frames in a 2x2 GRID (e.g., top-left, top-right, bottom-left, bottom-right) instead of a long horizontal strip. This ensures they fit perfectly into a square canvas.
- Ensure consistent character details across all frames.
- Isolated on a clean background.
- Saftey Margin: Leave a moderate empty border (about 10% padding) around the edges of the canvas. Ensure NO CROPPING occurs, but keep the characters large enough to maintain high detail and information density.
"""
        
        full_prompt = f"Style Reference: {style_guide}\n\nTask: {prompt}\n{consistency_instruction}\n{format_instruction}".strip()
        print(f"🎨 画师({MODEL_ARTIST}) 正在绘制: {prompt[:30]}...")
        
        try:
            if ref_image_path and os.path.exists(ref_image_path):
                print(f"🖼️ [GPT-Image-1.5 图生图] 正在读取文件流: {os.path.basename(ref_image_path)}")
                
                # 回滚到最初无报错的 API 调用逻辑，仅保留 prompt 层面的排版优化
                with open(ref_image_path, "rb") as image_file:
                    response = client.images.edit(
                        model=MODEL_ARTIST,
                        image=image_file,
                        prompt=full_prompt,
                        n=1,
                        size="1024x1024"
                    )
            else:
                response = client.images.generate(
                    model=MODEL_ARTIST,
                    prompt=full_prompt,
                    n=1,
                    size="1024x1024"
                )

            # 解析结果 (回滚到最初的解析逻辑)
            image_data = None
            if hasattr(response, 'data') and response.data:
                if hasattr(response.data[0], 'b64_json') and response.data[0].b64_json:
                    image_data = base64.b64decode(response.data[0].b64_json)
                elif hasattr(response.data[0], 'url') and response.data[0].url:
                    image_data = requests.get(response.data[0].url).content

            if image_data:
                timestamp = datetime.datetime.now().strftime("%H%M%S")
                filename = f"{filename_hint}_{timestamp}.png"
                filepath = os.path.join(self.output_dir, filename)
                with open(filepath, 'wb') as f:
                    f.write(image_data)
                print(f"✅ 素材已生成: {filename}")
                return filename
            
            return None
        except Exception as e:
            print(f"❌ 绘图模块报错: {e}")
            return None

# 4. 导演 Agent
class SeedanceDirector:
    def __init__(self, game_name="xundaodaqian"):
        self.game_name = game_name
        self.base_dir = os.path.join("seedance_project", "games", game_name)
        
        self.assets_dir = os.path.join(self.base_dir, "assets")
        self.references_dir = os.path.join(self.base_dir, "references")
        self.output_dir = os.path.join(self.base_dir, "output")
        self.docs_dir = os.path.join(self.base_dir, "docs")
        
        # Ensure directories exist
        for d in [self.assets_dir, self.references_dir, self.output_dir, self.docs_dir]:
            if not os.path.exists(d):
                os.makedirs(d)

        self.artist = AssetGenerator(self.assets_dir)
        self.style_dna = "" 
        self.reference_analysis = {}

        # Load shared guide + per-game context
        self.shared_guide = ""
        self.game_context = ""
        self.context_bundle = ""

        shared_guide_path = os.path.join(
            "seedance_project", "docs", "seedance_guide.txt"
        )
        legacy_shared_guide_path = os.path.join(
            "seedance_project", "games", "xundaodaqian", "docs", "seedance_guide.txt"
        )
        context_path = os.path.join(self.docs_dir, "game_context.txt")

        if os.path.exists(shared_guide_path):
            with open(shared_guide_path, 'r', encoding='utf-8') as f:
                self.shared_guide = f.read().strip()
        elif os.path.exists(legacy_shared_guide_path):
            with open(legacy_shared_guide_path, 'r', encoding='utf-8') as f:
                self.shared_guide = f.read().strip()

        if os.path.exists(context_path):
            with open(context_path, 'r', encoding='utf-8') as f:
                self.game_context = f.read().strip()

        context_parts = []
        if self.shared_guide:
            context_parts.append(f"## Shared Seedance Guide\n{self.shared_guide}")
        if self.game_context:
            context_parts.append(f"## Game-Specific Context: {self.game_name}\n{self.game_context}")
        self.context_bundle = "\n\n".join(context_parts).strip()

    def _select_and_analyze_best_video(self, video_paths: list[str], user_instruction: str) -> dict:
        """
        [真实实现] 抽取多个候选视频的关键帧，交给 MLLM 比较。
        选出最匹配需求的一个视频，并给出截取时间段(start_time, end_time)和动作特征总结。
        然后调用 ffmpeg 进行裁剪，返回裁剪后的视频路径和分析结果。
        """
        import cv2
        import base64
        import subprocess
        
        print(f"🔍 正在抽取 {len(video_paths)} 个候选视频的关键帧进行评比...")
        content_messages = [{"type": "text", "text": f"User Instruction: '{user_instruction}'.\nWe have downloaded several candidate gameplay videos. For each video, I will provide a few keyframes. Please evaluate which video best matches the user instruction (e.g. right game, right action like ultimate skill). Also, identify the best time segment to clip (e.g. start_time: '00:02', end_time: '00:08') and provide a detailed motion reference analysis for that segment."}]
        
        valid_paths = []
        for idx, v_path in enumerate(video_paths):
            try:
                cap = cv2.VideoCapture(v_path)
                fps = cap.get(cv2.CAP_PROP_FPS)
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                duration = total_frames / fps if fps > 0 else 0
                
                content_messages.append({"type": "text", "text": f"--- VIDEO {idx+1} --- Path: {os.path.basename(v_path)}, Duration: {duration:.1f}s"})
                
                # 抽取均匀的 5 张图
                for i in [1, total_frames//4, total_frames//2, int(total_frames*0.75), total_frames-2]:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, i))
                    ret, frame = cap.read()
                    if ret:
                        _, buffer = cv2.imencode('.jpg', frame)
                        b64_str = base64.b64encode(buffer).decode('utf-8')
                        content_messages.append({
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{b64_str}", "detail": "low"}
                        })
                cap.release()
                valid_paths.append(v_path)
            except Exception as e:
                print(f"抽取视频 {v_path} 失败: {e}")
                
        if not valid_paths:
            return {"best_video_path": video_paths[0], "analysis": "Fallback analysis due to extraction failure."}
            
        system_prompt = """You are a professional game animation director.
You must compare the candidate videos and select the ONE that best fits the User Instruction.
CRITICAL EVALUATION CRITERIA:
- Reject videos that are mostly static screens, text menus, or lack dynamic movement if the user requested an action (e.g., combat, ultimate skill).
- Reject videos that do not match the user's intent (e.g., if the user wants combat, do not pick a video of someone just clicking through inventory unless it's explicitly asked for).
- Ensure the selected video has clear, active, and relevant motion that can be referenced.

Output a JSON with:
1. "best_video_index": The integer index (1, 2, 3...) of the best video. (If none are good, still pick the closest one but note the flaws in reason).
2. "reason": Why this video is the best and how it aligns with the user's requirements (mentioning motion vs static screens).
3. "start_time": The start time to clip (e.g. "00:02"). Keep it within the video duration. If uncertain, use "00:00".
4. "end_time": The end time to clip (e.g. "00:07"). Keep the clip short (3-8 seconds). If uncertain, use the video duration or a small clip.
5. "motion_analysis": A detailed 'Motion Reference Profile' of the selected segment. Focus ONLY on reusable execution techniques (timing, physics, camera movement, VFX, rhythm). Do NOT describe the specific characters or the narrative events, just the stylistic animation properties that can be applied to any character.
"""
        try:
            print("🤖 请求大模型评比视频并提取动作特征...")
            response = client.chat.completions.create(
                model=MODEL_DIRECTOR,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": content_messages}
                ],
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            
            best_idx = result.get("best_video_index", 1)
            # Ensure index is valid
            best_idx = max(1, min(best_idx, len(valid_paths)))
            best_v_path = valid_paths[best_idx - 1]
            
            print(f"🏆 大模型选中了视频 {best_idx}: {os.path.basename(best_v_path)}")
            print(f"💡 理由: {result.get('reason')}")
            
            start_time = result.get("start_time", "00:00")
            end_time = result.get("end_time", "")
            
            # 使用 ffmpeg 进行裁剪
            trimmed_filename = f"trimmed_best_ref_{int(time.time())}.mp4"
            trimmed_path = os.path.join(self.references_dir, trimmed_filename)
            
            ffmpeg_cmd = [
                "/Users/xd/.local/lib/python3.13/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-x86_64-v7.1",
                "-i", best_v_path,
                "-ss", start_time
            ]
            if end_time:
                ffmpeg_cmd.extend(["-to", end_time])
            ffmpeg_cmd.extend(["-c:v", "libx264", "-c:a", "aac", trimmed_path])
            
            print(f"✂️ 正在裁剪视频: {start_time} 到 {end_time} ...")
            subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            if os.path.exists(trimmed_path):
                print(f"✅ 视频裁剪成功: {trimmed_path}")
                final_path = trimmed_path
            else:
                print("⚠️ 视频裁剪失败，使用原视频。")
                final_path = best_v_path
                
            return {
                "best_video_path": final_path,
                "analysis": result.get("motion_analysis", "Motion reference focus: smooth character animation.")
            }
            
        except Exception as e:
            print(f"⚠️ 视频评比失败: {e}")
            return {
                "best_video_path": video_paths[0] if video_paths else None,
                "analysis": "Reference video motion focus: smooth character animation, impact frames, and dynamic camera follow."
            }

    def _regenerate_plan_with_video_refs(self, user_input, ref_image_path, analysis, original_plan, video_analysis_result, video_paths):
        """
        融合真实视频分析结果，重新生成最终 Timeline，完美承接 Plan A 的编排逻辑
        """
        print("🔄 将视频特征注入 Timeline 编排...")
        
        all_assets = self._scan_assets()
        ref_filename = os.path.basename(ref_image_path) if ref_image_path else "None"
        style_reference = self._build_style_reference()
        
        video_filenames = [os.path.basename(p) for p in video_paths]
        video_refs_str = ", ".join([f"@{v}" for v in video_filenames])
        video_filenames_str = ", ".join(video_filenames)
        new_assets = original_plan.get('selected_assets', [])
        
        system_prompt = f"""
You are the Seedance Creative Director for "{self.game_name}". 
Your goal: Write the FINAL VIDEO PROMPT using a **TIMELINE STRUCTURE**.

## SHARED GUIDE + GAME CONTEXT
{style_reference}

## ASSET MANIFEST
1. **First Frame**: @{ref_filename}
2. **New Assets**: {json.dumps(new_assets)}
3. **Library**: {json.dumps(all_assets)}

## MOTION REFERENCE (ACTUAL SCRAPED VIDEO)
We have successfully scraped reference video(s) for motion style! 
Filenames: {video_filenames_str}
Motion Analysis of the Video: 
"{video_analysis_result}"

Your task is to merge this external Motion Reference into the timeline.
CRITICAL RULES FOR VIDEO REFERENCE:
- DO NOT just blindly copy the exact events or storyline from the reference video.
- The Core Storyline and Events MUST be strictly driven by the "Original user input" and the context of the "First Frame".
- ONLY extract the USEFUL execution techniques from the video analysis (e.g., timing, combat rhythm, hit pause, camera shake, UI popping style, particle emission patterns).
- If the video shows a different specific action than what the user requested, ignore the video's action semantics and ONLY apply its dynamic physics/rhythm/camera-work to the user's requested action.

## PROMPT RULES (TIMELINE & LAYERS)
1. **Start with**: "First Frame: @{ref_filename}. Reference Video: {video_refs_str}..."
2. **Timeline Format**: Use `[00s-05s]` style to describe the sequence of events.
3. **Layering**: Explicitly state where elements appear.
   - **(Background Layer)**: Scene changes, parallax scrolling.
   - **(Character/Action Layer)**: Character movements or Live2D poses using @sprite_sheets.
   - **(VFX Layer)**: Magic/Explosions/Click Effects overlay using @vfx_assets.
   - **(UI Layer)**: Floating combat text (飘字), damage numbers, pop-up windows, store feedback using @ui_assets.
4. Respect the shared Seedance workflow, but keep the final visuals faithful to this game's own art style, rhythm, camera language, and environment notes.
5. Treat the first frame composition and image_type as a hard lock:
   - Preserve the original arrangement from the first frame.
   - Do not convert a non-combat scene into a combat scene randomly.
   - Preserve the focus anchors, UI anchor, and motion flow from the reference frame.
   - Explicitly describe the action/interaction using the same layout axis as the first frame.
6. **Strict Logic Continuity**: Follow the `Perception & Game Logic Lock`. Ensure the generated actions directly continue the momentum of the first frame. DO NOT restart the sequence. Tailor the entire timeline to flow logically from the exact initial state.
7. **CRITICAL IMAGE LIMIT**: You MUST NOT reference more than 9 assets in total (including the First Frame, New Assets, Library assets, and the new Video). Select only the most essential assets.

## ⚠️ ELEMENT-GROUNDED PROMPT WRITING
- ONLY reference characters/enemies visible in the Element Inventory from the composition lock.
- DO NOT invent new characters or scene changes not grounded in the first frame.
- If a skill is already in progress in the first frame, follow through. If not, you may build toward one but the progression must be smooth and gradual — no abrupt jump to a climax.
- VFX style must match the existing scene's art style and color palette. Escalation is fine if it builds naturally.
- Use the reference video ONLY for motion technique (timing, rhythm, camera shake) — NOT for its story, characters, or specific abilities.
"""
        
        user_instruction = f"""
Original user input: "{user_input}"

Your goal is to generate the final script, merging the image assets with the new reference video seamlessly, ensuring it naturally follows the original logic and styling constraints.

You MUST output a valid JSON.
CRITICAL INSTRUCTIONS FOR JSON FIELDS:
1. "thought": "Explain how to blend the reference motion with the first frame."
2. "selected_assets": "You MUST output a SINGLE LIST OF STRINGS containing all previous image filenames AND the new video filenames. E.g. ['0045.jpg', 'effect.png', '{video_filenames[0] if video_filenames else 'video.mp4'}']"
3. "prompt_en": "Your English prompt MUST start EXACTLY with this prefix: 'First Frame: @{ref_filename}. Reference Video: {video_refs_str}. Motion Style Reference: ...'. Then write the [00s-xxs] timeline."
4. "prompt_zh": "Your Chinese prompt MUST start EXACTLY with this prefix: '> 首帧锁定: @{ref_filename}。参考视频: {video_refs_str}。动作风格参考: ...'. Then write the [00s-xxs] timeline."

If you do not include the exact video filenames {video_filenames_str} in the selected_assets array and the prompts, the video generation system will fail.
"""
        try:
            response = client.chat.completions.create(
                model=MODEL_DIRECTOR,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_instruction}],
                response_format={"type": "json_object"}
            )
            final_plan = json.loads(response.choices[0].message.content)
            
            filename = f"final_plan_with_video_refs_{int(time.time())}.json"
            save_path = os.path.join(self.output_dir, filename)
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(final_plan, f, indent=2, ensure_ascii=False)
                
            # 我们同时也将这个带有视频的最终版存为 md 文件以便阅读
            md_path = self.save_plan(final_plan, user_input + "_with_video")
            print(f"✅ JSON saved at: {save_path}")
            print(f"✅ Markdown saved at: {md_path}")
            
            return md_path
            
        except Exception as e:
            print(f"JSON 解析失败或生成失败: {e}")
            return None

    def _build_composition_lock(self):
        if not self.reference_analysis:
            return ""

        image_type = self.reference_analysis.get("image_type", "unknown")
        layout_axis = self.reference_analysis.get("layout_axis", "unknown")
        primary_focus = self.reference_analysis.get("primary_focus_anchor", "unknown")
        secondary_focus = self.reference_analysis.get("secondary_focus_anchor", "unknown")
        ui_anchor = self.reference_analysis.get("ui_anchor", "unknown")
        camera_angle = self.reference_analysis.get("camera_angle", "unknown")
        motion_flow = self.reference_analysis.get("motion_or_flow_direction", "unknown")
        composition_summary = self.reference_analysis.get("composition_summary", "")
        
        # Perception fields
        scene_state = self.reference_analysis.get("scene_state", "unknown")
        scene_context_summary = self.reference_analysis.get("scene_context_summary", "")
        game_logic_plan = self.reference_analysis.get("game_logic_plan", "")

        # Element inventory fields
        visible_characters = self.reference_analysis.get("visible_characters", [])
        visible_enemies = self.reference_analysis.get("visible_enemies", [])
        visible_effects = self.reference_analysis.get("visible_effects", [])
        visible_ui_elements = self.reference_analysis.get("visible_ui_elements", [])
        background_desc = self.reference_analysis.get("background_description", "")
        absent_warnings = self.reference_analysis.get("absent_elements_warning", [])

        chars_str = json.dumps(visible_characters, ensure_ascii=False) if visible_characters else "None detected"
        enemies_str = json.dumps(visible_enemies, ensure_ascii=False) if visible_enemies else "None detected"
        effects_str = ", ".join(visible_effects) if visible_effects else "None detected"
        ui_str = ", ".join(visible_ui_elements) if visible_ui_elements else "None detected"
        absent_str = "\n".join([f"  - {w}" for w in absent_warnings]) if absent_warnings else "  - (none listed)"

        return f"""## Composition & Image Type Lock From Reference Frame
- image_type: {image_type}
- layout_axis: {layout_axis}
- primary_focus_anchor: {primary_focus}
- secondary_focus_anchor: {secondary_focus}
- ui_anchor: {ui_anchor}
- camera_angle: {camera_angle}
- motion_or_flow_direction: {motion_flow}
- composition_summary: {composition_summary}

Mandatory composition rules:
- Preserve the original first-frame composition and arrangement.
- Respect the identified image_type (e.g., do not turn a store UI into a combat scene, or a community post into a gacha pull).
- Keep the relative anchor positions consistent with the first frame.
- Visual flow, interaction direction, or attack travel path must follow the same scene axis as the first frame.

## Element Inventory (GROUND TRUTH from First Frame)
**Characters on screen**: {chars_str}
**Enemies on screen**: {enemies_str}
**Active VFX**: {effects_str}
**UI/HUD elements**: {ui_str}
**Background**: {background_desc}

### ⚠️ ABSENT ELEMENTS — DO NOT INVENT THESE:
{absent_str}

**HARD RULES based on Element Inventory:**
- You may ONLY reference characters/enemies that appear in the Element Inventory above.
- DO NOT invent new characters, new enemies, or new factions that are not visible in the first frame.
- If the first frame already shows a skill/ultimate in progress, CONTINUE and FOLLOW THROUGH with it naturally.
- If no skill is visible, you MAY introduce one, but it must build up smoothly from the current pose/state — no sudden jump cuts or abrupt power-ups. The progression should feel like a natural next beat (e.g., idle → gather energy → release), not a jarring teleport to a climax frame.
- VFX must be stylistically consistent with what's already on screen (same color palette, same art style, same energy level). New VFX should feel like they belong in the same scene, not imported from a different game.
- The background/environment MUST remain the same as described above. Do not teleport to a new location.
- If the Element Inventory shows only 1 character with no enemy, do NOT introduce an enemy out of nowhere. Animate the existing character's natural next action instead.

## Perception & Game Logic Lock
- Current Scene State: {scene_state}
- Scene Context: {scene_context_summary}
- Recommended Game Logic Progression: {game_logic_plan}

Mandatory Logic Rules:
- STRICTLY follow the first frame's state and image_type. DO NOT contradict the scene context.
- The timeline MUST be a natural continuation of the EXACT moment shown in the first frame. Treat the first frame as frame 0 of the video — everything flows forward from there.
- [BATTLE] If it's a 'mid-battle' image with a skill in progress, continue resolving that skill naturally. If it's 'pre-battle' or the characters are idle/ready, you may build toward a skill release, but do it with a smooth ramp-up — no jarring instant teleport to the climax.
- [STORE/UI] If it's a 'store_ui', start with user interaction (e.g., hovering/clicking an item), followed by UI feedback (glowing borders, pop-up confirmation), and character Live2D reaction.
- [GACHA] If it's a 'gacha_pull', simulate the pull animation, suspense build-up, and character reveal.
- [PROMO/COMMUNITY] If it's a 'promotional_art' or community strategy image, focus on parallax scrolling, subtle environmental effects (wind, glowing text), and showcasing key highlights without forcing a battle.
- DO NOT use generic one-size-fits-all templates. Tailor every timeline beat to the observed scene. Escalation and skill release are allowed, but the progression must feel smooth and earned — build up naturally from the first frame's current state."""

    def _build_style_reference(self):
        style_parts = []
        if self.context_bundle:
            style_parts.append(self.context_bundle)
        composition_lock = self._build_composition_lock()
        if composition_lock:
            style_parts.append(composition_lock)
        if self.style_dna:
            style_parts.append(f"## Visual DNA from Reference Frame\n{self.style_dna}")
        return "\n\n".join(style_parts).strip()

    def _scan_assets(self):
        if not os.path.exists(self.assets_dir): os.makedirs(self.assets_dir)
        return [f for f in os.listdir(self.assets_dir) if f.lower().endswith(('.jpg', '.png', '.mp4'))]

    def _analyze_visual_style(self, image_path):
        """导演视觉分析 + 场景感知 + 画面元素清点"""
        print(f"👁️  导演正在分析首图风格与场景感知: {os.path.basename(image_path)}...")
        data_url = encode_image_to_data_url(image_path)
        try:
            response = client.chat.completions.create(
                model=MODEL_DIRECTOR,
                messages=[
                    {
                        "role": "system",
                        "content": """You are an Art Director, Layout Analyst, and Game Logic Designer.
Analyze the screenshot and return a JSON object that captures visual style, composition, the CURRENT SCENE STATE, and a COMPLETE INVENTORY of all visible elements.

You must identify:
- image_type: The overall category of the image. Must be one of ["battle", "store_ui", "character_select", "gacha_pull", "promotional_art", "dialogue_scene", "other"].
- style_summary: concise art/style summary
- layout_axis: one of ["vertical", "horizontal", "diagonal", "mixed", "unknown"]
- primary_focus_anchor: where the main focal point (e.g., hero, featured character, main UI panel) is anchored ["top", "bottom", "left", "right", "center", "unknown"]
- secondary_focus_anchor: where the secondary element (e.g., enemy, secondary UI, background elements) is anchored
- ui_anchor: where the main UI elements are anchored
- camera_angle: short phrase for camera/view angle
- motion_or_flow_direction: likely visual flow or attack travel direction in the frame
- composition_summary: 1-2 sentences describing the exact composition that must be preserved
- scene_state: What is the current state? For battle: ["pre-battle", "mid-battle", "post-battle"]. For UI/store: ["idle", "interacting", "loading", "unknown"].
- scene_context_summary: Describe exactly what is happening in this specific frame. Are there projectiles mid-air? Is a character posing for a gacha pull? Is a store item highlighted?
- game_logic_plan: Based on the image_type and scene_context_summary, plan a logical 3-step sequence for what should happen NEXT in the video. For battle, continue the combat logic. For store UI, maybe simulate a user clicking 'Buy' and a pop-up appearing. For gacha, simulate the pull animation revealing a character. Tailor this entirely to the current frame.

## CRITICAL: ELEMENT INVENTORY
You MUST provide a thorough inventory of EVERY visible element in the image. This is used to prevent downstream steps from inventing elements that don't exist.

- visible_characters: A list of objects, each with {"description": "...", "position": "left/right/center/...", "action_state": "idle/attacking/casting/hit/..."}. Describe appearance (color, weapon, species) but do NOT invent names or abilities.
- visible_enemies: Same format as visible_characters, for any opponents/monsters in the scene. Empty list if none.
- visible_effects: List of strings describing VFX currently on screen (e.g., "blue energy beam mid-screen", "fire particles around left character"). Empty list if none.
- visible_ui_elements: List of strings describing HUD/UI elements (e.g., "HP bar top-left", "damage number -3842 floating center", "skill cooldown icons bottom"). Empty list if none.
- background_description: 1-2 sentences describing the background/environment as it appears.
- absent_elements_warning: Explicitly list things that are NOT in the image that a model might hallucinate (e.g., "No ultimate skill charging", "No second enemy", "No treasure chest"). List at least 3 items.

Focus on preserving layout and strictly adhering to the first frame's state. Be EXHAUSTIVE in the element inventory."""
                    },
                    {"role": "user", "content": [
                        {"type": "text", "text": "Extract visual style, composition lock, perceive the scene state, and provide a COMPLETE ELEMENT INVENTORY of everything visible in this screenshot."},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]}
                ],
                response_format={"type": "json_object"}
            )
            result = json.loads(response.choices[0].message.content)
            self.reference_analysis = result
            return result.get("style_summary", "")
        except Exception as e:
            self.reference_analysis = {
                "image_type": "unknown",
                "layout_axis": "unknown",
                "primary_focus_anchor": "unknown",
                "secondary_focus_anchor": "unknown",
                "ui_anchor": "unknown",
                "camera_angle": "unknown",
                "motion_or_flow_direction": "unknown",
                "composition_summary": "Preserve the original first-frame composition as closely as possible.",
                "scene_state": "unknown",
                "scene_context_summary": "Unable to analyze scene context.",
                "game_logic_plan": "Proceed with a generic logical sequence.",
                "visible_characters": [],
                "visible_enemies": [],
                "visible_effects": [],
                "visible_ui_elements": [],
                "background_description": "Unknown background.",
                "absent_elements_warning": []
            }
            return "Wuxia/Fantasy hand-drawn art style."

    def analyze_needs(self, user_instruction, ref_image_path=None):
        if ref_image_path: self.style_dna = self._analyze_visual_style(ref_image_path)
        style_reference = self._build_style_reference()
        
        system_prompt = f"""You are a Creative Director for the game "{self.game_name}". 
        
        Shared Guide and Game Context:
        {style_reference}
        
        Instruction:
        - Follow the shared Seedance guide as the global generation rulebook.
        - Apply the game-specific context as the local art direction for this title.
        - If the shared guide and game context differ, keep the shared guide's structure/workflow, but prioritize the current game's art style, feel, and environment details.
        # 3. 泛化场景兼容设计
        - The first frame composition is a hard constraint. Asset planning must support the original layout and image_type from the reference image.
        - If the screenshot shows top-vs-bottom factions, request assets that fit top-vs-bottom staging rather than left-vs-right staging.
        - STRICTLY follow the 'Perception & Game Logic Lock'. Adapt the assets generated to the image_type:
          * For battle: generate attack sprites, VFX, damage numbers (floating combat text), UI hit feedback.
          * For store_ui: generate interactive UI elements (clicks, glowing borders, pop-ups, "Purchase" buttons, rotating coin/gem icons), character Live2D idle/reaction poses, or promotional banners.
          * For gacha_pull/character_select: generate card flip animations, rarity reveal VFX (golden/rainbow sparks), character entrance effects.
          * For promotional_art/community_post: generate subtle environmental animations (wind, glowing text, parallax background elements).
          * For dialogue_scene: generate character portraits with different expressions, text boxes, typing indicators.
        
        Analyze the user request and decide what SUPPLEMENTARY assets are needed.
        IMPORTANT: Limit your image asset request to a MAXIMUM of 6 key assets.

        ## ⚠️ CRITICAL: ELEMENT-GROUNDED ASSET PLANNING
        The Element Inventory in the composition lock above is GROUND TRUTH. Your asset requests MUST obey these rules:

        1. **NO NEW CHARACTERS**: Do NOT request sprite sheets for characters/enemies that do not appear in the Element Inventory. If only one hero is visible, do NOT generate a "second hero" or "ally support character".
        2. **SMOOTH PROGRESSION, NOT SUDDEN JUMPS**: 
           - If the first frame already shows a skill/ultimate in progress → generate assets to complete that skill's full animation arc (impact, aftermath, etc.).
           - If no skill is visible → you MAY generate skill/ultimate VFX, but the assets must support a smooth build-up from the current state (e.g., energy gathering → cast → release). Do NOT skip straight to the climax explosion.
           - Always match the VFX art style and color palette to what's already visible.
        3. **SUPPLEMENT, DON'T REPLACE**: Your assets should enhance and extend the existing scene. Examples:
           - Image shows a sword mid-swing → request: slash trail VFX, hit impact sparks, damage number UI
           - Image shows a character idle → request: skill charge-up aura, energy gather particles (to smoothly transition INTO an action)
           - Image shows a character in a store → request: button glow effect, click ripple, item highlight border
        4. **MATCH THE SCALE**: Escalation is fine, but it must be gradual. Don't jump from a calm idle to a screen-filling explosion in one step — provide intermediate build-up assets.
        5. **SAME ENVIRONMENT**: Do NOT request new background assets that change the scene. The background stays as-is from the first frame.
        6. **ABSENT ELEMENTS WARNING**: Refer to the "absent_elements_warning" list in the Element Inventory. Do not generate assets for elements that contradict the scene.
        
        ## THINKING DYNAMICALLY (SPRITE SHEETS & UI & FX)
        - **Characters**: ONLY request additional frames/states for characters already visible (e.g., hit reaction for the existing enemy, follow-through for the hero's current attack).
        - **VFX/Animations**: Request VFX that naturally accompany the CURRENT action (e.g., slash trail for a sword visible in the image), not unrelated effects.
        - **UI/HUD**: Explicitly ask for **"Game UI elements"** that match the existing UI style visible in the image.
          - Examples: "-9999 Critical Hit" (Floating Combat Text), "Purchase Success Pop-up", "Gacha SR Card Reveal".
          - Specify if it should be floating (animated) or fixed (static).
          
        ## REFERENCE VIDEOS (PLAN B WORKFLOW)
        - If the user request implies a complex motion sequence that would benefit from a reference video, recommend 1-2 exact search queries for an external scraper.
        - The keywords MUST strongly include the game's official Chinese name (e.g. "寻道大千") combined with ONE specific action keyword.
        - Example: "寻道大千 战斗", "寻道大千 抽卡", "寻道大千 大招".
        - KEEP IT SHORT. Do not use long phrases like "大招 实机演示" as Chinese platforms like TapTap will return zero results for long queries. Maximum 2-3 words.
        
        Output JSON:
        {{
            "thought": "Reasoning about what's visible and what supplementary assets are needed to animate the existing scene...",
            "missing_assets": [
                {{"filename_hint": "enemy_attack_sheet", "description": "A horizontal sprite sheet of the enemy performing a heavy slash attack (3 frames)."}},
                {{"filename_hint": "crit_damage_ui", "description": "Game UI asset: A bright red '-9999' critical damage number. Isolated, bold font."}}
            ],
            "reference_video_keywords": ["TapTap idle RPG generic attack motion"]
        }}
        """
        
        response = client.chat.completions.create(
            model=MODEL_DIRECTOR,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_instruction}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)

    def generate_final_plan(self, user_instruction, new_assets, needs_analysis_result, ref_image_path=None):
        all_assets = self._scan_assets()
        ref_filename = os.path.basename(ref_image_path) if ref_image_path else "None"
        style_reference = self._build_style_reference()
        ref_videos = needs_analysis_result.get("reference_video_keywords", [])
        
        system_prompt = f"""
You are the Seedance Creative Director for "{self.game_name}". 
Your goal: Write the FINAL VIDEO PROMPT using a **TIMELINE STRUCTURE**.

## SHARED GUIDE + GAME CONTEXT
{style_reference}

## ASSET MANIFEST
1. **First Frame**: @{ref_filename}
2. **New Assets**: {json.dumps(new_assets)}
3. **Library**: {json.dumps(all_assets)}

## REFERENCE VIDEO STYLE (PLAN B)
If the system has identified reference video keywords ({json.dumps(ref_videos)}), include a section in your thought process on how to blend this external motion style into the generated prompt.

## PROMPT RULES (TIMELINE & LAYERS)
1. **Start with**: "First Frame: @{ref_filename}..."
2. **Timeline Format**: Use `[00s-05s]` style to describe the sequence of events.
3. **Layering**: Explicitly state where elements appear.
   - **(Background Layer)**: Scene changes, parallax scrolling.
   - **(Character/Action Layer)**: Character movements or Live2D poses using @sprite_sheets.
   - **(VFX Layer)**: Magic/Explosions/Click Effects overlay using @vfx_assets.
   - **(UI Layer)**: Floating combat text (飘字), damage numbers, pop-up windows, store feedback using @ui_assets.
4. Respect the shared Seedance workflow, but keep the final visuals faithful to this game's own art style, rhythm, camera language, and environment notes.
5. Treat the first frame composition and image_type as a hard lock:
   - Preserve the original arrangement from the first frame.
   - Do not convert a non-combat scene into a combat scene randomly.
   - Preserve the focus anchors, UI anchor, and motion flow from the reference frame.
   - Explicitly describe the action/interaction using the same layout axis as the first frame.
6. **Strict Logic Continuity**: Follow the `Perception & Game Logic Lock`. Ensure the generated actions directly continue the momentum of the first frame. DO NOT restart the sequence. Tailor the entire timeline to flow logically from the exact initial state:
   - Battle: Resolve mid-air attacks, manage hit impacts and clear floating damage numbers (飘字).
   - Store UI: Execute store purchases, hover interactions, item showcases.
   - Promo/Community: Add atmospheric life, highlighting featured elements without breaking the static layout.
7. **CRITICAL IMAGE LIMIT**: You MUST NOT reference more than 9 images in total (including the First Frame, New Assets, and Library assets combined). Select only the most essential assets to ensure the prompt remains within the 9-image limit.

## ⚠️ CRITICAL: ELEMENT-GROUNDED PROMPT WRITING
Your prompt MUST be grounded in the Element Inventory from the composition lock above. This is the most important rule.

**FORBIDDEN actions in the prompt:**
- ❌ Introducing characters/enemies not listed in the Element Inventory.
- ❌ Changing the background or teleporting to a new environment.
- ❌ Adding VFX that contradict the current scene's style (e.g., ice magic when the image shows fire effects, sci-fi beams in a wuxia scene).
- ❌ Creating narrative arcs that have zero basis in the first frame (e.g., sudden villain reveal, victory celebration when the battle just started).
- ❌ Abrupt jump cuts — going from a calm/idle state directly to a climax explosion with no build-up in between.

**REQUIRED approach — SMOOTH CONTINUATION:**
- ✅ Treat the first frame as frame 0. The video must feel like pressing "play" on a paused scene.
- ✅ If a skill/ultimate is already in progress → follow through naturally: impact lands, VFX dissipates, target reacts.
- ✅ If no skill is visible but the scene supports action → you MAY build toward a skill, but do it gradually: subtle energy gather (0-2s) → charge-up intensifies (2-3s) → release (3-5s). The progression must feel earned, not teleported.
- ✅ If a character is idle in a non-combat scene → animate naturally (breathing, cloth sway, environmental particles). You can introduce gentle interaction but don't force combat.
- ✅ If UI elements are visible, animate them (HP bar ticking, damage numbers fading, skill cooldown rotating).
- ✅ Energy level should progress smoothly — calm scenes can build intensity gradually, intense scenes maintain or resolve intensity. No sudden spikes or drops.
- ✅ Every element you mention in the prompt must trace back to something visible in the Element Inventory or the newly generated supplementary assets.

## Output JSON
{{
    "thought": "First, I list what's visible in the first frame. Then I plan what naturally happens next, without inventing new elements...",
    "selected_assets": ["list", "of", "filenames"],
    "reference_video_strategy": "If reference videos were provided, explain what visual elements (motion, VFX, camera) from them should be integrated into the timeline.",
    "prompt_en": "First Frame: @{ref_filename}. [00s-02s] (Action Layer) The existing hero's sword completes its arc... [02s-04s] (UI Layer) The damage number already visible continues to float upward and fade...",
    "prompt_zh": "中文版时间轴剧本..."
}}
"""
        response = client.chat.completions.create(
            model=MODEL_DIRECTOR,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_instruction}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)

    def save_plan(self, plan, user_instruction):
        if not os.path.exists(self.output_dir): os.makedirs(self.output_dir)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_instruction = "".join([c for c in user_instruction if c.isalnum()])[:10]
        filename = f"{timestamp}_{safe_instruction}.md"
        filepath = os.path.join(self.output_dir, filename)
        
        content = f"""# Seedance Plan ({self.game_name})
> Instruction: {user_instruction}
> Date: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. Director's Thought
{plan.get('thought')}

## 2. Selected Assets
`{', '.join(plan.get('selected_assets', []))}`

## 3. English Prompt
```text
{plan.get('prompt_en')}
```

## 4. Chinese Prompt
> {plan.get('prompt_zh')}
"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return filepath

    def run_pipeline(self, user_instruction, ref_image_path=None, pipeline_mode="auto", provided_video=None):
        """API 调用入口
        pipeline_mode: 
          - "auto": 默认走图生逻辑，不自动爬视频。
          - "image_only": 仅生成图片，不包含视频。
          - "video_only": 跳过生图，仅调试视频。
          - "full_hybrid": (Plan C) 自动先爬取/分析参考视频，再根据视频分析结果去指导生图，最后生成混合 Timeline。
        provided_video: 如果提供，将跳过爬虫直接使用该视频
        """
        result = {
            "status": "success",
            "logs": [],
            "new_assets": [],
            "plan_path": "",
            "plan_content": {},
            "reference_video_keywords": [],
            "best_video_path": None,
            "video_analysis_result": None
        }
        
        def log(msg):
            print(msg)
            result["logs"].append(msg)

        log(f"🎬 Director started for game: {self.game_name} (Mode: {pipeline_mode})")
        
        try:
            if ref_image_path:
                log(f"🖼️ Reference image: {os.path.basename(ref_image_path)}")
            
            log("🤔 Analyzing needs...")
            needs = self.analyze_needs(user_instruction, ref_image_path)
            
            # --- 提前处理视频爬取 (Full Hybrid 模式下) ---
            ref_videos = needs.get("reference_video_keywords", [])
            if ref_videos:
                log(f"🎥 Identified Reference Video Keywords: {ref_videos}")
                result["reference_video_keywords"] = ref_videos
                
            if pipeline_mode == "full_hybrid":
                log("⚙️ [Plan C - Full Hybrid] 启动前置视频参考提取...")
                
                if provided_video and os.path.exists(provided_video):
                    log(f"✅ 使用指定的本地参考视频: {provided_video}")
                    result["best_video_path"] = provided_video
                    
                    log("🤔 正在分析指定的本地参考视频...")
                    analysis_result = self._select_and_analyze_best_video([provided_video], user_instruction)
                    result["best_video_path"] = analysis_result.get("best_video_path")
                    result["video_analysis_result"] = analysis_result.get("analysis")
                    log(f"✨ 获得外部视频参考指引！")
                else:
                    if provided_video:
                        log(f"⚠️ 指定的视频不存在: {provided_video}，将回退到自动爬取")
                    scraper = VideoReferenceScraper(self.references_dir)
                    
                    downloaded_paths = None
                    target_kw = ""
                    for kw in ref_videos:
                        log(f"🔄 尝试使用关键词进行爬取: {kw}")
                        paths = scraper.simulate_search_and_download(kw, self.game_name)
                        if paths:
                            downloaded_paths = paths
                            target_kw = kw
                            log(f"✅ 成功通过关键词 '{kw}' 获取到视频。")
                            break
                        else:
                            log(f"⚠️ 关键词 '{kw}' 未能获取到视频，继续尝试下一个...")
                    
                    if downloaded_paths:
                        analysis_result = self._select_and_analyze_best_video(downloaded_paths, user_instruction)
                        result["best_video_path"] = analysis_result.get("best_video_path")
                        result["video_analysis_result"] = analysis_result.get("analysis")
                        log(f"✨ 获得外部视频参考指引！")
                        # 移除将视频特征注入到 style_dna 的逻辑，确保生图完全基于首图
                        # self.style_dna += f"\n[Video Motion Profile]: {result['video_analysis_result']}"
            # ---------------------------------------------

            # --- 生成图片及资产规划流程 ---
            new_assets = []
            if pipeline_mode in ["auto", "image_only", "full_hybrid"]:
                if needs.get("missing_assets"):
                    limited_assets = needs["missing_assets"][:6]
                    log(f"🎨 Generating {len(limited_assets)} new assets...")
                    
                    for item in limited_assets:
                        log(f"   - Generating: {item['filename_hint']}...")
                        res = self.artist.generate_image(
                            item['description'],
                            self._build_style_reference(),
                            item['filename_hint'],
                            ref_image_path
                        )
                        if res: 
                            new_assets.append(res)
                            result["new_assets"].append(res)
            elif pipeline_mode == "video_only":
                log("⏭️ 当前为 video_only 模式，跳过生图环节...")
            
            # --- 最终计划生成 ---
            log("📝 Writing final plan...")
            
            if pipeline_mode == "full_hybrid" and result["best_video_path"]:
                # 如果是全混合模式且成功拿到了视频，直接调用 _regenerate 获得带视频引用的最终版本
                log("🔄 直接生成带有真实视频参考的 Timeline 编排...")
                plan_path = self._regenerate_plan_with_video_refs(
                    user_instruction, ref_image_path, self.reference_analysis, 
                    {"selected_assets": new_assets}, result["video_analysis_result"], [result["best_video_path"]]
                )
                if plan_path:
                    # 尝试读取刚刚写入的 JSON 文件来作为返回值
                    import glob
                    json_files = sorted(glob.glob(os.path.join(self.output_dir, "final_plan_with_video_refs_*.json")), key=os.path.getmtime, reverse=True)
                    if json_files:
                        with open(json_files[0], 'r', encoding='utf-8') as f:
                            plan = json.load(f)
                    else:
                        plan = {}
                else:
                    plan = self.generate_final_plan(user_instruction, new_assets, needs, ref_image_path)
                    plan_path = self.save_plan(plan, user_instruction)
            else:
                # 默认普通生成
                plan = self.generate_final_plan(user_instruction, new_assets, needs, ref_image_path)
                plan_path = self.save_plan(plan, user_instruction)
            
            result["plan_path"] = plan_path
            result["plan_content"] = plan
            log("✅ Pipeline completed successfully!")
            
            return result
            
        except Exception as e:
            log(f"❌ Error: {str(e)}")
            result["status"] = "error"
            result["error"] = str(e)
            return result

# 6. 新增：参考视频爬取与编排模块 (路径 B)
class VideoReferenceScraper:
    def __init__(self, download_dir):
        self.download_dir = download_dir
        if not os.path.exists(self.download_dir):
            os.makedirs(self.download_dir)
            
    def simulate_search_and_download(self, keyword, game_name):
        """
        [真实实现] 从 TapTap 抓取参考视频
        使用 Playwright 获取链接，使用 yt-dlp 进行真实下载。
        """
        import asyncio
        from test_taptap_scraper import search_and_download_taptap_video
        
        print(f"\n🕷️ [路径 B] 启动真实视频爬虫模块...")
        print(f"🔍 正在平台中搜索关键词: '{keyword}'")
        
        # 调用我们写好的真实爬虫函数 (使用 asyncio.run 执行异步函数)
        try:
            downloaded_paths = asyncio.run(search_and_download_taptap_video(game_name, keyword, self.download_dir))
            
            if downloaded_paths and len(downloaded_paths) > 0:
                print(f"✅ 真实下载完成，共找到 {len(downloaded_paths)} 个参考视频。")
                return downloaded_paths
            else:
                print(f"⚠️ 未能自动下载到关于 '{keyword}' 的参考视频，返回 None。")
                return None
        except Exception as e:
            print(f"❌ 真实爬取执行失败: {e}")
            return None

# ==========================================

# 5. 主循环 (CLI 兼容)
def main():
    # 默认使用寻道大千
    director = SeedanceDirector("xundaodaqian")
    scraper = VideoReferenceScraper(director.references_dir)
    print(f"🎬 Seedance AI 导演组已就绪 (Game: {director.game_name})")
    print(f"📂 Assets Dir: {director.assets_dir}")
    
    while True:
        user_input = input("\n🎥 请输入创意指令 (输入 'q' 退出): ")
        if user_input.lower() == 'q': break
        
        # 路径识别
        ref_image_path = None
        if "references/" in user_input:
             parts = user_input.split()
             for part in parts:
                 if "references/" in part or part.endswith(('.jpg', '.png')):
                     fname = os.path.basename(part)
                     potential_path = os.path.join(director.references_dir, fname)
                     if os.path.exists(potential_path):
                         ref_image_path = potential_path
                         break
        
        if not ref_image_path:
             for f in os.listdir(director.references_dir):
                if f in user_input:
                    ref_image_path = os.path.join(director.references_dir, f)
                    break

        res = director.run_pipeline(user_input, ref_image_path)
        
        # --- 扩展路径 B 工作流编排 ---
        if res["status"] == "success" and "reference_video_keywords" in res and res["reference_video_keywords"]:
            print("\n🔄 检测到场景支持视频参考，开始路径 B (外部视频参考) 工作流...")
            
            downloaded_videos = None
            for keyword in res["reference_video_keywords"]:
                print(f"🔄 尝试爬取关键词: {keyword}")
                paths = scraper.simulate_search_and_download(keyword, director.game_name)
                if paths:
                    downloaded_videos = paths
                    print(f"✅ 已成功获取到参考视频 (关键词: {keyword})")
                    break
                else:
                    print(f"⚠️ 关键词 '{keyword}' 未能获取到合适的视频，继续尝试...")
                    
            if downloaded_videos:
                print(f"🎉 路径 B 执行成功，共下载 {len(downloaded_videos)} 个参考视频。")
                print("➡️ 下一步 (Plan B 阶段 3): 调用视觉大模型解析这批视频，并提取动态参考特征融入 Timeline!")
                
                # 分析下载的视频
                print("🎬 正在使用多模态大模型分析参考视频的动态特征...")
                analysis_result = director._select_and_analyze_best_video(downloaded_videos, user_input)
                best_video = analysis_result.get("best_video_path")
                video_analysis_result = analysis_result.get("analysis")
                
                if video_analysis_result:
                    print("✨ 视频动态特征提取成功！将此特征注入到最终的 Timeline 生成中。")
                    
                    # 在原始的 plan_path JSON 旁边生成一个注入了视频参考的新 JSON
                    try:
                        # 重新调用生成 timeline，这次带上视频参考特征
                        enhanced_plan_path = director._regenerate_plan_with_video_refs(
                            user_input, ref_image_path, director.reference_analysis, res.get("plan_content", {}), video_analysis_result, [best_video]
                        )
                        print(f"✅ 包含真实视频参考的 Timeline 已生成: {enhanced_plan_path}")
                    except Exception as e:
                        print(f"注入视频参考特征时出错: {e}")
        # -----------------------------
        
        if res["status"] == "success":
            print(f"\n✅ 方案生成成功: {res['plan_path']}")
        else:
            print(f"\n❌ 失败: {res.get('error')}")

if __name__ == "__main__":
    main()
