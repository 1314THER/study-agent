"""Start the shared API. --sqlite is a loopback-only development environment."""
import argparse
from getpass import getpass
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8003)
    parser.add_argument("--sqlite", action="store_true")
    parser.add_argument("--bootstrap-owner", action="store_true")
    args = parser.parse_args()
    from backend.auth import ROOT
    from backend.cloud_app import build_cloud_app
    from backend.storage.database import Database
    from backend.storage.accounts import CloudAccountStore
    root = Path(os.environ.get("STUDY_CLOUD_ROOT") or ROOT / ".cloud").resolve()
    if args.sqlite:
        if args.host not in ("127.0.0.1", "::1"):
            parser.error("--sqlite 仅允许在本机 loopback 调试")
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.environ["STUDY_DATABASE_URL"] = "sqlite:///" + str(root / "development.sqlite3")
        keyfile = root / "development.key"
        if not os.environ.get("STUDY_AUTH_ENCRYPTION_KEY"):
            from cryptography.fernet import Fernet
            if not keyfile.exists():
                with keyfile.open("xb") as f:
                    keyfile.chmod(0o600); f.write(Fernet.generate_key())
            os.environ["STUDY_AUTH_ENCRYPTION_KEY"] = keyfile.read_text().strip()
    elif not os.environ.get("STUDY_DATABASE_URL"):
        parser.error("请配置 STUDY_DATABASE_URL；生产库先运行 alembic upgrade head")
    db = Database()
    if args.sqlite:
        db.create_schema()
    store = CloudAccountStore(db, root)
    if args.bootstrap_owner:
        password = getpass("主人密码（至少 12 位）：")
        if password != getpass("再次输入密码："):
            parser.error("两次密码不一致")
        store.bootstrap_owner(password)
    app = build_cloud_app(database=db, root=root, store=store, secure_cookie=not args.sqlite,
        origin=f"http://127.0.0.1:{args.port}" if args.sqlite else None)
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port, workers=1)


if __name__ == "__main__": main()
