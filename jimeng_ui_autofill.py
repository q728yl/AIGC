from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_APP_NAME = "ChromiteX"
ASSET_MENTION_PATTERN = re.compile(r"@([A-Za-z0-9._-]+)")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="直接操作当前前台即梦页面，自动填入中文 prompt 并逐张上传素材。"
    )
    parser.add_argument("plan", type=Path, help="Seedance 输出的 plan markdown 文件路径")
    parser.add_argument(
        "--app-name",
        default=DEFAULT_APP_NAME,
        help="当前使用的浏览器应用名，默认是 ChromiteX",
    )
    parser.add_argument(
        "--focus-delay",
        type=float,
        default=5.0,
        help="启动后留给你切到浏览器并点击输入框的倒计时秒数",
    )
    parser.add_argument(
        "--between-files-delay",
        type=float,
        default=0.9,
        help="每次粘贴图片后的等待秒数",
    )
    parser.add_argument(
        "--after-text-delay",
        type=float,
        default=0.5,
        help="粘贴文本后的等待秒数",
    )
    parser.add_argument(
        "--after-upload-delay",
        type=float,
        default=1.2,
        help="所有图片上传后，开始写 prompt 前的等待秒数",
    )
    parser.add_argument(
        "--mention-delay",
        type=float,
        default=0.6,
        help="输入 @素材名 后等待联想列表出现的秒数",
    )
    return parser.parse_args()


def ensure_dependencies():
    try:
        import pyautogui  # noqa: F401
        import pyperclip  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "缺少依赖，请先执行 `python -m pip install -r requirements.txt`。"
        ) from exc


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def parse_plan(plan_path: Path) -> tuple[str, str, list[str], Path]:
    text = read_text(plan_path)

    game_match = re.search(r"^#\s+Seedance Plan \(([^)]+)\)", text, re.MULTILINE)
    if not game_match:
        raise ValueError("无法从 plan 文件中解析游戏名。")
    game_name = game_match.group(1).strip()

    assets_match = re.search(
        r"^## 2\. Selected Assets\s*$\n`([^`]+)`", text, re.MULTILINE
    )
    if not assets_match:
        raise ValueError("无法从 plan 文件中解析 Selected Assets。")
    asset_names = re.findall(r"@([^,\s`]+)", assets_match.group(1))

    prompt_match = re.search(
        r"^## 4\. Chinese Prompt\s*$\n((?:>.*(?:\n|$))+)",
        text,
        re.MULTILINE,
    )
    if not prompt_match:
        raise ValueError("无法从 plan 文件中解析 Chinese Prompt。")

    prompt_lines = []
    for line in prompt_match.group(1).splitlines():
        if line.startswith(">"):
            prompt_lines.append(line[1:].lstrip())
        else:
            prompt_lines.append(line)
    chinese_prompt = "\n".join(prompt_lines).strip()

    if plan_path.parent.name == "output":
        game_dir = plan_path.parent.parent
    else:
        game_dir = (
            plan_path.parent.parent
            / "seedance_project"
            / "games"
            / game_name
        )

    return game_name, chinese_prompt, asset_names, game_dir


def resolve_asset_paths(game_dir: Path, asset_names: list[str]) -> list[Path]:
    search_dirs = [
        game_dir / "references",
        game_dir / "assets",
        game_dir / "output",
    ]

    resolved: list[Path] = []
    missing: list[str] = []

    for name in asset_names:
        found = None
        for base_dir in search_dirs:
            candidate = base_dir / name
            if candidate.exists():
                found = candidate
                break
        if found:
            resolved.append(found)
        else:
            missing.append(name)

    if missing:
        raise FileNotFoundError(
            "以下素材在游戏目录中未找到: " + ", ".join(missing)
        )

    return resolved


def copy_text_to_clipboard(text: str):
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


def copy_image_to_clipboard(path: Path):
    escaped_path = str(path).replace("\\", "\\\\").replace('"', '\\"')
    suffix = path.suffix.lower()

    if suffix == ".png":
        read_type = "«class PNGf»"
    elif suffix in {".jpg", ".jpeg"}:
        read_type = "JPEG picture"
    else:
        raise RuntimeError(f"暂不支持直接粘贴这种图片格式: {path.name}")

    script = (
        f'set the clipboard to (read (POSIX file "{escaped_path}") as {read_type})'
    )
    subprocess.run(["osascript", "-e", script], check=True)


def paste_text(pyautogui, text: str):
    if not text:
        return
    copy_text_to_clipboard(text)
    pyautogui.hotkey("command", "v")


def paste_image(pyautogui, path: Path, wait_seconds: float):
    copy_image_to_clipboard(path)
    time.sleep(0.15)
    pyautogui.hotkey("command", "v")
    time.sleep(wait_seconds)


def split_prompt_segments(prompt: str) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    last_index = 0
    for match in ASSET_MENTION_PATTERN.finditer(prompt):
        if match.start() > last_index:
            segments.append(("text", prompt[last_index:match.start()]))
        segments.append(("mention", match.group(1)))
        last_index = match.end()
    if last_index < len(prompt):
        segments.append(("text", prompt[last_index:]))
    return segments


def build_uploaded_asset_aliases(asset_paths: list[Path]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for index, path in enumerate(asset_paths, start=1):
        aliases[path.name] = f"图片{index}"
    return aliases


def insert_asset_mention(pyautogui, asset_name: str, wait_seconds: float):
    paste_text(pyautogui, "@")
    time.sleep(0.12)
    paste_text(pyautogui, asset_name)
    time.sleep(wait_seconds)
    pyautogui.press("down")
    time.sleep(0.08)
    pyautogui.press("enter")
    time.sleep(0.12)


def compose_prompt_with_mentions(
    pyautogui, prompt: str, uploaded_asset_aliases: dict[str, str], mention_delay: float
):
    segments = split_prompt_segments(prompt)
    if not segments:
        return

    for segment_type, value in segments:
        if segment_type == "text":
            paste_text(pyautogui, value)
            time.sleep(0.08)
            continue

        if value in uploaded_asset_aliases:
            insert_asset_mention(pyautogui, uploaded_asset_aliases[value], mention_delay)
        else:
            paste_text(pyautogui, f"@{value}")
            time.sleep(0.08)


def activate_app(app_name: str):
    subprocess.run(
        ["osascript", "-e", f'tell application "{app_name}" to activate'],
        check=False,
    )


def get_front_window_bounds(app_name: str) -> tuple[int, int, int, int]:
    script = f'''
    tell application "System Events"
        tell process "{app_name}"
            if (count of windows) is 0 then
                error "No window"
            end if
            set winPos to position of front window
            set winSize to size of front window
            return (item 1 of winPos as text) & "," & (item 2 of winPos as text) & "," & (item 1 of winSize as text) & "," & (item 2 of winSize as text)
        end tell
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(
            f"无法读取 {app_name} 前台窗口位置。请确认浏览器在前台，并给终端辅助功能权限。"
        )
    left, top, width, height = [int(v.strip()) for v in result.stdout.strip().split(",")]
    return left, top, width, height


def focus_jimeng_input_area(pyautogui, app_name: str):
    activate_app(app_name)
    time.sleep(0.3)
    left, top, width, height = get_front_window_bounds(app_name)

    # 经验坐标：即梦底部大输入容器的文本区域，大致位于窗口中下部偏左到中间区域
    click_points = [
        (left + int(width * 0.42), top + int(height * 0.78)),
        (left + int(width * 0.36), top + int(height * 0.74)),
        (left + int(width * 0.48), top + int(height * 0.74)),
    ]

    for x, y in click_points:
        pyautogui.click(x, y)
        time.sleep(0.15)


def main() -> int:
    ensure_dependencies()
    import pyautogui

    args = parse_args()
    if not args.plan.exists():
        print(f"plan 文件不存在: {args.plan}")
        return 1

    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.15

    game_name, chinese_prompt, asset_names, game_dir = parse_plan(args.plan)
    asset_paths = resolve_asset_paths(game_dir, asset_names)
    uploaded_asset_aliases = build_uploaded_asset_aliases(asset_paths)

    print(f"游戏: {game_name}")
    print(f"素材数量: {len(asset_paths)}")
    for index, asset_path in enumerate(asset_paths, start=1):
        print(f"  - 图片{index} <= {asset_path.name}")

    print("\n准备开始自动化。")
    print("请确认：")
    print("- 你当前已经打开并登录了即梦")
    print("- 当前页面就是你要操作的页面")
    print("- 当前模式已经切到“全能参考”")
    print("- 倒计时结束后，脚本会自动激活浏览器并尝试点击即梦底部输入区域")
    print(f"- 你有 {args.focus_delay:.1f} 秒时间把正确页面放到前台")
    input("\n准备好后按回车开始倒计时...")

    for remain in range(int(args.focus_delay), 0, -1):
        print(f"{remain}...")
        time.sleep(1)

    total = len(asset_paths)
    for index, asset_path in enumerate(asset_paths, start=1):
        print(f"粘贴图片 {index}/{total}: {asset_path.name}")
        paste_image(pyautogui, asset_path, args.between_files_delay)

    time.sleep(args.after_upload_delay)
    focus_jimeng_input_area(pyautogui, args.app_name)
    time.sleep(0.2)
    compose_prompt_with_mentions(
        pyautogui, chinese_prompt, uploaded_asset_aliases, args.mention_delay
    )
    time.sleep(args.after_text_delay)

    print("\n已完成：")
    print("- 中文 prompt 已写入")
    print("- 素材已按当前焦点输入框逐张粘贴")
    print("- prompt 中的 @素材名 已按上传顺序映射为 @图片1、@图片2... 后再自动关联")
    print("- 脚本不会点击“生成”")
    return 0


if __name__ == "__main__":
    sys.exit(main())
