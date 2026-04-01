import asyncio
from playwright.async_api import async_playwright
import os
import time
import urllib.parse
import requests

async def search_and_download_taptap_video(game_name: str, keyword: str, download_dir: str):
    """
    使用 Playwright 自动化搜索 TapTap 并尝试下载相关视频
    """
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)

    print(f"🚀 开始在 TapTap 搜索: {game_name} {keyword}")
    
    async with async_playwright() as p:
        # 启动浏览器 (headless=False 可以看到页面操作过程)
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(
            viewport={'width': 1280, 'height': 800},
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await context.new_page()

        try:
            # 1. 访问 TapTap 搜索页
            # 如果是大模型识别出的关键词包含多个搜索条件，可能导致 TapTap 搜不到
            # 比如 "寻道大千 大招 实机演示"，我们只提取最核心的 "游戏名 关键词"
            # 简化搜索词，提高命中率
            search_query = f"{game_name} " + keyword.replace(game_name, "").strip()
            # 限制搜索词长度，避免太复杂的句子搜不到
            words = search_query.split()
            if len(words) > 3:
                search_query = " ".join(words[:3])
                
            encoded_query = urllib.parse.quote(search_query)
            search_url = f"https://www.taptap.cn/search/{encoded_query}"
            print(f"🌐 访问搜索页: {search_url} (原词: {keyword})")
            
            # 设置拦截器捕获视频资源请求
            video_src = None
            async def handle_response(response):
                nonlocal video_src
                url = response.url
                if response.request.resource_type == "media" or ".mp4" in url:
                    if video_src is None and "blank" not in url:
                        video_src = url
                        print(f"🎯 成功拦截到视频源链接: {video_src[:100]}...")
                        
                # 获取网页初始化时的 API 数据
                if "webapiv2" in url and response.request.resource_type in ["xhr", "fetch"]:
                    # print(f"🕵️ 发现 API 请求: {url}")
                    pass
                
                if "webapiv2/search/v6/agg-search" in url and response.request.resource_type in ["xhr", "fetch"]:
                    try:
                        data = await response.json()
                        with open("taptap_agg_search.json", "w", encoding="utf-8") as f:
                            import json
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        print("📦 成功拦截并保存了搜索 API 返回的 JSON: taptap_agg_search.json")
                    except Exception as e:
                        print(f"❌ 解析搜索结果 API 失败: {e}")

            page.on("response", handle_response)
            
            # 访问页面
            await page.goto(search_url, wait_until='domcontentloaded')
            await page.wait_for_timeout(3000) # 等待渲染
            
            print("🔄 刷新页面以获取正常内容...")
            try:
                await page.reload(wait_until='domcontentloaded')
            except Exception as e:
                print(f"刷新时忽略错误: {e}")
            await page.wait_for_timeout(4000)
            
            # 向下滚动以触发懒加载
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(2000)
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(2000)
            
            print("🔍 寻找页面中的播放按钮或帖子...")
            
            # 更智能地寻找TapTap视频帖子，过滤掉明显的广告或非视频内容
            post_links = []
            
            # TapTap的新版UI中，视频通常在类似 `.video-card`, `.tap-video` 或带有播放图标的结构里
            # 如果直接找 a 标签，我们加上一些更严格的过滤
            links = page.locator("a")
            count = await links.count()
            for i in range(count):
                href = await links.nth(i).get_attribute("href")
                if href and "/moment/" in href:
                    # 尝试判断它是不是一个视频类型的帖子 (看有没有播放量、时长标签等)
                    inner_text = await links.nth(i).inner_text()
                    # 只要是moment我们就先收下，之后靠下载工具去辨别
                    full_link = href if href.startswith("http") else f"https://www.taptap.cn{href}"
                    if full_link not in post_links:
                        post_links.append(full_link)
            
            # 如果直接找没找到好的，尝试找包含播放时间的元素
            if len(post_links) < 3:
                # 寻找可能有视频特征的组件
                video_elements = page.locator("div:has(span:text-matches('[0-9]+:[0-9]+', 'g'))")
                v_count = await video_elements.count()
                for i in range(v_count):
                    try:
                        parent_a = video_elements.nth(i).locator("xpath=ancestor::a").first
                        if await parent_a.count() > 0:
                            href = await parent_a.get_attribute("href")
                            if href and "/moment/" in href:
                                full_link = href if href.startswith("http") else f"https://www.taptap.cn{href}"
                                if full_link not in post_links:
                                    post_links.append(full_link)
                    except:
                        pass
            
            if len(post_links) > 0:
                print(f"✅ 找到 {len(post_links)} 个帖子链接，准备使用 yt-dlp 下载前 3 个...")
                
                # 关闭浏览器，交给 yt-dlp
                await browser.close()
                
                import yt_dlp
                downloaded_files = []
                
                for idx, target_url in enumerate(post_links[:3]):
                    print(f"⬇️ 准备调用 yt-dlp 下载视频 {idx+1}: {target_url}...")
                    filename = f"taptap_{game_name}_{keyword.replace(' ', '_')}_{int(time.time())}_{idx}.mp4"
                    filepath = os.path.join(download_dir, filename)
                    
                    ydl_opts = {
                        'outtmpl': filepath,
                        'quiet': False,
                        'merge_output_format': 'mp4',
                        'ffmpeg_location': '/Users/xd/.local/lib/python3.13/site-packages/imageio_ffmpeg/binaries/ffmpeg-macos-x86_64-v7.1'
                    }
                    
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            info = ydl.extract_info(target_url, download=True)
                            print(f"🎉 视频 {idx+1} 下载完成！文件已保存至: {filepath}")
                            if os.path.exists(filepath):
                                downloaded_files.append(filepath)
                    except Exception as e:
                        print(f"❌ 视频 {idx+1} yt-dlp 下载失败: {e}")
                
                if downloaded_files:
                    return downloaded_files
                else:
                    return None
            else:
                print("⚠️ 未找到帖子链接。")
                await page.screenshot(path="taptap_search_debug_final.png", full_page=True)
                return None
                
        except Exception as e:
            print(f"❌ 爬取过程中发生错误: {e}")
            
        finally:
            if browser.is_connected():
                await browser.close()
            
    return None

if __name__ == "__main__":
    game = "杖剑传说"
    kw = "实机" # 稍微换个词测试，或者就用空
    save_dir = "./references"
    
    # 临时用于测试单页面提取视频的函数
    async def test_single_page(url, download_dir):
        if not os.path.exists(download_dir):
            os.makedirs(download_dir)
            
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context(
                viewport={'width': 1280, 'height': 800},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = await context.new_page()
            
            video_src = None
            # 在加载期间监听 API 响应数据
            api_data_videos = []
            
            async def handle_response(response):
                nonlocal video_src
                url = response.url
                
                # 监听媒体流，TapTap 视频可能不带 .mp4 后缀，而是在特定域名或包含特定字眼
                if response.request.resource_type == "media" or "video" in response.headers.get("content-type", "") or ".mp4" in url:
                    print(f"📡 捕获媒体请求: {url[:100]}...")
                    if video_src is None and not url.startswith("blob:"):
                        video_src = url
                        print(f"🎯 选定下载链接: {video_src[:100]}...")
                        
                # 监听 API 响应以防视频 URL 在 JSON 里
                if "webapiv2/moment" in url and response.request.resource_type in ["xhr", "fetch"]:
                    try:
                        data = await response.json()
                        print(f"📦 拦截到动态数据 API: {url[:80]}...")
                        # 尝试从 JSON 中深度搜索 mp4 链接
                        import json
                        json_str = json.dumps(data)
                        import re
                        mp4_links = re.findall(r'https?://[^\s"\'\\]+\.mp4[^\s"\'\\]*', json_str)
                        if mp4_links:
                            print(f"💡 从 API 响应中找到 MP4 链接: {mp4_links[0][:100]}")
                            if not video_src:
                                video_src = mp4_links[0]
                    except:
                        pass
            
            page.on("response", handle_response)
            
            print(f"🌐 访问详情页: {url}")
            await page.goto(url, wait_until='networkidle')
            await page.wait_for_timeout(3000)
            
            # 测试：这可能不是一个视频帖子，或者是格式非常特殊的帖子。
            # 我们直接从 TapTap 搜索 API 请求获取视频数据。
            # TapTap 的搜索接口是: https://www.taptap.cn/webapiv2/search/v1/keyword
            # 我们可以直接抓取这些返回 JSON 从而得到真实的 MP4。
            nuxt_data = await page.evaluate('''() => {
                try {
                    return JSON.stringify(window.__NUXT__);
                } catch(e) { return null; }
            }''')
            
            if nuxt_data:
                import json
                try:
                    # 尝试用正则找视频链接，不局限于 mp4
                    import re
                    # 寻找包含 /video/ 或者 mp4 的链接
                    video_links = re.findall(r'https?://[^"\']*(?:mp4|video|vod)[^"\']*', nuxt_data)
                    for link in video_links:
                        # 过滤掉一些明显的图片或非视频链接
                        if not link.endswith((".jpg", ".png", ".webp")) and ("tap-video" in link or "vod" in link or ".mp4" in link):
                            print(f"💡 从网页全局变量找到疑似视频链接: {link[:100]}")
                            if not video_src:
                                video_src = link
                                break
                except Exception as e:
                    print(f"解析全局变量失败: {e}")
            
            # 尝试在页面上寻找帖子正文区域并点击
            try:
                print("🖱️ 尝试点击帖子主体区域...")
                # 寻找包含 TapTap 动态正文的常见类名，或者直接定位中间的图片/视频占位符
                post_area = page.locator(".tap-post-detail, .post-content, .video-container, .tap-video")
                if await post_area.count() > 0:
                    await post_area.first.click()
                    await page.wait_for_timeout(2000)
            except Exception as e:
                print(f"点击帖子主体区域失败: {e}")
                
            # 延迟等待更多 API 和渲染
            await page.wait_for_timeout(5000)
            
            nuxt_data = await page.evaluate('''() => {
                // 尝试抓取 window 全局变量里的视频链接
                const html = document.documentElement.innerHTML;
                const matches = html.match(/https?:\\/\\/[^"\'\\s]+\\.mp4[^"\'\\s]*/g);
                if (matches) return JSON.stringify(matches);
                return null;
            }''')
            
            if nuxt_data:
                import json
                try:
                    mp4_links = json.loads(nuxt_data)
                    for link in mp4_links:
                        link = link.replace('\\/', '/')
                        if not link.endswith((".jpg", ".png", ".webp")):
                            print(f"💡 从整个页面源码正则匹配到 mp4: {link[:100]}")
                            if not video_src:
                                video_src = link
                                break
                except Exception as e:
                    print(f"解析全局变量失败: {e}")
                    
            # 等待网络请求被拦截
            for _ in range(15):
                if video_src: break
                await page.wait_for_timeout(1000)
                
            # 尝试直接通过 API 获取视频信息
            # TapTap 的动态页面有时会通过接口加载数据，比如 /webapiv2/moment/v3/detail
            # 但如果没有触发点击，视频可能不会自动播放。
            
            # 检查是否有 x-gigua 等视频播放器的容器
            try:
                gigua_el = page.locator("xg-video-container, xg-start")
                if await gigua_el.count() > 0:
                    print("🖱️ 找到 xgplayer 容器，尝试点击...")
                    await gigua_el.first.click()
            except:
                pass
                
            # 检查 DOM
            try:
                await page.screenshot(path="taptap_single_page_debug.png", full_page=True)
                
                # 获取所有 iframe
                iframes = page.locator("iframe")
                count = await iframes.count()
                for i in range(count):
                    src = await iframes.nth(i).get_attribute("src")
                    print(f"🖼️ iframe src: {src}")
                    
                # 再次强行执行 JS 获取 HTML 里的数据
                page_content = await page.content()
                import re
                mp4_links = re.findall(r'https?://[^"\'\s]+\.mp4[^"\'\s]*', page_content)
                if mp4_links:
                     print(f"💡 从整个页面源码正则匹配到 mp4: {mp4_links[0][:100]}")
                     if not video_src:
                         video_src = mp4_links[0]
                         
                video_el = page.locator("video").first
                if await video_el.count() > 0:
                    src = await video_el.get_attribute("src")
                    print(f"📺 DOM 中 video 的 src: {src}")
                else:
                    print("❌ 页面中没有找到 video 标签")
            except Exception as e:
                print(f"DOM 检查失败: {e}")
                
            await browser.close()

    print("--- 开始 TapTap 视频爬取测试 ---")
    asyncio.run(search_and_download_taptap_video(game, kw, save_dir))
    print("--- 测试结束 ---")
