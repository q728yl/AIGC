from __future__ import annotations

import argparse
import sys
import time


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="测试当前前台焦点输入框是否能接收到自动粘贴。"
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=5.0,
        help="开始前倒计时秒数，留给你点进输入框",
    )
    parser.add_argument(
        "--text",
        default="[AUTOFOCUS_TEST]",
        help="要粘贴到当前焦点输入框的测试文字",
    )
    return parser.parse_args()


def ensure_dependencies():
    try:
        import pyautogui  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(
            "缺少依赖，请先执行 `python -m pip install -r requirements.txt`。"
        ) from exc


def copy_text_to_clipboard(text: str):
    import subprocess
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=True)


def main() -> int:
    ensure_dependencies()
    import pyautogui

    args = parse_args()
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.15

    print("请先手动打开目标页面，并用鼠标点进你想测试的输入框。")
    print("倒计时结束后，脚本会向你当前已经点中的焦点输入框粘贴测试文字。")
    input("\n准备好后按回车开始倒计时...")

    for remain in range(int(args.delay), 0, -1):
        print(f"{remain}...")
        time.sleep(1)

    copy_text_to_clipboard(args.text)
    pyautogui.hotkey("command", "v")

    print("\n已执行粘贴。")
    print(f"如果输入框里出现了 `{args.text}`，说明权限和焦点链路是通的。")
    print("如果什么都没出现，优先检查 macOS 的辅助功能/自动化权限。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
