"""
Seedance 直出对比脚本 —— 单图 + 单 Prompt 直接生成视频，不使用工作流编排。

用法:
  python direct_seedance.py <图片路径> --prompt "你的提示词"

示例:
  python direct_seedance.py seedance_project/games/xundaodaqian/references/0045.jpg --prompt "角色释放大招，能量光束席卷战场"
  python direct_seedance.py hero.png -p "战斗场景，角色挥剑攻击敌人" -d 10
"""

import argparse
import os
import requests

from seedance_api import create_seedance_task, poll_task_status
from quick_submit import get_image_size, get_closest_ratio


def direct_generate(image_path, prompt, duration=5, ratio=None, model="doubao-seedance-2-0-fast-260128"):
    if not os.path.exists(image_path):
        print(f"❌ 图片不存在: {image_path}")
        return None

    if not ratio:
        w, h = get_image_size(image_path)
        if w > 0 and h > 0:
            ratio = get_closest_ratio(w, h)
            print(f"📐 首图尺寸 {w}x{h} → 自动选择比例: {ratio}")
        else:
            ratio = "16:9"
            print(f"📐 无法读取首图尺寸，默认比例: {ratio}")

    image_filename = os.path.basename(image_path)
    final_prompt = f"首帧锁定: @{image_filename}。{prompt}"

    print("\n" + "=" * 60)
    print("  Seedance 直出模式 (无工作流编排，纯对比基线)")
    print("=" * 60)
    print(f"  首帧图片 : {image_path}")
    print(f"  用户 Prompt : {prompt}")
    print(f"  实际提交 Prompt : {final_prompt}")
    print(f"  时长     : {duration}s")
    print(f"  比例     : {ratio}")
    print(f"  模型     : {model}")
    print("=" * 60 + "\n")

    task_id = create_seedance_task(
        prompt_text=final_prompt,
        image_paths=[image_path],
        reference_video_url=None,
        duration=duration,
        ratio=ratio,
        model=model,
    )

    if not task_id:
        print("❌ 任务提交失败。")
        return None

    print(f"\n✅ 任务已提交，Task ID: {task_id}")
    print("⏳ 开始轮询结果...\n")

    result = poll_task_status(task_id)

    if result and result.get("status") == "succeeded":
        video_url = result.get("content", {}).get("video_url")
        if video_url:
            out_dir = "direct_output"
            os.makedirs(out_dir, exist_ok=True)
            filename = f"direct_{task_id}.mp4"
            local_path = os.path.join(out_dir, filename)
            print(f"⬇️ 正在下载视频到 {local_path} ...")
            vid_resp = requests.get(video_url)
            with open(local_path, "wb") as f:
                f.write(vid_resp.content)
            print(f"🎉 视频已保存: {local_path}")
            return local_path

    return None


def main():
    parser = argparse.ArgumentParser(
        description="Seedance 直出对比脚本 —— 单图+单Prompt 直接生成视频",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("image", help="单张首帧参考图片路径")
    parser.add_argument("--prompt", "-p", type=str, required=True, help="视频生成提示词")
    parser.add_argument("--duration", "-d", type=int, default=5, help="视频时长，秒 (4-15，默认5)")
    parser.add_argument("--ratio", "-r", type=str, default=None, help="视频比例 (如 16:9, 9:16, 1:1，不填则从首图自动推断)")
    parser.add_argument("--model", "-m", type=str, default="doubao-seedance-2-0-fast-260128", help="模型名称")

    args = parser.parse_args()
    duration = max(4, min(15, args.duration))

    direct_generate(
        image_path=args.image,
        prompt=args.prompt,
        duration=duration,
        ratio=args.ratio,
        model=args.model,
    )


if __name__ == "__main__":
    main()
