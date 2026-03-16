import os
import json
import datetime
import requests
import base64
import re
from openai import OpenAI
from dotenv import load_dotenv

# 1. 环境加载
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")

# 模型定义
MODEL_DIRECTOR = os.getenv("MODEL_DIRECTOR", "gpt-5.4") 
MODEL_ARTIST = os.getenv("MODEL_ARTIST", "gpt-image-1.5")

if not api_key:
    print("❌ 错误：请先设置 OPENAI_API_KEY")
    exit(1)

client = OpenAI(api_key=api_key, timeout=120.0)

# 2. 工具函数 (保留 Data URL 用于 Chat 分析)
def encode_image_to_data_url(image_path):
    mime_type = "image/png"
    if image_path.lower().endswith(('.jpg', '.jpeg')): mime_type = "image/jpeg"
    with open(image_path, "rb") as f:
        return f"data:{mime_type};base64,{base64.b64encode(f.read()).decode('utf-8')}"

# 3. 画师 Agent (核心修正处)
class AssetGenerator:
    def __init__(self, output_dir="seedance_project/assets"):
        self.output_dir = output_dir
        if not os.path.exists(output_dir): os.makedirs(output_dir)

    def generate_image(self, prompt, style_guide, filename_hint="generated", ref_image_path=None):
        """调用 GPT-Image-1.5 绘图，修正二进制流传递问题"""
        
        # --- 核心优化：注入 Sprite Sheet 或 UI 强制指令 ---
        is_ui = any(k in prompt.lower() for k in ["ui", "hud", "bar", "text", "number", "damage", "icon"])
        is_static_bg = "background" in prompt.lower()
        
        format_instruction = ""
        
        if is_ui:
            format_instruction = """
FORMAT REQUIREMENT (GAME UI):
- Generate a FLAT, 2D Game UI Element.
- Frontal view, NO perspective distortion.
- Isolated on a plain background (ready for removal).
- Style: High-quality game interface art.
"""
            # 如果是 UI 动画（如飘字），也要求序列帧
            if "anim" in prompt.lower() or "sequence" in prompt.lower():
                format_instruction += "- Layout: HORIZONTAL SPRITE SHEET (3 frames showing start->peak->fade)."

        elif not is_static_bg:
            format_instruction = """
FORMAT REQUIREMENT (SPRITE):
- Generate a HORIZONTAL SPRITE SHEET (Grid View).
- Show 3 distinct keyframes of the action: [Preparation] -> [Impact/Action] -> [Follow-through].
- Ensure consistent character details across all frames.
- Isolated on a clean background.
"""
        
        full_prompt = f"Style Reference: {style_guide}\n\nTask: {prompt}\n{format_instruction}".strip()
        print(f"🎨 画师({MODEL_ARTIST}) 正在绘制: {prompt[:30]}...")
        
        try:
            if ref_image_path and os.path.exists(ref_image_path):
                print(f"🖼️ [GPT-Image-1.5 图生图] 正在读取文件流: {os.path.basename(ref_image_path)}")
                
                # 核心修正：使用二进制模式打开文件并传给 'image' 参数
                with open(ref_image_path, "rb") as image_file:
                    response = client.images.edit(
                        model=MODEL_ARTIST,
                        image=image_file,        # 关键修正：传入文件流而非字符串
                        prompt=full_prompt,
                        n=1,
                        size="1024x1024",
                        background="auto",       
                        input_fidelity="high",   
                        quality="medium"         
                    )
            else:
                response = client.images.generate(
                    model=MODEL_ARTIST,
                    prompt=full_prompt,
                    n=1,
                    size="1024x1024"
                )

            # 解析结果
            image_data = None
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
    def __init__(self, assets_dir="seedance_project/assets", references_dir="seedance_project/references"):
        self.assets_dir = assets_dir
        self.references_dir = references_dir
        self.artist = AssetGenerator(assets_dir)
        self.style_dna = "" 

    def _scan_assets(self):
        if not os.path.exists(self.assets_dir): os.makedirs(self.assets_dir)
        return [f for f in os.listdir(self.assets_dir) if f.lower().endswith(('.jpg', '.png', '.mp4'))]

    def _analyze_visual_style(self, image_path):
        """导演视觉分析 (GPT-5.4 仍使用 Data URL 分析)"""
        print(f"👁️  导演正在分析首图风格: {os.path.basename(image_path)}...")
        data_url = encode_image_to_data_url(image_path)
        try:
            response = client.chat.completions.create(
                model=MODEL_DIRECTOR,
                messages=[
                    {"role": "system", "content": "You are an Art Director. Identify game characters and visual effects needed."},
                    {"role": "user", "content": [
                        {"type": "text", "text": "Extract visual style from this screenshot."},
                        {"type": "image_url", "image_url": {"url": data_url}}
                    ]}
                ]
            )
            return response.choices[0].message.content
        except Exception as e:
            return "Wuxia/Fantasy hand-drawn art style."

    def analyze_needs(self, user_instruction, ref_image_path=None):
        if ref_image_path: self.style_dna = self._analyze_visual_style(ref_image_path)
        
        system_prompt = f"""You are a Creative Director. 
        Visual Style: {self.style_dna}
        
        Analyze the user request and decide what SUPPLEMENTARY assets are needed.
        IMPORTANT: Limit your request to a MAXIMUM of 6 key assets.
        
        ## THINKING DYNAMICALLY (SPRITE SHEETS & UI)
        - **Characters**: Ask for "action sequences" (e.g., idle, attack, hit).
        - **VFX**: Ask for "VFX sequences" (e.g., slash trail, explosion).
        - **UI/HUD**: Explicitly ask for **"Game UI elements"**.
          - Examples: "-9999 Critical Hit number", "HP Bar frame", "Victory Text".
          - Specify if it should be floating (animated) or fixed (static).
        
        Output JSON:
        {{
            "thought": "Reasoning...",
            "missing_assets": [
                {{"filename_hint": "enemy_attack_sheet", "description": "A horizontal sprite sheet of the enemy performing a heavy slash attack (3 frames)."}},
                {{"filename_hint": "crit_damage_ui", "description": "Game UI asset: A bright red '-9999' critical damage number. Isolated, bold font."}}
            ]
        }}
        """
        
        response = client.chat.completions.create(
            model=MODEL_DIRECTOR,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_instruction}],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)

    def generate_final_plan(self, user_instruction, new_assets, ref_image_path=None):
        all_assets = self._scan_assets()
        ref_filename = os.path.basename(ref_image_path) if ref_image_path else "None"
        
        system_prompt = f"""
You are the Seedance Creative Director. 
Your goal: Write the FINAL VIDEO PROMPT using a **TIMELINE STRUCTURE**.

## ASSET MANIFEST
1. **First Frame**: @{ref_filename}
2. **New Assets**: {json.dumps(new_assets)}
3. **Library**: {json.dumps(all_assets)}

## PROMPT RULES (TIMELINE & LAYERS)
1. **Start with**: "First Frame: @{ref_filename}..."
2. **Timeline Format**: Use `[00s-05s]` style to describe the sequence of events.
3. **Layering**: Explicitly state where elements appear.
   - **(Background Layer)**: Scene changes.
   - **(Action Layer)**: Character movements using @sprite_sheets.
   - **(VFX Layer)**: Magic/Explosions overlay using @vfx_assets.
   - **(UI Layer)**: Floating numbers, fixed bars using @ui_assets.

## Output JSON
{{
    "thought": "Planning the timeline...",
    "selected_assets": ["list", "of", "filenames"],
    "prompt_en": "First Frame: @{ref_filename}. [00s-02s] (Action Layer) The hero charges up... [02s-04s] (UI Layer) A critical hit number @damage.png pops up...",
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
        output_dir = "seedance_project/output"
        if not os.path.exists(output_dir): os.makedirs(output_dir)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(output_dir, f"{timestamp}_plan.md")
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(f"# Seedance Plan\n\n## English Prompt\n{plan.get('prompt_en')}\n\n## Chinese Prompt\n{plan.get('prompt_zh')}\n\n## Assets\n{plan.get('selected_assets')}")
        return filepath

# 5. 主循环
def main():
    director = SeedanceDirector()
    print(f"🎬 Seedance AI 导演组已就绪 (Director: {MODEL_DIRECTOR} | Artist: {MODEL_ARTIST})")
    while True:
        user_input = input("\n🎥 请输入创意指令 (输入 'q' 退出): ")
        if user_input.lower() == 'q': break
        
        # 路径识别
        ref_image_path = None
        path_match = re.search(r'(/[^\s]+?\.(?:jpg|jpeg|png|webp))', user_input)
        if path_match and os.path.exists(path_match.group(1)):
            ref_image_path = path_match.group(1)
        else:
            for f in os.listdir(director.references_dir):
                if f in user_input:
                    ref_image_path = os.path.join(director.references_dir, f)
                    break
        
        if not ref_image_path:
            print("⚠️ 未识别参考图。")
            continue

        try:
            needs = director.analyze_needs(user_input, ref_image_path)
            new_assets = []
            if needs.get("missing_assets"):
                # Hard limit to 6 assets
                limited_assets = needs["missing_assets"][:6]
                if len(needs["missing_assets"]) > 6:
                    print(f"⚠️ 导演请求了 {len(needs['missing_assets'])} 个素材，已自动限制为前 6 个。")
                
                for item in limited_assets:
                    res = director.artist.generate_image(item['description'], director.style_dna, item['filename_hint'], ref_image_path)
                    if res: new_assets.append(res)
            plan = director.generate_final_plan(user_input, new_assets, ref_image_path)
            director.save_plan(plan, user_input)
            print(f"\n✅ 方案生成成功!")
            print(f"\n🇺🇸 English Prompt:\n{plan.get('prompt_en')}")
            print(f"\n🇨🇳 Chinese Prompt:\n{plan.get('prompt_zh')}")
        except Exception as e:
            print(f"❌ 发生错误: {e}")
            import traceback
            traceback.print_exc()

if __name__ == "__main__":
    main()