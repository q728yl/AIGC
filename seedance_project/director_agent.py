import os
import json
import datetime
import requests
import base64
from openai import OpenAI
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 获取配置
api_key = os.getenv("OPENAI_API_KEY")

# --- 模型配置 ---
MODEL_DIRECTOR = os.getenv("MODEL_DIRECTOR", "gpt-5.4") 
MODEL_ARTIST = os.getenv("MODEL_ARTIST", "gpt-image-1.5")

if not api_key:
    print("错误：请先设置 OPENAI_API_KEY")
    exit(1)

client = OpenAI(api_key=api_key)

def encode_image(image_path):
    """将图片编码为 Base64"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

class AssetGenerator:
    """画师 Agent: 负责根据描述生成图片"""
    def __init__(self, output_dir="seedance_project/assets"):
        self.output_dir = output_dir
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

    def generate_image(self, prompt, style_guide, filename_hint="generated"):
        """调用 DALL-E 生成图片，融合风格指南"""
        
        # 将风格指南融入 Prompt
        full_prompt = f"""
{style_guide}

Specific Subject: {prompt}
""".strip()
        
        print(f"🎨 画师正在绘制: {prompt[:20]}... (已融合参考图风格)")
        
        try:
            # 尝试请求 URL 格式
            try:
                target_size = "1024x1536" 
                print(f"📐 画师设定画布大小: {target_size} ")
                
                response = client.images.generate(
                    model=MODEL_ARTIST,
                    prompt=full_prompt,
                    size=target_size,
                    quality="high",
                    n=1,
                )
            except Exception as e:
                if "quality" in str(e).lower():
                     print("⚠️ 模型不支持 quality='high'，尝试使用默认设置...")
                     response = client.images.generate(
                        model=MODEL_ARTIST,
                        prompt=full_prompt,
                        size=target_size,
                        n=1,
                    )
                else:
                    raise e

            # 处理响应
            image_url = response.data[0].url
            b64_json = getattr(response.data[0], 'b64_json', None)
            
            # 准备文件路径
            timestamp = datetime.datetime.now().strftime("%H%M%S")
            filename = f"{filename_hint}_{timestamp}.png"
            filepath = os.path.join(self.output_dir, filename)
            
            if image_url:
                img_data = requests.get(image_url).content
                with open(filepath, 'wb') as f:
                    f.write(img_data)
            elif b64_json:
                img_data = base64.b64decode(b64_json)
                with open(filepath, 'wb') as f:
                    f.write(img_data)
            else:
                print("⚠️ 未获取到 URL，尝试请求 b64_json 格式...")
                response = client.images.generate(
                    model=MODEL_ARTIST,
                    prompt=full_prompt,
                    size=target_size,
                    response_format="b64_json",
                    n=1,
                )
                if hasattr(response.data[0], 'b64_json') and response.data[0].b64_json:
                    img_data = base64.b64decode(response.data[0].b64_json)
                    with open(filepath, 'wb') as f:
                        f.write(img_data)
                else:
                    print(f"❌ 绘图失败: 无法获取图片数据")
                    return None
                
            print(f"✅ 图片已交付: {filename}")
            return filename
        except Exception as e:
            print(f"❌ 绘图失败: {e}")
            return None

class SeedanceDirector:
    def __init__(self, 
                 assets_dir="seedance_project/assets", 
                 references_dir="seedance_project/references",
                 guide_path="seedance_project/docs/seedance_guide.txt", 
                 game_context_path="seedance_project/docs/game_context.txt"):
        self.assets_dir = assets_dir
        self.references_dir = references_dir
        self.guide_content = self._load_file(guide_path)
        self.game_context_content = self._load_file(game_context_path)
        self.assets = self._scan_assets()
        self.artist = AssetGenerator(assets_dir)
        self.style_dna = "" # 存储分析出的风格特征

    def _load_file(self, path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            return f"文件 {path} 未找到。"

    def _scan_assets(self):
        assets = []
        if not os.path.exists(self.assets_dir):
            os.makedirs(self.assets_dir)
        for file in os.listdir(self.assets_dir):
            if file.lower().endswith(('.jpg', '.png', '.mp4', '.mov')):
                assets.append(file)
        return assets

    def _analyze_visual_style(self):
        """核心逻辑：导演查看参考图，提取风格 DNA"""
        if not os.path.exists(self.references_dir):
            os.makedirs(self.references_dir)
            return "No reference images provided. Use general ink wash painting style."

        ref_images = [f for f in os.listdir(self.references_dir) if f.lower().endswith(('.jpg', '.png', '.jpeg'))]
        if not ref_images:
            return "No reference images found. Use general ink wash painting style."

        print(f"👁️  导演正在观察 {len(ref_images)} 张参考图，提取《寻道大千》美术风格...")
        
        # 取第一张图进行分析（为了节省 token，也可以多张）
        img_path = os.path.join(self.references_dir, ref_images[0])
        base64_image = encode_image(img_path)

        system_prompt = """
You are an expert Art Director acting as the "Eyes" for a blind but talented painter (gpt-image-1.5).
Your job is to analyze the provided game screenshot and translate its visual essence into a precise prompt that the painter can use to replicate the style perfectly.

Focus on:
1. **Art Style**: Is it Ink wash? Cel-shaded? Vector? Describe the brush strokes.
2. **Line Work**: Thick/thin? Black/colored? Rough/smooth?
3. **Color Palette**: Describe the dominant colors, background tones (e.g., parchment, old paper), and accent colors.
4. **Composition**: Is it flat 2D? Side-scrolling? Isometric?
5. **Texture**: Paper grain? Watercolor bleed? Digital noise?

Output a single, dense paragraph of descriptive keywords.
Start with: "Art Style: ..."
"""
        try:
            response = client.chat.completions.create(
                model=MODEL_DIRECTOR,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": [
                        {"type": "text", "text": "Analyze this game screenshot style."},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                    ]}
                ],
                max_completion_tokens=1024
            )
            style_desc = response.choices[0].message.content
            print(f"✨ 风格提取完成: {style_desc[:50]}...")
            return style_desc
        except Exception as e:
            print(f"⚠️ 视觉分析失败: {e}")
            return "Ink wash painting style, traditional Chinese fantasy game art."

    def _call_llm(self, system_prompt, user_prompt):
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]
        try:
            response = client.chat.completions.create(
                model=MODEL_DIRECTOR,
                messages=messages,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            # 简单的错误处理回退
            print(f"⚠️ LLM 调用错误 ({MODEL_DIRECTOR}): {e}")
            # 尝试 Completion 接口回退逻辑 (省略详细实现以保持简洁，沿用之前的逻辑即可)
            return {}

    def analyze_needs(self, user_instruction):
        # 1. 先分析视觉风格 (如果还没分析过)
        if not self.style_dna:
            self.style_dna = self._analyze_visual_style()

        system_prompt = f"""
你是一位专业的 Seedance 创意导演。
你的任务是：分析用户指令，决定我们需要哪些素材。

## 核心美术风格 (必须严格遵守)
{self.style_dna}

## 你的知识库
1. Seedance 指南: {self.guide_content[:200]}...
2. 寻道大千设定: {self.game_context_content}

## 现有素材
{json.dumps(self.assets, ensure_ascii=False)}

## 输出要求 (JSON)
1. "thought": (string) 思考过程。需明确如何将用户需求与核心美术风格结合。
2. "missing_assets": (list) 需要生成的素材列表。
   格式: [{{"filename_hint": "hero_pig", "description": "Based on the Art Style DNA, describe the asset..."}}]
"""
        return self._call_llm(system_prompt, f"用户指令：{user_instruction}")

    def generate_final_plan(self, user_instruction, newly_generated_assets=[]):
        all_assets = self._scan_assets()
        
        system_prompt = f"""
You are an expert Seedance Creative Director.
Please write the final Seedance prompt.

## Core Art Style (Must be strictly followed)
{self.style_dna}

## Your Full Asset Library
{json.dumps(all_assets, ensure_ascii=False)}

## Output Requirements (JSON)
1. "thought": Director's thinking.
2. "selected_assets": A list of ALL asset filenames selected for this scene (e.g., ["snake_demon.png", "forest_bg.png"]).
3. "prompt_en": Seedance specialized English prompt. 
   IMPORTANT: You MUST include the exact filenames of ALL selected assets in the prompt using the @ symbol (e.g., "@snake_demon.png", "@forest_bg.png") to ensure the video generation model uses the specific character and background images.
4. "prompt_zh": Chinese translation.
5. "parameters": Parameter settings.
"""
        return self._call_llm(system_prompt, f"用户指令：{user_instruction}")

    def save_plan(self, plan, user_instruction):
        output_dir = "seedance_project/output"
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_instruction = "".join([c for c in user_instruction if c.isalnum()])[:10]
        filename = f"{timestamp}_{safe_instruction}.md"
        filepath = os.path.join(output_dir, filename)
        
        content = f"""# Seedance 生成方案: {user_instruction}
> 生成时间: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 1. 导演思考 (Visual Thinking)
{plan.get('thought')}

## 2. 核心美术风格 (Style DNA)
> {self.style_dna}

## 3. 选定素材
`{', '.join(plan.get('selected_assets', ['无']))}`

## 4. Prompt (英文 - Seedance)
```text
{plan.get('prompt_en')}
```

## 5. Prompt (中文 - 参考)
> {plan.get('prompt_zh')}
"""
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        return filepath

def main():
    director = SeedanceDirector()
    print(f"🎬 Seedance AI 导演组已就绪 (Director: {MODEL_DIRECTOR} | Artist: {MODEL_ARTIST})")
    print(f"📂 请将《寻道大千》游戏截图放入: seedance_project/references/ 文件夹中")
    
    while True:
        user_input = input("\n🎥 请输入你的创意指令 (输入 'q' 退出): ")
        if user_input.lower() == 'q':
            break
            
        print(f"\n🤔 导演({MODEL_DIRECTOR}) 正在进行视觉分析与需求拆解...")
        try:
            needs = director.analyze_needs(user_input)
            
            new_assets = []
            if needs.get("missing_assets"):
                print(f"\n🎨 导演认为缺少素材，正在呼叫画师({MODEL_ARTIST})...")
                for item in needs["missing_assets"]:
                    # 将提取的风格 DNA 传给画师
                    filename = director.artist.generate_image(
                        item['description'], 
                        director.style_dna, # 传入风格指南
                        item['filename_hint']
                    )
                    if filename:
                        new_assets.append(filename)
            else:
                print("✅ 现有素材充足，无需绘图。")
                
            print("\n📝 导演正在撰写最终剧本...")
            plan = director.generate_final_plan(user_input, new_assets)
            director.save_plan(plan, user_input)
            
            print(f"\n✅ 方案已生成! 风格参考: {director.style_dna[:30]}...")
            print(f"🇺🇸 Prompt: \n{plan.get('prompt_en')}")
        
        except Exception as e:
            print(f"\n❌ 发生错误: {e}")

if __name__ == "__main__":
    main()
