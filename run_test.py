import asyncio
from director_agent import SeedanceDirector, VideoReferenceScraper

def test_path_a_image_only():
    """纯图片素材生成与编排 (Path A)"""
    print("\n" + "="*50)
    print("=== 开始测试 Path A: 纯图片素材生成 ===")
    print("="*50)
    director = SeedanceDirector("xundaodaqian")
    user_input = "生成一段大招战斗视频，我需要参考网上的实机演示来做动作设计"
    ref_image = "seedance_project/games/xundaodaqian/references/0045.jpg"
    
    res = director.run_pipeline(user_input, ref_image, pipeline_mode="image_only")
    print(f"Path A 结果: {res['plan_path']}")

def test_path_b_video_reference():
    """基于参考视频的快速编排 (Path B)，跳过慢速的单图素材生成"""
    print("\n" + "="*50)
    print("=== 开始测试 Path B: 仅基于外部参考视频调试 ===")
    print("="*50)
    director = SeedanceDirector("xundaodaqian")
    scraper = VideoReferenceScraper(director.references_dir)
    
    # 模拟输入一张静态战斗图片
    user_input = "生成一段大招战斗视频，我需要参考网上的实机演示来做动作设计"
    ref_image = "seedance_project/games/xundaodaqian/references/0045.jpg"
    
    print("1. 开始基础感知与需求分析 (已关闭生图)...")
    # 传入 pipeline_mode="video_only" 来跳过生图步骤
    res = director.run_pipeline(user_input, ref_image, pipeline_mode="video_only")
    
    print("\n" + "-"*30)
    print(f"基础流程完成: {res['status']}")
    
    if "reference_video_keywords" in res and res["reference_video_keywords"]:
        keywords = res["reference_video_keywords"]
        print(f"提取到的视频关键词: {keywords}")
        
        downloaded_paths = None
        target_kw = ""
        for kw in keywords:
            print(f"\n2. 🎯 尝试使用大模型生成的关键词进行爬取: {kw}")
            paths = scraper.simulate_search_and_download(kw, director.game_name)
            if paths:
                downloaded_paths = paths
                target_kw = kw
                print(f"✅ 成功通过关键词 '{kw}' 获取到视频。")
                break
            else:
                print(f"⚠️ 关键词 '{kw}' 未能获取到视频，继续尝试下一个...")
                
        if downloaded_paths:
            print(f"✅ 视频下载成功: {downloaded_paths}")
            
            print("\n3. 🎬 正在进行多模态视频理解抽帧并选择最佳片段...")
            analysis_result = director._select_and_analyze_best_video(downloaded_paths, user_input)
            best_video = analysis_result.get("best_video_path")
            analysis = analysis_result.get("analysis")
            print(f"视频特征总结已提取！最佳视频: {best_video}")
            
            print("\n4. 📝 正在生成最终带视频引用的计划...")
            enhanced_plan_path = director._regenerate_plan_with_video_refs(
                user_input, ref_image, director.reference_analysis, res.get("plan_content", {}), analysis, [best_video]
            )
            print(f"🎉 包含真实视频参考的 Timeline 已生成:\n{enhanced_plan_path}")
        else:
            print("❌ 视频下载失败")

import argparse
import sys
import glob

def test_path_c_full_hybrid(user_input=None, ref_image=None, ref_video=None):
    """图生结合视频参考的全自动化流程 (Plan C)"""
    print("\n" + "="*50)
    print("=== 开始测试 Path C: 全混合工作流 ===")
    print("="*50)
    director = SeedanceDirector("xundaodaqian")
    
    # 默认值回退
    if not user_input:
        user_input = "生成一段大招战斗视频，我需要参考网上的实机演示来做动作设计"
    if not ref_image:
        ref_image = "seedance_project/games/xundaodaqian/references/0045.jpg"
        
    print(f"🖼️ 使用首图: {ref_image}")
    print(f"💬 创意指令: {user_input}")
    
    if ref_video:
        print(f"🎥 指定了本地参考视频，跳过爬虫阶段: {ref_video}")
        # 如果提供了本地参考视频，我们强行让 pipeline 使用这个视频而不是去爬
        # 传递 ref_video 参数给 run_pipeline
        res = director.run_pipeline(user_input, ref_image, pipeline_mode="full_hybrid", provided_video=ref_video)
    else:
        print("🚀 启动全自动化流水线 pipeline_mode='full_hybrid' (包含自动爬虫)...")
        res = director.run_pipeline(user_input, ref_image, pipeline_mode="full_hybrid")
    
    print("\n" + "-"*30)
    print(f"流程执行完毕，状态: {res['status']}")
    if res["status"] == "success":
        if res.get("best_video_path"):
            print(f"🎥 成功下载并融合了最佳视频: {res['best_video_path']}")
        print(f"🎨 新生成的图片资产: {res['new_assets']}")
        print(f"🎉 最终混合计划存放在: {res['plan_path']}")
        
        # --- 新增: 调用 Seedance 2.0 API 提交视频生成任务 ---
        print("\n" + "="*50)
        print("=== 正在将剧本与资产提交至 Seedance 2.0 API ===")
        print("="*50)
        
        try:
            from seedance_api import create_seedance_task, poll_task_status, upload_video_to_tmpfiles
            import os
            
            # 获取提示词 (优先使用中文)
            plan_content = res.get("plan_content", {})
            prompt_text = plan_content.get("prompt_zh", "")
            if not prompt_text:
                prompt_text = plan_content.get("prompt_en", "生成一段战斗视频")
                
            # 收集要上传的图片路径
            # 1. 首图
            image_paths = []
            if os.path.exists(ref_image):
                image_paths.append(ref_image)
                
            # 2. 生成的素材图
            # 从 selected_assets 中提取所有图片
            selected_assets = plan_content.get("selected_assets", [])
            for asset_name in selected_assets:
                if asset_name.endswith(('.png', '.jpg', '.jpeg')):
                    # 如果不是首图，则去 assets_dir 找
                    asset_path = os.path.join(director.assets_dir, asset_name.lstrip('@'))
                    if os.path.exists(asset_path) and asset_path not in image_paths:
                        image_paths.append(asset_path)
                        
            # 注意：如果超过9张图，API 会报错，可在此截断
            image_paths = image_paths[:9]
            
            # 3. 处理视频 (火山API不支持本地视频，使用临时文件上传服务)
            video_url = None
            if res.get("best_video_path") and os.path.exists(res["best_video_path"]):
                print("\n[API要求] 正在处理本地参考视频转公网链接...")
                video_url = upload_video_to_tmpfiles(res["best_video_path"])
                if not video_url:
                    print("⚠️ 视频上传临时图床失败，任务将降级为不附带参考视频直接生成。")
            
            print("\n准备提交提示词:\n" + prompt_text)
            print(f"准备上传图片列表: {image_paths}")
            if video_url:
                print(f"准备上传视频链接: {video_url}")
            
            task_id = create_seedance_task(
                prompt_text=prompt_text,
                image_paths=image_paths,
                reference_video_url=video_url, # 传入上传好的公网URL
                duration=-1 # 让模型根据文本自动决定时长 (可选-1或具体的如 5 秒)
            )
            
            if task_id:
                # 轮询任务状态
                poll_task_status(task_id)
                
        except ImportError as e:
            print(f"⚠️ 无法导入 seedance_api，请确保环境配置正确。({e})")
        except FileNotFoundError as e:
            print(f"⚠️ 密钥未配置: {e}")
        except Exception as e:
            print(f"❌ 提交任务时发生错误: {e}")
            
    else:
        print(f"❌ 流程失败: {res.get('error')}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="测试 Seedance 视频生成工作流")
    parser.add_argument("--prompt", type=str, help="输入的创意指令", default=None)
    parser.add_argument("--image", type=str, help="参考的首图路径", default=None)
    parser.add_argument("--video", type=str, help="可选的本地参考视频路径，提供后将跳过爬虫直接使用该视频", default=None)
    parser.add_argument("--mode", type=str, choices=["a", "b", "c"], default="c", help="测试模式 (a=图生图, b=视频参考, c=全混合)")
    
    args = parser.parse_args()
    
    if args.mode == "a":
        # 你可以随时在这里切换注释，单独调试某一条路径
        test_path_a_image_only()
    elif args.mode == "b":
        test_path_b_video_reference()
    elif args.mode == "c":
        test_path_c_full_hybrid(user_input=args.prompt, ref_image=args.image, ref_video=args.video)
