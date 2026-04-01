from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import Error, sync_playwright


JIMENG_URL = "https://jimeng.jianying.com/ai-tool/generate?type=video&workspace=0"
DEFAULT_PROFILE_DIR = Path.home() / ".jimeng-playwright-profile"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="将 Seedance plan 自动填入即梦视频生成页面。"
    )
    parser.add_argument("plan", type=Path, help="Seedance 输出的 plan markdown 文件路径")
    parser.add_argument(
        "--url",
        default=JIMENG_URL,
        help="即梦生成页地址，默认是视频生成页",
    )
    parser.add_argument(
        "--profile-dir",
        type=Path,
        default=DEFAULT_PROFILE_DIR,
        help="Playwright 持久化浏览器配置目录；首次登录后会复用会话",
    )
    parser.add_argument(
        "--wait-after-upload-ms",
        type=int,
        default=1500,
        help="上传文件后等待页面处理的毫秒数",
    )
    parser.add_argument(
        "--browser-path",
        type=Path,
        help="指定本机浏览器可执行文件或 .app 路径，例如 /Applications/ChromiteX.app",
    )
    parser.add_argument(
        "--connect-cdp",
        help="连接一个已手动启动并开启远程调试端口的 Chromium 浏览器，例如 http://127.0.0.1:9222",
    )
    return parser.parse_args()


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


def normalize_browser_path(browser_path: Path) -> Path:
    browser_path = browser_path.expanduser()
    if browser_path.suffix == ".app":
        app_name = browser_path.stem
        candidate = browser_path / "Contents" / "MacOS" / app_name
        if candidate.exists():
            return candidate
    return browser_path


def launch_browser(play, profile_dir: Path, browser_path: Path | None = None):
    profile_dir.mkdir(parents=True, exist_ok=True)
    launch_options = {
        "user_data_dir": str(profile_dir),
        "headless": False,
        "viewport": {"width": 1500, "height": 960},
    }

    local_browser_candidates = [
        "/Applications/ChromiteX.app/Contents/MacOS/ChromiteX",
        "/Applications/ChromiteX.app",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    ]

    if browser_path:
        normalized_path = normalize_browser_path(browser_path)
        if not normalized_path.exists():
            raise RuntimeError(f"指定的浏览器路径不存在: {normalized_path}")
        try:
            return play.chromium.launch_persistent_context(
                executable_path=str(normalized_path),
                **launch_options,
            )
        except Error as exc:
            raise RuntimeError(
                f"无法使用指定浏览器启动: {normalized_path}"
            ) from exc

    try:
        return play.chromium.launch_persistent_context(
            channel="chrome",
            **launch_options,
        )
    except Error:
        pass

    for browser_path in local_browser_candidates:
        normalized_path = normalize_browser_path(Path(browser_path))
        if normalized_path.exists():
            try:
                return play.chromium.launch_persistent_context(
                    executable_path=str(normalized_path),
                    **launch_options,
                )
            except Error:
                continue

    try:
        return play.chromium.launch_persistent_context(**launch_options)
    except Error as exc:
        raise RuntimeError(
            "无法启动浏览器。请先执行 `python -m playwright install chromium`，"
            "或者确保本机已安装 Google Chrome / Chromium。"
        ) from exc


def connect_browser_over_cdp(play, endpoint: str):
    try:
        browser = play.chromium.connect_over_cdp(endpoint)
    except Error as exc:
        raise RuntimeError(
            f"无法连接到 CDP 端点: {endpoint}\n"
            "请确认你已经手动启动浏览器，并带上 --remote-debugging-port=9222 一类参数。"
        ) from exc

    if browser.contexts:
        context = browser.contexts[0]
    else:
        raise RuntimeError(
            "已连接到浏览器，但未发现可用 context。请确认浏览器是以普通窗口方式启动的。"
        )

    return browser, context


def pick_best_handle(handles):
    best_handle = None
    best_area = 0
    for handle in handles:
        try:
            box = handle.bounding_box()
        except Error:
            continue
        if not box:
            continue
        area = box["width"] * box["height"]
        if box["width"] < 120 or box["height"] < 24:
            continue
        if area > best_area:
            best_area = area
            best_handle = handle
    return best_handle


def find_prompt_handle(page):
    selectors = [
        "textarea",
        "[contenteditable='true']",
        "[role='textbox']",
        ".ProseMirror",
        ".ql-editor",
        "[data-slate-editor='true']",
    ]
    for selector in selectors:
        handles = page.locator(selector).element_handles()
        handle = pick_best_handle(handles)
        if handle:
            return handle
    return None


def find_file_input_handle(page):
    handles = page.locator("input[type='file']").element_handles()
    if not handles:
        return None
    return handles[0]


def click_best_text_target(page, text: str, min_width: int = 40):
    handles = page.get_by_text(text, exact=True).element_handles()
    best_handle = None
    best_area = 0
    for handle in handles:
        try:
            box = handle.bounding_box()
        except Error:
            continue
        if not box:
            continue
        if box["width"] < min_width or box["height"] < 20:
            continue
        area = box["width"] * box["height"]
        if area > best_area:
            best_area = area
            best_handle = handle
    if best_handle:
        best_handle.click(force=True)
        return True
    return False


def has_visible_text_target(page, text: str, min_width: int = 40):
    handles = page.get_by_text(text, exact=True).element_handles()
    for handle in handles:
        try:
            box = handle.bounding_box()
        except Error:
            continue
        if not box:
            continue
        if box["width"] >= min_width and box["height"] >= 20:
            return True
    return False


def ensure_reference_mode(page, mode_name: str = "全能参考"):
    page.wait_for_timeout(1200)

    # 很多时候页面默认就是“全能参考”，此时直接视为成功，避免误判失败
    current_mode_candidates = [
        page.locator("button").filter(has_text=mode_name),
        page.locator("[role='button']").filter(has_text=mode_name),
        page.locator("div").filter(has_text=mode_name),
    ]
    for locator in current_mode_candidates:
        try:
            if locator.count() > 0:
                return
        except Error:
            continue

    if has_visible_text_target(page, mode_name, min_width=50):
        return

    # 先尝试点击底部模式选择按钮
    trigger_candidates = [
        page.locator("button").filter(has_text=mode_name),
        page.locator("[role='button']").filter(has_text=mode_name),
        page.locator("div").filter(has_text=mode_name),
    ]

    clicked_trigger = False
    for locator in trigger_candidates:
        try:
            if locator.count() > 0:
                locator.first.click(force=True)
                clicked_trigger = True
                break
        except Error:
            continue

    if not clicked_trigger:
        click_best_text_target(page, mode_name)

    page.wait_for_timeout(600)

    # 弹层里再次选择“全能参考”
    option_clicked = click_best_text_target(page, mode_name, min_width=60)
    if not option_clicked:
        option_candidates = [
            page.locator("[role='menuitem']").filter(has_text=mode_name),
            page.locator("[role='option']").filter(has_text=mode_name),
            page.locator("li").filter(has_text=mode_name),
        ]
        for locator in option_candidates:
            try:
                if locator.count() > 0:
                    locator.first.click(force=True)
                    option_clicked = True
                    break
            except Error:
                continue

    if not option_clicked:
        if has_visible_text_target(page, mode_name, min_width=50):
            return
        raise RuntimeError("未能切换到“全能参考”模式，请检查页面结构是否变化。")

    page.wait_for_timeout(800)


def fill_prompt(page, prompt_handle, prompt: str):
    tag_name = prompt_handle.evaluate("el => el.tagName.toLowerCase()")
    if tag_name in {"textarea", "input"}:
        prompt_handle.fill(prompt)
        return

    prompt_handle.click(force=True)
    prompt_handle.evaluate(
        """el => {
            el.focus();
            if ('value' in el) el.value = '';
            el.innerHTML = '';
            el.textContent = '';
        }"""
    )
    page.keyboard.press("Meta+A")
    page.keyboard.insert_text(prompt)


def wait_for_ready(page) -> tuple[object | None, object | None]:
    for _ in range(15):
        prompt_handle = find_prompt_handle(page)
        file_input_handle = find_file_input_handle(page)
        if prompt_handle and file_input_handle:
            return prompt_handle, file_input_handle
        page.wait_for_timeout(1000)
    return None, None


def get_page_from_context(
    context,
    prefer_new_page: bool = False,
    preferred_url_keyword: str | None = None,
):
    if prefer_new_page:
        return context.new_page()

    if preferred_url_keyword and context.pages:
        for page in reversed(context.pages):
            try:
                current_url = page.url or ""
            except Error:
                continue
            if preferred_url_keyword in current_url:
                return page

    if context.pages:
        return context.pages[-1]
    return context.new_page()


def get_existing_cdp_page(context, preferred_url_keyword: str):
    matching_pages = []
    for page in context.pages:
        try:
            current_url = page.url or ""
        except Error:
            continue
        if preferred_url_keyword in current_url:
            matching_pages.append(page)

    if not matching_pages:
        return None

    # 优先使用当前可见/聚焦的页面，其次使用最近的匹配页
    for page in reversed(matching_pages):
        try:
            is_visible = page.evaluate("document.visibilityState === 'visible'")
            has_focus = page.evaluate("document.hasFocus()")
        except Error:
            continue
        if is_visible or has_focus:
            return page

    return matching_pages[-1]


def safe_goto(page, url: str, wait_until: str = "domcontentloaded", retries: int = 2):
    last_exc = None
    for attempt in range(retries + 1):
        try:
            page.goto(url, wait_until=wait_until)
            return
        except Error as exc:
            last_exc = exc
            if "ERR_ABORTED" in str(exc):
                page.wait_for_timeout(1500)
                current_url = page.url or ""
                if current_url.startswith("https://jimeng.jianying.com/"):
                    return
            if attempt < retries:
                page.wait_for_timeout(1200)
                continue
            raise
    if last_exc:
        raise last_exc


def wait_for_file_input(page, attempts: int = 10):
    for _ in range(attempts):
        file_input_handle = find_file_input_handle(page)
        if file_input_handle:
            return file_input_handle
        page.wait_for_timeout(500)
    return None


def reopen_upload_picker(page):
    trigger_locators = [
        page.get_by_text("参考内容", exact=False),
        page.get_by_text("添加参考内容", exact=False),
        page.get_by_text("上传", exact=False),
        page.get_by_text("+", exact=True),
    ]

    for locator in trigger_locators:
        try:
            if locator.count() > 0:
                locator.first.click(force=True)
                page.wait_for_timeout(800)
                file_input_handle = wait_for_file_input(page, attempts=6)
                if file_input_handle:
                    return file_input_handle
        except Error:
            continue

    # 兜底：尝试点击页面左侧/输入区较明显的上传卡片
    fallback_selectors = [
        "[class*='upload']",
        "[class*='Upload']",
        "[class*='reference']",
        "[class*='Reference']",
        "[aria-label*='参考']",
        "[aria-label*='上传']",
    ]
    for selector in fallback_selectors:
        try:
            locator = page.locator(selector)
            if locator.count() > 0:
                locator.first.click(force=True)
                page.wait_for_timeout(800)
                file_input_handle = wait_for_file_input(page, attempts=6)
                if file_input_handle:
                    return file_input_handle
        except Error:
            continue

    return None


def upload_assets(page, initial_file_input_handle, asset_paths: list[Path], wait_ms: int):
    is_multiple = initial_file_input_handle.evaluate("el => !!el.multiple")
    if is_multiple:
        initial_file_input_handle.set_input_files([str(path) for path in asset_paths])
        page.wait_for_timeout(wait_ms)
        return

    total = len(asset_paths)
    for index, asset_path in enumerate(asset_paths, start=1):
        file_input_handle = wait_for_file_input(page)
        if not file_input_handle:
            file_input_handle = reopen_upload_picker(page)
        if not file_input_handle:
            raise RuntimeError("上传过程中未找到文件上传控件，请检查页面是否变化。")

        print(f"上传素材 {index}/{total}: {asset_path.name}")
        file_input_handle.set_input_files(str(asset_path))
        page.wait_for_timeout(wait_ms)


def main() -> int:
    args = parse_args()
    if not args.plan.exists():
        print(f"plan 文件不存在: {args.plan}")
        return 1

    game_name, chinese_prompt, asset_names, game_dir = parse_plan(args.plan)
    asset_paths = resolve_asset_paths(game_dir, asset_names)

    print(f"游戏: {game_name}")
    print(f"素材数量: {len(asset_paths)}")
    for asset_path in asset_paths:
        print(f"  - {asset_path}")

    with sync_playwright() as play:
        browser = None
        if args.connect_cdp:
            browser, context = connect_browser_over_cdp(play, args.connect_cdp)
        else:
            context = launch_browser(play, args.profile_dir, args.browser_path)

        if args.connect_cdp:
            page = get_existing_cdp_page(
                context,
                preferred_url_keyword="jimeng.jianying.com",
            )
            if not page:
                raise RuntimeError(
                    "CDP 模式下未找到你当前已打开的即梦页面。\n"
                    "请先在 ChromiteX 中手动打开 https://jimeng.jianying.com/ai-tool/generate?type=video&workspace=0 ，"
                    "并停留在要操作的那个标签页。"
                )
            print("CDP 模式：将直接使用你当前已经打开好的浏览器页面，不再自动跳转或切换模式。")
        else:
            page = get_page_from_context(context, prefer_new_page=False)
            safe_goto(page, args.url, wait_until="domcontentloaded")
            ensure_reference_mode(page, "全能参考")

        prompt_handle, file_input_handle = wait_for_ready(page)
        if not prompt_handle or not file_input_handle:
            print("未自动检测到输入框或上传控件。")
            input("请在浏览器中手动打开正确页面并确保上传区域可见后按回车继续...")
            prompt_handle, file_input_handle = wait_for_ready(page)

        if not prompt_handle:
            print("仍未找到 prompt 输入框，请检查页面结构是否变化。")
            context.close()
            return 2

        if not file_input_handle:
            print("仍未找到文件上传控件，请检查页面结构是否变化。")
            context.close()
            return 3

        fill_prompt(page, prompt_handle, chinese_prompt)
        upload_assets(page, file_input_handle, asset_paths, args.wait_after_upload_ms)

        print("\n已完成：")
        print("- 中文 prompt 已填入")
        print("- 相关素材已上传到页面")
        print("- 浏览器会保持打开，你可以检查后手动点击生成")
        if args.connect_cdp:
            input("\n确认无误后按回车断开脚本连接（不会关闭你手动打开的浏览器）...")
            browser.close()
        else:
            input("\n确认无误后按回车关闭脚本（不会自动点击生成）...")
            context.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
