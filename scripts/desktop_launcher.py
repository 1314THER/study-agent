"""Start one local backend and open the learning assistant on macOS."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / ".runtime"
LOG = ROOT / "logs" / "local-server.log"
PID_FILE = STATE / "local-server.pid"
BASE = "http://127.0.0.1:8000"
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ready():
    try:
        with HTTP.open(BASE + "/openapi.json", timeout=2) as response:
            paths = json.load(response).get("paths", {})
        return "/patterns" in paths and "/agent/context" in paths
    except (OSError, ValueError):
        return False


def port_in_use():
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", 8000)) == 0


def existing_server():
    """Only reuse a backend whose process belongs to this checkout."""
    output = subprocess.run(
        ["/usr/sbin/lsof", "-nP", "-a", "-iTCP:8000", "-sTCP:LISTEN", "-Fp"],
        capture_output=True, text=True, check=False,
    ).stdout
    pids = {int(line[1:]) for line in output.splitlines() if line.startswith("p")}
    if len(pids) != 1:
        raise RuntimeError("8000 端口已被其他服务占用，请关闭该服务后重试。")
    pid = pids.pop()
    cwd = subprocess.run(
        ["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        capture_output=True, text=True, check=False,
    ).stdout.splitlines()
    command = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "command="],
        capture_output=True, text=True, check=False,
    ).stdout.strip()
    if "n" + str(ROOT) not in cwd or " -m uvicorn backend.main:app " not in command:
        raise RuntimeError("8000 端口不是本项目的后台，请关闭占用该端口的服务后重试。")
    return pid


def server_env():
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["STUDY_LOCAL_CODEX"] = "1" if (ROOT / ".local-codex/provider.py").is_file() else "0"
    # Finder and Terminal may not inherit the app's bundled Codex CLI path.
    if not shutil.which("codex", path=env.get("PATH", "")):
        cli = Path("/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex")
        if cli.is_file() and os.access(cli, os.X_OK):
            env["PATH"] = str(cli.parent) + os.pathsep + env.get("PATH", os.defpath)
    return env


def start_server():
    python = ROOT / ".venv" / "bin" / "python"
    if not python.is_file():
        raise RuntimeError("本地 Python 环境缺失，请使用「一键打开.command」准备环境。")
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("ab") as log:
        child = subprocess.Popen(
            [str(python), "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8000"],
            cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True, env=server_env(),
        )
    return child


def main(open_browser=True):
    STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (STATE / "launcher.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        child = None
        if port_in_use():
            pid = existing_server()
        else:
            child = start_server()
            pid = child.pid
        try:
            deadline = time.monotonic() + 45
            while not ready():
                if child is not None and child.poll() is not None:
                    raise RuntimeError("启动失败，请查看日志：" + str(LOG))
                if time.monotonic() >= deadline:
                    raise RuntimeError("后台启动超时，请查看日志：" + str(LOG))
                time.sleep(0.3)
            if existing_server() != pid:
                raise RuntimeError("启动时端口发生变化，请重新打开。")
        except BaseException:
            if child is not None and child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()
            raise
        PID_FILE.write_text(str(pid) + "\n", encoding="ascii")
        url = BASE + "/home.html?launch=1"
        if open_browser:
            subprocess.run(["/usr/bin/open", url], check=True)
        print("学习系统已就绪：" + url)
        print("后台 PID：" + str(pid) + "；关闭此终端窗口后，服务仍会运行。")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="一键打开学习系统，重复打开复用同一个后台")
    parser.add_argument("--no-browser", action="store_true", help="仅启动后台，用于检查启动状态")
    args = parser.parse_args()
    try:
        main(open_browser=not args.no_browser)
    except Exception as exc:
        print("启动失败：" + str(exc), file=sys.stderr)
        sys.exit(1)
