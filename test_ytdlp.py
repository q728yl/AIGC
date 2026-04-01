import yt_dlp

URL = 'https://www.taptap.cn/moment/733276860904901101'

ydl_opts = {
    'outtmpl': 'taptap_test_video.%(ext)s',
    'quiet': False
}

print(f"Testing yt-dlp with URL: {URL}")
try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([URL])
    print("Download successful!")
except Exception as e:
    print(f"Error: {e}")
