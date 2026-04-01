import os
import cv2
import base64
import json
import math
import tempfile
import shutil
import numpy as np
from pathlib import Path
from openai import OpenAI
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 引入 scenedetect 用于长视频的自动分段
from scenedetect import detect, ContentDetector

# 加载 .env 文件
load_dotenv()

# 初始化 OpenAI 客户端
api_key = os.getenv("OPENAI_API_KEY")
base_url = os.getenv("OPENAI_BASE_URL")  # 增加从环境变量读取 base_url

if not api_key:
    raise ValueError("请在 .env 文件中设置 OPENAI_API_KEY")

# 支持中转代理配置
if base_url:
    client = OpenAI(api_key=api_key, base_url=base_url)
else:
    client = OpenAI(api_key=api_key)

# ================== 结构化输出定义 ==================
class KeyframePhase(BaseModel):
    frame_index: int = Field(description="该阶段对应的最佳视频帧的索引编号。必须是提供给你的帧编号之一。")
    reasoning: str = Field(description="选择该帧的理由，为什么它最能代表这个阶段。")
    description: str = Field(description="对该阶段画面的详细描述，包含特效的形状、颜色结构、粒子密度等（用于后续的Prompt生成）。")

class SkillAnalysisResult(BaseModel):
    contains_clear_skill: bool = Field(description="核心判断：这组提供的帧中，是否【完整且清晰地】包含同一个角色发出的【唯一一次连贯的技能释放过程（起手->命中）】？如果画面太乱、多次攻击交织、阵营混乱或缺乏某个阶段（如没有命中），必须设为 false，拒绝拼凑！")
    wind_up: KeyframePhase = Field(description="起手蓄力阶段（Wind-up / Anticipation）")
    release: KeyframePhase = Field(description="技能释放阶段（Release / Cast / Action）")
    impact: KeyframePhase = Field(description="命中/爆发阶段（Impact / Climax）")
    dissipation: KeyframePhase = Field(description="残留与收尾阶段（Dissipation / Follow-through）")
    global_style: str = Field(description="整体技能特效风格总结（如：卡通渲染风格、高对比度的霓虹色彩、水墨风等）。")
    ready_to_use_prompt: str = Field(description="生成一段可以直接输入给 Midjourney/即梦 等 AI 绘图工具的英文 Prompt（需包含黑底纯色背景、发光特效、具体的色彩和形状描述）。")

# ================== 核心逻辑 ==================

def auto_split_video(video_path: str, output_dir: str) -> list[str]:
    """
    使用 PySceneDetect 自动将长视频按场景（镜头切换/明显动作突变）切分成短视频。
    如果视频本身很短（如小于 5 秒），则直接返回原视频路径。
    """
    if not os.path.exists(video_path):
        print(f"文件不存在: {video_path}")
        return [video_path]
        
    try:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"OpenCV 无法打开视频文件: {video_path}")
            return [video_path]
            
        fps = cap.get(cv2.CAP_PROP_FPS)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        cap.release()
    except Exception as e:
        print(f"读取视频元数据失败: {e}")
        return [video_path]
    
    # 如果视频本来就很短，就不分段了
    if duration <= 6.0:
        print(f"视频时长 {duration:.1f}s <= 6s，跳过场景切分。")
        return [video_path]
        
    print(f"视频时长 {duration:.1f}s，开始自动场景检测与切分...")
    
    # 创建临时文件夹存放切出来的片段
    file_prefix = Path(video_path).stem
    split_dir = os.path.join(output_dir, f"{file_prefix}_splits")
    os.makedirs(split_dir, exist_ok=True)
    
    # 查找场景切换：使用 ContentDetector，针对特别乱的满屏特效游戏，需要将阈值继续调小，让切片更短，保证每个切片里只有一两秒的动作。
    scene_list = detect(video_path, ContentDetector(threshold=20.0, min_scene_len=15))
    
    if not scene_list:
        print("未检测到明显场景切换，将原视频作为唯一片段。")
        return [video_path]
        
    print(f"检测到 {len(scene_list)} 个场景，正在切割视频...")
    
    # 改为使用 moviepy 来切割视频，这比 OpenCV 更可靠且处理音视频更好
    valid_splits = []
    try:
        from moviepy.video.io.VideoFileClip import VideoFileClip
        
        video = VideoFileClip(video_path)
        
        for i, (start_time, end_time) in enumerate(scene_list):
            start_sec = start_time.get_seconds()
            end_sec = end_time.get_seconds()
            
            # 如果片段太短（小于 0.5 秒），跳过
            if (end_sec - start_sec) < 0.5:
                continue
                
            out_path = os.path.join(split_dir, f"{file_prefix}_scene{i:03d}.mp4")
            out_path = os.path.abspath(out_path)
            
            # 使用 imageio_ffmpeg 附带的 ffmpeg 提取片段，极速且避免重编码
            import imageio_ffmpeg
            import subprocess
            ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            
            subprocess.run([
                ffmpeg_exe, "-y", 
                "-i", video_path, 
                "-ss", str(start_sec), 
                "-to", str(end_sec), 
                "-c", "copy", 
                out_path
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 检查是否真的写入成功了
            if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
                valid_splits.append(out_path)
            else:
                print(f"写入视频失败或文件为空: {out_path}")
                # 尝试删除坏文件
                try:
                    if os.path.exists(out_path):
                        os.remove(out_path)
                except:
                    pass
            
    except Exception as e:
        print(f"MoviePy 切分视频失败: {e}")
        return [video_path]
        
    print(f"成功切分出 {len(valid_splits)} 个有效短视频片段。")
    return valid_splits if valid_splits else [video_path]

def cleanup_splits(split_dir: str):
    """
    清理切分出的临时视频文件夹。
    """
    try:
        if os.path.exists(split_dir):
            shutil.rmtree(split_dir)
            print(f"已清理临时文件夹: {split_dir}")
    except Exception as e:
        print(f"清理临时文件夹失败: {e}")


def extract_frames_from_video(video_path: str, max_frames: int = 15):
    """
    从视频中均匀提取若干帧。
    返回一个包含元组的列表：(帧索引, 帧画面(RGB图像))
    """
    try:
        # 在 Mac 上强制使用默认后端，避免某些带扩展名的文件被错误拦截
        cap = cv2.VideoCapture(video_path, cv2.CAP_ANY)
        if not cap.isOpened():
            # 尝试使用 AVFoundation
            cap = cv2.VideoCapture(video_path, cv2.CAP_AVFOUNDATION)
            if not cap.isOpened():
                print(f"提取帧时无法打开视频: {video_path}")
                return [], 0
            
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        duration = total_frames / fps if fps > 0 else 0
    except Exception as e:
        print(f"提取帧时读取视频失败: {e}")
        return [], 0
    print(f"视频总帧数: {total_frames}, FPS: {fps:.2f}, 时长: {duration:.2f}秒")

    # 计算提取步长
    step = max(1, total_frames // max_frames)
    
    frames_data = []
    
    current_frame = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        if current_frame % step == 0 and len(frames_data) < max_frames:
            # OpenCV 默认是 BGR，转为 RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frames_data.append((current_frame, frame_rgb))
            
        current_frame += 1

    cap.release()
    return frames_data, fps

def encode_image_to_base64(image_rgb, max_size=512):
    """
    将 numpy RGB 图像缩小并编码为 base64 字符串（用于传递给 MLLM 节省 token）。
    """
    # 等比例缩放
    h, w = image_rgb.shape[:2]
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        new_w, new_h = int(w * scale), int(h * scale)
        # 用 Pillow 缩放
        from PIL import Image
        pil_img = Image.fromarray(image_rgb)
        image_resized = np.array(pil_img.resize((new_w, new_h), Image.Resampling.LANCZOS))
    else:
        image_resized = image_rgb

    # 转回 BGR 用于 imencode 或直接用 PIL 存 base64
    from PIL import Image
    import io
    pil_img = Image.fromarray(image_resized)
    buffered = io.BytesIO()
    pil_img.save(buffered, format="JPEG", quality=80)
    return base64.b64encode(buffered.getvalue()).decode('utf-8')

def analyze_video_with_mllm(frames_data) -> SkillAnalysisResult:
    """
    将提取的帧发送给 GPT-4o 进行视觉理解和分阶段提取。
    """
    content = [
        {
            "type": "text",
            "text": "以下是从一个游戏战斗视频片段中按时间顺序提取的 15 张关键帧。\n"
                    "【核心任务与雷区】：\n"
                    "1. 这个片段中极其可能包含了多次毫无关联的攻击、多个人物的乱战、甚至敌我双方交替出手的画面。\n"
                    "2. 你的唯一任务是：在这些帧里，【严格锁定唯一的一个施法主体】和【唯一的一套技能视觉特征（比如特定颜色的光效）】，然后把这唯一一次攻击拆解为：起手、释放、命中、收尾 4 个阶段。\n"
                    "3. 【致命错误警告】：绝对不能把角色A的起手（如帧3）和角色B的命中（如帧10）拼在一起！绝对不能把第一发子弹的释放和第二发子弹的命中拼在一起！所有的 4 个阶段必须在时间线和因果关系上完美连贯，属于同一个技能的同一波特效！\n"
                    "4. 【拒绝回答机制】：如果在提供的这十几张图里，你无法凑齐同一次攻击的完整 4 个阶段（比如只有起手没有命中，或者画面太乱根本分不清是谁打的），你必须将 `contains_clear_skill` 字段设为 false！千万不要为了交差而强行把毫无关联的帧拼凑起来！\n\n"
                    "如果确认包含完整的单一技能释放，请针对每个阶段挑选最准确的帧编号，并提供用于后续 AI 图生图的特效视觉描述（颜色、形状、密度等）。"
        }
    ]

    for frame_index, frame_rgb in frames_data:
        base64_img = encode_image_to_base64(frame_rgb)
        # 将帧编号加入文本
        content.append({
            "type": "text",
            "text": f"--- 帧编号: {frame_index} ---"
        })
        content.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{base64_img}",
                "detail": "low" # 使用 low detail 节省 token
            }
        })

    try:
        response = client.beta.chat.completions.parse(
            model="gpt-4o",  # 视觉任务首选 gpt-4o
            messages=[
                {"role": "system", "content": "You are a Technical Artist and VFX analyst. Your task is to break down game skill visual effects. Please respond in English."},
                {"role": "user", "content": content}
            ],
            response_format=SkillAnalysisResult,
            max_tokens=1500,
            temperature=0.2
        )
        return response.choices[0].message.parsed
    except Exception as e:
        print(f"调用 API 失败: {e}")
        return None

def create_reference_board(frames_data, analysis_result: SkillAnalysisResult, output_dir: str, prefix: str):
    """
    生成带有四个阶段的高清参考板，并保存详细描述到文本文件。
    如果 PIL 可用，则拼成一张大图；否则分别保存 4 张小图。
    """
    os.makedirs(output_dir, exist_ok=True)
    
    # 建立 frame_index 到完整图像的映射
    frame_map = {idx: img for idx, img in frames_data}
    
    phases = [
        ("1_Wind_up", "Wind-up", analysis_result.wind_up),
        ("2_Release", "Release", analysis_result.release),
        ("3_Impact", "Impact", analysis_result.impact),
        ("4_Dissipation", "Dissipation", analysis_result.dissipation)
    ]
    
    # 提取选中的帧并分别保存
    selected_images = []
    
    for phase_key, phase_name, phase_data in phases:
        f_idx = phase_data.frame_index
        # 容错：如果大模型返回了不存在的索引，找最接近的
        if f_idx not in frame_map:
            f_idx = min(frame_map.keys(), key=lambda k: abs(k - f_idx))
            print(f"警告: 模型选择了不存在的帧 {phase_data.frame_index}，回退到最接近的帧 {f_idx}")
            
        img_rgb = frame_map[f_idx]
        
        # 收集图片用于最后拼图，不再保存单帧的 jpg 文件
        selected_images.append((phase_name, img_rgb, phase_data.description))
        
    # 保存 Prompt 信息
    prompt_path = os.path.join(output_dir, f"{prefix}_prompts.txt")
    with open(prompt_path, "w", encoding="utf-8") as f:
        f.write(f"【直接可用 AI 绘图 Prompt (英文)】\n{analysis_result.ready_to_use_prompt}\n\n")
        f.write("="*40 + "\n\n")
        f.write(f"【整体风格】: {analysis_result.global_style}\n\n")
        for phase_key, phase_name, phase_data in phases:
            f.write(f"【{phase_name}】 (帧 {phase_data.frame_index})\n")
            f.write(f"理由: {phase_data.reasoning}\n")
            f.write(f"提示词/特征描述: {phase_data.description}\n\n")
    print(f"已保存详细提示词描述: {prompt_path}")

    # 尝试根据原图比例自适应拼接为一张参考板（横向排布）
    try:
        from PIL import Image, ImageDraw, ImageFont
        
        # 使用第一张图的比例来决定排版
        first_img_rgb = selected_images[0][1]
        orig_h, orig_w = first_img_rgb.shape[:2]
        
        # 竖屏游戏（宽 < 高）：横向排列 4 张
        # 横屏游戏（宽 > 高）：竖向排列 4 张
        is_portrait = orig_w < orig_h
        
        # 限制最大尺寸以防图片过大
        max_dim = 800
        scale = max_dim / max(orig_w, orig_h)
        target_w, target_h = int(orig_w * scale), int(orig_h * scale)
        
        padding = 60
        header_height = 80
        
        if is_portrait:
            # 1行4列
            board_w = (target_w * 4) + (padding * 5)
            board_h = target_h + header_height + (padding * 2)
            positions = [
                (padding + i * (target_w + padding), header_height + padding)
                for i in range(4)
            ]
        else:
            # 4行1列
            board_w = target_w + (padding * 2)
            board_h = (target_h * 4) + header_height + (padding * 5)
            positions = [
                (padding, header_height + padding + i * (target_h + padding))
                for i in range(4)
            ]
            
        board = Image.new('RGB', (board_w, board_h), color=(30, 30, 30))
        draw = ImageDraw.Draw(board)
        
        # 写个大标题
        draw.text((padding, padding//2), f"Skill FX Breakdown - {prefix}", fill=(255, 255, 255))

        for i, (name, img_rgb, desc) in enumerate(selected_images):
            pil_img = Image.fromarray(img_rgb)
            pil_img = pil_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
            
            x, y = positions[i]
            board.paste(pil_img, (x, y))
            
            # 画阶段名称
            draw.text((x, y - 25), name, fill=(200, 200, 255))
            
        board_path = os.path.join(output_dir, f"{prefix}_reference_board.jpg")
        board.save(board_path)
        print(f"已生成四宫格参考板: {board_path}")
        
    except ImportError:
        print("未安装 Pillow，跳过生成拼图参考板。可以通过 pip install Pillow 安装。")


def process_single_video(video_path: str, output_dir: str, max_frames: int):
    file_prefix = Path(video_path).stem
    print(f"\n==================================================")
    print(f"开始处理视频: {video_path}")
    print(f"==================================================")
    
    # 自动切分长视频
    split_paths = auto_split_video(video_path, output_dir)
    
    def process_split(split_idx_and_path):
        split_idx, current_video_path = split_idx_and_path
        sub_prefix = Path(current_video_path).stem
        print(f"\n---> [{sub_prefix}] 正在分析片段 {split_idx + 1}/{len(split_paths)}")
        
        frames_data, fps = extract_frames_from_video(current_video_path, max_frames=max_frames)
        if not frames_data:
            print(f"[{sub_prefix}] 未提取到任何视频帧，跳过该片段。")
            return
            
        print(f"[{sub_prefix}] 共提取了 {len(frames_data)} 帧，准备发送给大模型进行分析。")
        
        analysis_result = analyze_video_with_mllm(frames_data)
        
        if not analysis_result:
            print(f"[{sub_prefix}] MLLM 分析失败或无返回结果，跳过。")
            return
            
        if not getattr(analysis_result, 'contains_clear_skill', True):
            print(f"[{sub_prefix}] MLLM 判断该片段不包含完整清晰的技能释放 (可能只是跑图/UI)，丢弃该片段。")
            return
            
        print(f"[{sub_prefix}] 分析成功！正在保存参考板和 Prompt...")
        # 为了防止重名，传入 sub_prefix
        create_reference_board(frames_data, analysis_result, output_dir, sub_prefix)
        print(f"[{sub_prefix}] 处理完成！")

    # 引入多线程并发处理（建议并发数控制在 3-5 之间，避免达到 OpenAI 并发频率限制）
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(process_split, enumerate(split_paths)))
        
    # 处理完后，如果这个视频有被切分，清理临时切分出来的短视频
    if len(split_paths) > 1 or (len(split_paths) == 1 and split_paths[0] != video_path):
        split_dir = os.path.dirname(split_paths[0])
        cleanup_splits(split_dir)
    
    print(f"\n【完毕】该长视频切片全部处理完成: {video_path}")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="使用 MLLM 提取视频中的技能特效关键帧并生成参考板")
    parser.add_argument("input_path", help="输入的游戏技能视频路径，或包含视频的文件夹路径")
    parser.add_argument("--output_dir", default="./output_frames", help="输出文件夹路径")
    parser.add_argument("--max_frames", type=int, default=15, help="发送给 MLLM 的最大采样帧数 (避免 token 爆炸)")
    
    args = parser.parse_args()
    
    input_path = args.input_path
    if not os.path.exists(input_path):
        print(f"错误: 找不到路径 {input_path}")
        return
        
    if os.path.isdir(input_path):
        # 遍历文件夹下的视频文件
        video_extensions = {".mp4", ".avi", ".mov", ".mkv", ".webm"}
        video_files = [
            os.path.join(input_path, f) for f in os.listdir(input_path)
            if os.path.isfile(os.path.join(input_path, f)) and Path(f).suffix.lower() in video_extensions
        ]
        
        if not video_files:
            print(f"文件夹 {input_path} 下没有找到支持的视频文件。")
            return
            
        print(f"找到 {len(video_files)} 个视频文件，开始批量处理...")
        for vp in video_files:
            process_single_video(vp, args.output_dir, args.max_frames)
            
        print("\n所有视频处理完成！")
    else:
        # 单个文件处理
        process_single_video(input_path, args.output_dir, args.max_frames)

if __name__ == "__main__":
    main()
