import requests
import json
import urllib.parse
import yt_dlp

def search_taptap_videos(keyword):
    # 尝试访问 TapTap Web 搜索 API
    print(f"🔍 正在搜索 TapTap: {keyword}")
    
    import urllib.parse
    
    # 构造 X-UA 参数，TapTap 的 webapiv2 通常需要带上它
    x_ua = "V=1&PN=WebApp&LANG=zh_CN&VN_CODE=100&VN=0.1.0&LOC=CN&PLT=PC&DS=Mac OS&UID=&OS=Mac OS&CH=default&DT=PC&CV=120.0.0.0"
    x_ua_encoded = urllib.parse.quote(x_ua)
    
    url = f"https://www.taptap.cn/webapiv2/search/v6/agg-search?keyword={urllib.parse.quote(keyword)}&X-UA={x_ua_encoded}"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.taptap.cn/'
    }
    
    # 获取搜索页面的动态 (Post/Video) 或聚合结果
    # 我们可以先看看 API 返回的内容
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            # print(json.dumps(data, indent=2, ensure_ascii=False)[:1000])
            with open("taptap_search_result.json", "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("✅ 搜索 API 访问成功，结果已保存到 taptap_search_result.json")
            
            # 简单解析一下看看有没有视频内容
            # TapTap 的聚合搜索结果通常在 data.list 里面
            video_links = []
            if "data" in data and "list" in data["data"]:
                for item in data["data"]["list"]:
                    # 寻找动态或者视频
                    if "moment" in item:
                        moment = item["moment"]
                        if "video" in moment:
                            video_id = moment["video"].get("id")
                            if video_id:
                                print(f"🎥 找到视频内容: {moment.get('title') or moment.get('summary')} (ID: {video_id})")
                                video_links.append(f"https://www.taptap.cn/video/{video_id}")
                                
            return video_links
        else:
            print(f"❌ 搜索请求失败: {response.status_code}")
    except Exception as e:
        print(f"❌ 请求发生错误: {e}")
        
    return []

if __name__ == "__main__":
    links = search_taptap_videos("寻道大千 战斗 技能")
    print(f"找到 {len(links)} 个视频链接: {links}")
    
    if links:
        target_url = links[0]
        print(f"\n⬇️ 尝试使用 yt-dlp 下载: {target_url}")
        ydl_opts = {
            'outtmpl': 'taptap_api_test.%(ext)s',
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([target_url])

