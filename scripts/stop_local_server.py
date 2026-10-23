"""Stop this checkout's local Uvicorn backend without touching other services."""

import os
from pathlib import Path
import shlex
import signal
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent.parent
PID_FILE = ROOT / ".runtime" / "local-server.pid"
PORT = "8000"


def command_for(pid):
    result = subprocess.run(
        ["/bin/ps", "-p", str(pid), "-o", "command="],
        capture_output=True, text=True, check=False,
    )
    return result.stdout.strip()


def cwd_for(pid):
    result = subprocess.run(
        ["/usr/sbin/lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"],
        capture_output=True, text=True, check=False,
    )
    for line in result.stdout.splitlines():
        if line.startswith("n"):
            return Path(line[1:]).resolve()
    return None


def is_project_backend(pid):
    command = command_for(pid)
    if not command or cwd_for(pid) != ROOT:
        return False
    try:
        args = shlex.split(command)
    except ValueError:
        return False
    required = ("-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", PORT)
    return all(value in args for value in required)


def listening_pids():
    result = subprocess.run(
        ["/usr/sbin/lsof", "-nP", "-a", "-iTCP:" + PORT, "-sTCP:LISTEN", "-Fp"],
        capture_output=True, text=True, check=False,
    )
    pids = set()
    for line in result.stdout.splitlines():
        if line.startswith("p"):
            try:
                pids.add(int(line[1:]))
            except ValueError:
                pass
    return pids


def read_pid_file():
    try:
        value = PID_FILE.read_text(encoding="ascii").strip()
        return int(value)
    except (OSError, ValueError):
        return None


def stop(pid):
    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if not is_project_backend(pid):
            return
        time.sleep(0.25)

    # Recheck the command and checkout immediately before the forced stop.
    if is_project_backend(pid):
        os.kill(pid, signal.SIGKILL)
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline and is_project_backend(pid):
            time.sleep(0.1)
        if is_project_backend(pid):
            raise RuntimeError("服务进程仍在运行，请稍后重试。")


def main():
    recorded_pid = read_pid_file()
    candidates = set(listening_pids())
    if recorded_pid is not None:
        candidates.add(recorded_pid)

    owned = sorted(pid for pid in candidates if is_project_backend(pid))
    if not owned:
        if recorded_pid is not None:
            try:
                PID_FILE.unlink()
            except OSError:
                pass
        listeners = listening_pids()
        if listeners:
            print("8000 端口由其他服务占用；未停止任何进程。")
        else:
            print("本项目的本地后端当前未运行。")
        return

    print("正在关闭本项目后端（PID: " + ", ".join(map(str, owned)) + "）…")
    for pid in owned:
        try:
            stop(pid)
        except ProcessLookupError:
            pass

    if recorded_pid in owned:
        try:
            PID_FILE.unlink()
        except FileNotFoundError:
            pass

    remaining = [pid for pid in listening_pids() if is_project_backend(pid)]
    if remaining:
        raise RuntimeError("后端仍占用 8000 端口：" + ", ".join(map(str, remaining)))
    print("本项目后端已关闭。")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError) as exc:
        print("关闭失败：" + str(exc), file=sys.stderr)
        sys.exit(1)
