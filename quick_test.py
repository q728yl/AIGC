import os
import json
import time
from director_agent import SeedanceDirector

director = SeedanceDirector("xundaodaqian")
user_input = "生成一段大招战斗视频，我需要参考网上的实机演示来做动作设计"
ref_image = "seedance_project/games/xundaodaqian/references/0045.jpg"
video_path = "seedance_project/games/xundaodaqian/references/taptap_xundaodaqian_杖剑传说_实机_1774616335.mp4"

# Use some fake plan content to avoid slow generation
plan_content = {
    "thought": "Original thought",
    "selected_assets": ["0045.jpg", "battle_firstframe_mock_205348.png", "hero_ultimate_sprite_sheet_205433.png"],
    "prompt_en": "First Frame...",
    "prompt_zh": "首帧锁定..."
}

analysis = """
Here’s a concise **Motion Reference Profile** based on the provided keyframes.

## Overall Style
- **Format:** Vertical mobile-game promo / social short.
- **Tone:** Playful, colorful, casual challenge/quiz format.
- **Visual language:** Scrapbook / sticker-book UI, rounded frames, thick outlines, bright pastel colors, oversized Chinese text headers, mascot character in the lower-right corner.
- **Animation style:** 2D UI-driven motion graphics combined with in-game footage inserts. Motion likely snappy, elastic, and readable for mobile viewing.
"""

print("Testing _regenerate_plan_with_video_refs...")
try:
    enhanced_plan_path = director._regenerate_plan_with_video_refs(
        user_input, ref_image, director.reference_analysis, plan_content, analysis, [video_path]
    )
    print(f"Success! Path: {enhanced_plan_path}")
except Exception as e:
    print(f"Failed: {e}")
