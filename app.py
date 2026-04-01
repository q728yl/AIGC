import os
import json
from flask import Flask, request, jsonify, send_from_directory
from werkzeug.utils import secure_filename
from director_agent import SeedanceDirector

app = Flask(__name__, static_folder='seedance_project/static')

# 配置
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max

# 路由：主页
@app.route('/')
def index():
    return send_from_directory('seedance_project/static', 'index.html')

# 路由：静态文件（CSS, JS）
@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory('seedance_project/static', filename)

# 路由：获取游戏列表
@app.route('/api/games', methods=['GET'])
def get_games():
    games_dir = os.path.join('seedance_project', 'games')
    if not os.path.exists(games_dir):
        os.makedirs(games_dir)
        # 创建默认游戏目录
        os.makedirs(os.path.join(games_dir, 'xundaodaqian'))
    
    games = [d for d in os.listdir(games_dir) if os.path.isdir(os.path.join(games_dir, d))]
    return jsonify({"games": games})

# 路由：生成任务
@app.route('/api/generate', methods=['POST'])
def generate():
    try:
        game_name = request.form.get('game_name', 'xundaodaqian')
        instruction = request.form.get('instruction', '')
        
        if not instruction:
            return jsonify({"status": "error", "message": "Instruction is required"}), 400

        # 处理图片上传
        ref_image_path = None
        if 'image' in request.files:
            file = request.files['image']
            if file.filename != '':
                filename = secure_filename(file.filename)
                save_dir = os.path.join('seedance_project', 'games', game_name, 'references')
                if not os.path.exists(save_dir):
                    os.makedirs(save_dir)
                ref_image_path = os.path.join(save_dir, filename)
                file.save(ref_image_path)

        # 处理视频上传
        ref_video_path = None
        pipeline_mode = request.form.get('pipeline_mode', 'full_hybrid')
        
        if 'video' in request.files and pipeline_mode != 'image_only':
            video_file = request.files['video']
            if video_file.filename != '':
                video_filename = secure_filename(video_file.filename)
                save_dir = os.path.join('seedance_project', 'games', game_name, 'references')
                if not os.path.exists(save_dir):
                    os.makedirs(save_dir)
                ref_video_path = os.path.join(save_dir, video_filename)
                video_file.save(ref_video_path)

        # 初始化导演
        director = SeedanceDirector(game_name=game_name)
        
        # 运行管道，使用前端传入的 pipeline_mode
        result = director.run_pipeline(
            instruction, 
            ref_image_path=ref_image_path, 
            pipeline_mode=pipeline_mode, 
            provided_video=ref_video_path
        )
        
        if result["status"] == "success":
            # 不再立即提交到 Seedance，而是将需要的数据返回给前端供编辑
            try:
                from quick_submit import get_image_size, get_closest_ratio
                import re
                
                plan_content = result.get("plan_content", {})
                prompt_text = plan_content.get("prompt_zh", "")
                if not prompt_text:
                    prompt_text = plan_content.get("prompt_en", "生成一段战斗视频")
                
                # 动态计算视频时长
                duration = 5
                time_matches = re.findall(r'\[\d+s-(\d+)s\]', prompt_text)
                if time_matches:
                    max_time = max([int(m) for m in time_matches])
                    duration = max(4, min(15, max_time))  # 确保在 4 到 15 之间
                
                # 收集图片
                image_paths = []
                if ref_image_path and os.path.exists(ref_image_path):
                    image_paths.append(ref_image_path)
                    
                selected_assets = plan_content.get("selected_assets", [])
                for asset_name in selected_assets:
                    if asset_name.endswith(('.png', '.jpg', '.jpeg')):
                        asset_path = os.path.join(director.assets_dir, asset_name.lstrip('@'))
                        if os.path.exists(asset_path) and asset_path not in image_paths:
                            image_paths.append(asset_path)
                image_paths = image_paths[:9]
                
                # 动态计算长宽比
                ratio = "16:9"
                if image_paths and os.path.exists(image_paths[0]):
                    try:
                        width, height = get_image_size(image_paths[0])
                        ratio = get_closest_ratio(width, height)
                    except Exception as e:
                        print(f"获取图片尺寸失败: {e}")
                
                # 暂时保存这些状态，以便后续提交使用
                result["draft_submission"] = {
                    "prompt_text": prompt_text,
                    "image_paths": image_paths,
                    "best_video_path": result.get("best_video_path"),
                    "duration": duration,
                    "ratio": ratio
                }
                
                result["logs"].append("✅ 编排完成，等待用户确认 Prompt...")
                    
            except Exception as e:
                result["logs"].append(f"⚠️ 准备编辑流程出错: {e}")
                print(f"❌ 准备编辑流程出错: {e}")

        # 结果中如果包含绝对路径，我们需要做一些相对路径的转换，或者直接让前端拼接API
        # 为了前端好展示，提取出用到的最终素材列表
        # 把 best_video_path 变成纯文件名发给前端
        if result.get("best_video_path"):
            result["best_video_filename"] = os.path.basename(result["best_video_path"])
        
        return jsonify(result)

    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 路由：提交任务到 Seedance
@app.route('/api/submit_task', methods=['POST'])
def submit_task():
    try:
        from seedance_api import create_seedance_task, upload_video_to_tmpfiles
        
        data = request.json
        prompt_text = data.get("prompt_text")
        image_paths = data.get("image_paths", [])
        best_video_path = data.get("best_video_path")
        duration = data.get("duration", 5)
        ratio = data.get("ratio", "16:9")
        
        video_url = None
        if best_video_path and os.path.exists(best_video_path):
            video_url = upload_video_to_tmpfiles(best_video_path)
            
        task_id = create_seedance_task(
            prompt_text=prompt_text,
            image_paths=image_paths,
            reference_video_url=video_url,
            duration=duration,
            ratio=ratio
        )
        
        if task_id:
            return jsonify({"status": "success", "task_id": task_id})
        else:
            return jsonify({"status": "error", "message": "API 返回失败"}), 500
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 路由：检查任务状态并下载视频
@app.route('/api/check_task/<game_name>/<task_id>', methods=['GET'])
def check_task(game_name, task_id):
    try:
        from seedance_api import get_api_key
        import requests
        
        # We need to hit the API directly since poll_task_status loops
        key = get_api_key()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}"
        }
        
        # Depending on proxy vs direct
        BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
        url = f"{BASE_URL}/{task_id}"
        
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            res_json = response.json()
            status = res_json.get("status")
            
            if status == "succeeded":
                video_url = res_json.get("content", {}).get("video_url")
                if video_url:
                    # 下载到本地
                    save_dir = os.path.join('seedance_project', 'games', secure_filename(game_name), 'output')
                    if not os.path.exists(save_dir):
                        os.makedirs(save_dir)
                    
                    filename = f"generated_{task_id}.mp4"
                    local_path = os.path.join(save_dir, filename)
                    
                    if not os.path.exists(local_path):
                        print(f"⬇️ 正在下载生成的视频: {video_url}")
                        vid_res = requests.get(video_url)
                        with open(local_path, 'wb') as f:
                            f.write(vid_res.content)
                        print(f"✅ 视频已保存至: {local_path}")
                    
                    return jsonify({
                        "status": "succeeded", 
                        "video_url": video_url,
                        "local_filename": filename
                    })
                
            elif status in ["failed", "error"]:
                return jsonify({"status": "failed", "error": res_json.get('error', res_json)})
            
            return jsonify({"status": status})
            
        else:
            return jsonify({"status": "error", "message": f"HTTP {response.status_code}: {response.text}"}), 500
            
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# 路由：查看结果文件/素材
@app.route('/api/view/<game_name>/<filename>')
def view_file(game_name, filename):
    # 安全检查
    safe_game = secure_filename(game_name)
    safe_file = secure_filename(filename)

    base_dir = os.path.join('seedance_project', 'games', safe_game)
    for subdir in ('assets', 'output', 'references'):
        directory = os.path.join(base_dir, subdir)
        file_path = os.path.join(directory, safe_file)
        if os.path.exists(file_path):
            return send_from_directory(directory, safe_file)

    return "File not found", 404

if __name__ == '__main__':
    print("🚀 Seedance Web Server running on http://127.0.0.1:5050")
    app.run(host='0.0.0.0', debug=True, port=5050)
