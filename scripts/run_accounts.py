"""Run the three-entrance account application on local HTTP."""

import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description="启动账号/游客系统本地预览")
    parser.add_argument("--port", type=int, default=8002)
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("端口需要在 1 到 65535 之间")
    env = dict(os.environ)
    if not env.get("STUDY_AUTH_ENCRYPTION_KEY"):
        parser.error("请先配置 STUDY_AUTH_ENCRYPTION_KEY。用 python3 scripts/bootstrap_owner.py --generate-key 生成一次并安全保存。")
    env.update(STUDY_AUTH_ENABLED="1", STUDY_AUTH_COOKIE_SECURE="0", STUDY_AUTH_ORIGIN=f"http://127.0.0.1:{args.port}", PYTHONDONTWRITEBYTECODE="1")
    env.setdefault("STUDY_AUTH_ROOT", str(ROOT / ".accounts"))
    env.setdefault("STUDY_AGENT_LOG_DIR", str(Path(env["STUDY_AUTH_ROOT"]) / "logs"))
    print(f"账号系统：http://127.0.0.1:{args.port}/login.html", flush=True)
    try:
        return subprocess.call([sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(args.port), "--workers", "1"], cwd=str(ROOT), env=env)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
