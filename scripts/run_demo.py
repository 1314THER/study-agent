"""Preview the read-only project showcase on local HTTP port 8000."""

import argparse
import os
from pathlib import Path
import socket
import subprocess
import sys


ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="本地项目演示：预制交互样例，无需 AI 配置")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口需要在 1 到 65535 之间")
    with socket.socket() as check:
        check.settimeout(0.5)
        if check.connect_ex(("127.0.0.1", args.port)) == 0:
            raise SystemExit("端口已被占用，请先停止对应的本地服务，再运行项目预览。")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    executable = str(python) if python.is_file() else sys.executable
    print("项目预览：http://127.0.0.1:" + str(args.port) + "/home.html", flush=True)
    try:
        return subprocess.call([executable, "-m", "uvicorn", "backend.showcase:app", "--host", "127.0.0.1",
                                "--port", str(args.port), "--workers", "1"], cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
