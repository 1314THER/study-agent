"""Start the isolated visitor experience on local HTTP port 8000."""

import argparse
import os
from pathlib import Path
import runpy
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="本地游客体验：独立题库、真实 AI 与体验引导")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口需要在 1 到 65535 之间")
    with socket.socket() as check:
        check.settimeout(0.5)
        if check.connect_ex(("127.0.0.1", args.port)) == 0:
            raise SystemExit("端口已被占用，请先停止对应的本地服务，再运行游客预览。")
    runtime = ROOT / ".demo-sessions"
    prepare = runpy.run_path(str(ROOT / "deploy" / "prepare-demo-ai.py"))["prepare"]
    config = prepare(ROOT, runtime / "private" / "ai-config.json")
    env = dict(os.environ)
    env.update({
        "STUDY_DEMO_ROOT": str(runtime),
        "STUDY_AGENT_LOG_DIR": str(runtime / "logs"),
        "STUDY_DEMO_AI_CONFIG": str(config),
        "STUDY_DEMO_AI_ENABLED": "1",
        "STUDY_DEMO_LOCAL_PREVIEW": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    executable = str(python) if python.is_file() else sys.executable
    print("游客预览：http://127.0.0.1:" + str(args.port) + "/home.html", flush=True)
    try:
        return subprocess.call([executable, "-m", "uvicorn", "backend.demo:app", "--host", "127.0.0.1",
                                "--port", str(args.port), "--workers", "1"], cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
