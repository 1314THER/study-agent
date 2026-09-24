"""Prepare a local clone and start its FastAPI server."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser


ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
REQUIREMENTS = ROOT / "requirements.txt"
FINGERPRINT = VENV / ".requirements.sha256"
URL = "http://127.0.0.1:8000/home.html"
HEALTH_URL = "http://127.0.0.1:8000/openapi.json"
DATABASES = ("study_agent.db", "mastery.db")


def prepare() -> None:
    if sys.version_info < (3, 9):
        raise RuntimeError("需要 Python 3.9 或更新版本。")

    if not VENV_PYTHON.is_file():
        print("创建虚拟环境 .venv …", flush=True)
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], cwd=ROOT, check=True)

    fingerprint = hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()
    installed = FINGERPRINT.read_text(encoding="ascii").strip() if FINGERPRINT.exists() else ""
    if installed != fingerprint:
        print("安装 Python 依赖 …", flush=True)
        subprocess.run(
            [str(VENV_PYTHON), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
            cwd=ROOT,
            check=True,
        )
        FINGERPRINT.write_text(fingerprint + "\n", encoding="ascii")

    for name in DATABASES:
        source = ROOT / "demo-data" / name
        target = ROOT / name
        created = False
        try:
            with source.open("rb") as src, target.open("xb") as dst:
                created = True
                shutil.copyfileobj(src, dst)
            print(f"已从演示快照创建 {name}", flush=True)
        except FileExistsError:
            pass
        except Exception:
            if created:
                target.unlink()
            raise


def port_in_use() -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", 8000)) == 0


def ready() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=1) as response:
            paths = json.load(response).get("paths", {})
        return "/patterns" in paths and "/agent/context" in paths
    except (OSError, ValueError, urllib.error.URLError):
        return False


def start(open_browser: bool, smoke: bool = False) -> int:
    if port_in_use():
        raise RuntimeError("端口 8000 已被占用。请先停止占用该端口的程序。")

    process = subprocess.Popen(
        [str(VENV_PYTHON), "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT,
    )
    try:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"服务启动失败，退出码 {process.returncode}；请查看上方错误。")
            if ready():
                print(f"已启动：{URL}  （按 Ctrl+C 退出）", flush=True)
                if smoke:
                    return 0
                if open_browser:
                    webbrowser.open(URL)
                return process.wait()
            time.sleep(0.25)
        raise RuntimeError("服务启动超时；请查看上方错误和 logs/app.log。")
    except KeyboardInterrupt:
        return 0
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description="安装依赖、复制演示数据并启动学习助手")
    parser.add_argument("--prepare-only", action="store_true", help="仅准备环境和数据")
    parser.add_argument("--no-browser", action="store_true", help="启动时不打开浏览器")
    parser.add_argument("--smoke", action="store_true", help="启动后检查接口，再停止服务")
    args = parser.parse_args()
    try:
        prepare()
        if args.prepare_only:
            print("环境和数据已准备好。", flush=True)
            return 0
        return start(not args.no_browser and not args.smoke, smoke=args.smoke)
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f"启动失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
