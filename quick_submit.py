import os
import glob
import re
from seedance_api import create_seedance_task, poll_task_status, upload_video_to_tmpfiles

def find_latest_md_plan(game_name="xundaodaqian"):
    output_dir = os.path.join("seedance_project", "games", game_name, "output")
    md_files = glob.glob(os.path.join(output_dir, "*.md"))
    if not md_files:
        return None
    # 找最新修改的文件
    return max(md_files, key=os.path.getmtime)

def parse_md_plan(md_path):
    """
    解析 Markdown 文件，提取 prompt_zh, selected_assets 和 reference_video。
    """
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    result = {
        "prompt_zh": "",
        "selected_assets": [],
        "reference_video_name": None
    }

    # 1. 提取 selected assets
    assets_match = re.search(r'## 2\. Selected Assets\n`([^`]+)`', content)
    if assets_match:
        assets_str = assets_match.group(1)
        result["selected_assets"] = [asset.strip() for asset in assets_str.split(',')]

    # 2. 提取 Chinese Prompt
    prompt_match = re.search(r'## 4\. Chinese Prompt\n> (.+)', content, re.DOTALL)
    if prompt_match:
        result["prompt_zh"] = prompt_match.group(1).strip()
        
    # 3. 在 assets 里找出 mp4
    for asset in result["selected_assets"]:
        if asset.endswith('.mp4'):
            result["reference_video_name"] = asset
            break
            
    # 4. 解析视频时长 (从 prompt_zh 中提取类似 [00s-05.5s] 的最大秒数)
    duration = 5 # 默认
    matches = re.findall(r'\[\d+s-([\d\.]+)s\]', result["prompt_zh"])
    if matches:
        max_sec = max(float(m) for m in matches)
        duration = max(4, min(15, int(round(max_sec))))
    result["duration"] = duration
            
    return result

def get_closest_ratio(width, height):
    """根据宽高计算最接近的 API 支持的视频比例"""
    if width == 0 or height == 0:
        return "16:9"
    
    actual_ratio = width / height
    ratios = {
        "16:9": 16/9,
        "4:3": 4/3,
        "1:1": 1/1,
        "3:4": 3/4,
        "9:16": 9/16,
        "21:9": 21/9
    }
    
    closest = min(ratios.keys(), key=lambda k: abs(ratios[k] - actual_ratio))
    return closest

def get_image_size(image_path):
    """尝试获取图片的宽高，无需安装额外库 (通过读取文件头)"""
    try:
        from PIL import Image
        with Image.open(image_path) as img:
            return img.width, img.height
    except ImportError:
        pass
        
    import struct
    try:
        with open(image_path, 'rb') as f:
            head = f.read(24)
            if len(head) != 24:
                return 0, 0
            
            # png
            if head.startswith(b'\x89PNG\r\n\x1a\n'):
                check = struct.unpack('>I', head[4:8])[0]
                if check != 0x0d0a1a0a:
                    return 0, 0
                width, height = struct.unpack('>ii', head[16:24])
                return width, height
            # jpeg
            elif head.startswith(b'\xff\xd8'):
                f.seek(0)
                size = 2
                ftype = 0
                while not 0xc0 <= ftype <= 0xcf or ftype in [0xc4, 0xc8, 0xcc]:
                    f.seek(size, 1)
                    byte = f.read(1)
                    while ord(byte) == 0xff:
                        byte = f.read(1)
                    ftype = ord(byte)
                    size = struct.unpack('>H', f.read(2))[0] - 2
                # We are at a SOFn block
                f.seek(1, 1)  # Skip `precision' byte.
                height, width = struct.unpack('>HH', f.read(4))
                return width, height
    except Exception as e:
        print(f"解析图片尺寸失败: {e}")
        
    return 0, 0

def quick_submit(game_name="xundaodaqian"):
    print("="*50)
    print("=== 快速重传工具：直接从最新报告中提取信息并提交API ===")
    print("="*50)
    print("⚠️ 运行前请确保您的 keys/seedance_key.txt 中填入了有效的 LiteLLM Virtual Key！\n")
    
    # 1. 找文件
    md_path = find_latest_md_plan(game_name)
    if not md_path:
        print(f"❌ 找不到对应游戏 {game_name} 的 markdown 报告。")
        return
        
    print(f"📄 找到最新计划文件: {md_path}")
    plan_data = parse_md_plan(md_path)
    
    if not plan_data["prompt_zh"]:
        print("❌ 未能在文件中提取到中文提示词 (Chinese Prompt)")
        return
        
    print("\n✅ 成功提取提示词:")
    print(plan_data["prompt_zh"][:100] + "... (省略)")
    
    # 2. 定位图片资源
    # 根据游戏目录组装路径
    game_dir = os.path.join("seedance_project", "games", game_name)
    assets_dir = os.path.join(game_dir, "assets")
    refs_dir = os.path.join(game_dir, "references")
    
    image_paths = []
    video_path = None
    
    for asset_name in plan_data["selected_assets"]:
        # 尝试在 assets_dir 和 refs_dir 查找
        potential_paths = [
            os.path.join(assets_dir, asset_name),
            os.path.join(refs_dir, asset_name)
        ]
        
        found_path = None
        for p in potential_paths:
            if os.path.exists(p):
                found_path = p
                break
                
        if not found_path:
            print(f"⚠️ 警告: 找不到引用的资源文件 - {asset_name}")
            continue
            
        if asset_name.endswith('.mp4'):
            video_path = found_path
        elif asset_name.endswith(('.png', '.jpg', '.jpeg')):
            if len(image_paths) < 9:
                image_paths.append(found_path)
            else:
                print(f"⚠️ 警告: 图片数量超过9张限制，舍弃 {asset_name}")

    print(f"✅ 找到 {len(image_paths)} 张参考图片。")
    
    # 3. 处理视频
    video_url = None
    if video_path:
        print(f"\n🎥 找到参考视频: {video_path}")
        print("⬆️ 正在将其上传至临时图床...")
        video_url = upload_video_to_tmpfiles(video_path)
        if not video_url:
            print("❌ 视频上传失败！终止提交。")
            return
    else:
        print("\n⚠️ 报告中未发现参考视频 (.mp4)。")
        
    # 4. 计算首图比例
    ratio = "16:9"
    if image_paths:
        first_frame = image_paths[0]
        w, h = get_image_size(first_frame)
        if w > 0 and h > 0:
            ratio = get_closest_ratio(w, h)
            print(f"📐 首图尺寸: {w}x{h}，计算得出最接近的长宽比: {ratio}")
        else:
            print("⚠️ 无法获取首图尺寸，默认使用 16:9")
            
    print(f"⏱️ 剧本解析得出视频总时长: {plan_data['duration']} 秒")
        
    # 5. 提交
    print("\n🚀 开始提交 Seedance 任务...")
    task_id = create_seedance_task(
        prompt_text=plan_data["prompt_zh"],
        image_paths=image_paths,
        reference_video_url=video_url,
        duration=plan_data["duration"],
        ratio=ratio
    )
    
    if task_id:
        poll_task_status(task_id)

if __name__ == "__main__":
    quick_submit()