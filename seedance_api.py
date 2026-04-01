import os
import time
import base64
import json
import requests

KEY_PATH = os.path.join(os.path.dirname(__file__), "keys", "seedance_key.txt")
# 如果你是用的火山引擎官方的 ARK_API_KEY，请将 BASE_URL 替换为下面的官方地址，并注释掉 tapsvc 的地址
BASE_URL = "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks"
# BASE_URL = "https://llm-proxy.tapsvc.com/volcengine/api/v3/contents/generations/tasks"

def get_api_key():
    if not os.path.exists(KEY_PATH):
        raise FileNotFoundError(f"未找到 API Key 文件：{KEY_PATH}。请先在该文件中填入您的 Key。")
    with open(KEY_PATH, "r", encoding="utf-8") as f:
        key = f.read().strip()
    if not key or key == "YOUR_SEEDANCE_API_KEY_HERE":
        raise ValueError(f"API Key 未正确配置。请在 {KEY_PATH} 中填入有效的 Seedance API Key。")
    
    # 只有使用 tapsvc 网关时才需要强制 sk- 前缀，如果直连火山引擎官方 API 则保留原样。
    if "tapsvc" in BASE_URL and not key.startswith("sk-"):
        key = "sk-" + key
        
    return key

def encode_image_to_base64(image_path):
    """将本地图片转换为 Base64 编码字符串"""
    ext = image_path.split('.')[-1].lower()
    if ext == 'jpg':
        ext = 'jpeg'
    with open(image_path, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
    return f"data:image/{ext};base64,{encoded_string}"

def upload_video_to_tmpfiles(video_path):
    """
    由于火山引擎API不支持本地视频，我们将视频临时上传至 tmpfiles.org 获取公网直链。
    注意：这是临时解决方案，视频仅保存较短时间。
    """
    if not os.path.exists(video_path):
        print(f"⚠️ 找不到视频文件: {video_path}")
        return None
        
    print(f"⬆️ 正在将本地参考视频上传至临时图床获取公网链接 (由于火山API不支持本地视频)...")
    try:
        with open(video_path, 'rb') as f:
            response = requests.post('https://tmpfiles.org/api/v1/upload', files={'file': f})
            
        if response.status_code == 200:
            res_json = response.json()
            if res_json.get('status') == 'success':
                # tmpfiles.org 返回的网页链接，需转换为直链 (通常是把 url 里的 org/ 替换为 org/dl/ )
                web_url = res_json['data']['url']
                direct_url = web_url.replace('tmpfiles.org/', 'tmpfiles.org/dl/')
                print(f"✅ 视频上传成功！临时公网链接: {direct_url}")
                return direct_url
        print(f"❌ 视频上传失败: HTTP {response.status_code} - {response.text}")
        return None
    except Exception as e:
        print(f"❌ 视频上传出现异常: {e}")
        return None

def create_seedance_task(prompt_text, image_paths, reference_video_url=None, duration=5, ratio="16:9", model="doubao-seedance-2-0-fast-260128"):
    """
    调用 Seedance 2.0 / 2.0 fast API 创建视频生成任务。
    
    参数:
        prompt_text (str): 提示词
        image_paths (list): 要作为参考图的本地图片路径列表 (首图 + 生成的素材)
        reference_video_url (str): 参考视频的公网 URL (注意: API不支持本地视频的 base64 上传)
        duration (int): 生成时长，[4,15] 或者 -1
        ratio (str): 生成视频的宽高比
        model (str): 模型名称
    """
    key = get_api_key()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}"
    }
    
    # 构造 content
    content = []
    
    # 1. 文本提示词
    if prompt_text:
        content.append({
            "type": "text",
            "text": prompt_text
        })
        
    # 2. 参考图片
    for i, img_path in enumerate(image_paths):
        if not os.path.exists(img_path):
            print(f"⚠️ 图片不存在，跳过: {img_path}")
            continue
            
        b64_img = encode_image_to_base64(img_path)
        content.append({
            "type": "image_url",
            "image_url": {
                "url": b64_img
            },
            # API 规定，多模态参考下所有图片均设为 reference_image
            "role": "reference_image"
        })
        
    # 3. 参考视频 (火山引擎要求必须是公网 URL，或内部素材 asset://)
    if reference_video_url:
        content.append({
            "type": "video_url",
            "video_url": {
                "url": reference_video_url
            },
            "role": "reference_video"
        })
    else:
        print("⚠️ 未提供参考视频的公网 URL。请注意，目前火山 API 不支持直接上传本地视频文件作为参考。若想融合视频风格，需将其上传至可公开访问的图床/TOS。")

    payload = {
        "model": model,
        "content": content,
        "resolution": "720p",
        "ratio": ratio,
        "duration": duration,
        "watermark": False,
        # "generate_audio": False  # 根据需要开启
    }

    # -- 新增：保存最新的请求 payload 供本地可视化 --
    try:
        preview_data = {
            "prompt_text": prompt_text,
            "images": image_paths, # 这里存原始路径方便网页显示，不存巨大的base64
            "video_url": reference_video_url,
            "duration": duration,
            "ratio": ratio
        }
        with open(os.path.join(os.path.dirname(__file__), "latest_payload.json"), "w", encoding="utf-8") as f:
            json.dump(preview_data, f, ensure_ascii=False, indent=2)
        print("📝 已将本次请求信息保存至 latest_payload.json，可打开 index.html 预览。")
    except Exception as e:
        print(f"⚠️ 保存预览文件失败: {e}")
    # ---------------------------------------------

    print("🚀 正在提交 Seedance 视频生成任务...")
    response = requests.post(BASE_URL, headers=headers, json=payload)
    
    if response.status_code == 200:
        res_json = response.json()
        task_id = res_json.get("id")
        print(f"✅ 任务提交成功！Task ID: {task_id}")
        return task_id
    else:
        print(f"❌ 任务提交失败。HTTP {response.status_code}")
        print(response.text)
        return None

def poll_task_status(task_id, poll_interval=15):
    """轮询任务状态"""
    key = get_api_key()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}"
    }
    url = f"{BASE_URL}/{task_id}"
    
    print(f"⏳ 开始轮询任务状态 (每 {poll_interval} 秒查询一次)...")
    while True:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            res_json = response.json()
            status = res_json.get("status")
            
            if status == "succeeded":
                print("\n🎉 任务已完成！")
                print("====================================")
                print(json.dumps(res_json, indent=2, ensure_ascii=False))
                print("====================================")
                # 一般在这个 json 里会有一个类似 res_json["content"] 或 res_json["video_url"] 的字段
                return res_json
            elif status in ["failed", "error"]:
                print(f"\n❌ 任务生成失败: {res_json.get('error', res_json)}")
                return res_json
            else:
                print(f"🔄 当前状态: {status}，请稍候...")
        else:
            print(f"⚠️ 查询请求失败 HTTP {response.status_code}: {response.text}")
            
        time.sleep(poll_interval)

if __name__ == "__main__":
    # 简单测试逻辑
    pass
