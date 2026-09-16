"""Desktop app entry: reuse a healthy server or start it without a terminal."""
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
STATE = Path.home() / 'Library' / 'Logs' / 'MathCoach'
BASE = 'http://127.0.0.1:8000'
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def ready():
    try:
        with HTTP.open(BASE + '/openapi.json', timeout=2) as response:
            paths = json.load(response).get('paths', {})
            return '/patterns' in paths and '/agent/context' in paths
    except Exception:
        return False


def main():
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'launcher.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not ready():
            with socket.socket() as sock:
                if sock.connect_ex(('127.0.0.1', 8000)) == 0:
                    raise RuntimeError('8000 端口已被其他服务占用，请关闭该服务后重试。')
            python = ROOT / '.venv' / 'bin' / 'python'
            if not python.exists():
                python = Path(sys.executable)
            env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
            with (STATE / 'server.log').open('ab') as log:
                child = subprocess.Popen(
                    [str(python), '-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', '8000'],
                    cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=log,
                    stderr=subprocess.STDOUT, start_new_session=True, env=env,
                )
            deadline = time.monotonic() + 45
            while not ready():
                if child.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError('启动失败，请查看日志：' + str(STATE / 'server.log'))
                time.sleep(0.3)
        subprocess.run(['/usr/bin/open', BASE + '/home.html?launch=1'], check=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
