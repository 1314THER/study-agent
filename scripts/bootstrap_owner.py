"""Create/reset the reserved owner using a server terminal and hidden prompts."""

import argparse
from getpass import getpass
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="在服务器创建主人 studyadmin；不会修改原学习数据库")
    parser.add_argument("--root", type=Path, default=Path(os.environ.get("STUDY_AUTH_ROOT", str(ROOT / ".accounts"))))
    parser.add_argument("--owner-directory", type=Path, default=Path(os.environ.get("STUDY_OWNER_DATA_DIR") or os.environ.get("STUDY_AGENT_DATA_DIR") or str(ROOT)))
    parser.add_argument("--email", help="可选：主人登录邮箱")
    parser.add_argument("--set-api-key", action="store_true", help="通过隐藏输入设置主人的 DeepSeek API Key")
    parser.add_argument("--reset-password", action="store_true", help="重设已有主人密码，并撤销全部主人登录会话")
    parser.add_argument("--generate-key", action="store_true", help="生成新的加密密钥后退出；保存到服务器环境并安全备份")
    args = parser.parse_args()
    if args.generate_key:
        from cryptography.fernet import Fernet
        print(Fernet.generate_key().decode())
        return 0
    password = getpass("主人密码（12–128 个字符）：")
    if password != getpass("再次输入密码："):
        parser.error("两次密码不一致")
    api_key = getpass("DeepSeek API Key：") if args.set_api_key else None
    from backend.auth import AccountStore, AuthError
    try:
        if os.environ.get("STUDY_DATABASE_URL"):
            from backend.storage.database import Database
            from backend.storage.accounts import CloudAccountStore
            cloud_root = Path(os.environ.get("STUDY_CLOUD_ROOT") or ROOT / ".cloud")
            store = CloudAccountStore(Database(), cloud_root)
        else:
            store = AccountStore(args.root, args.owner_directory)
        store.bootstrap_owner(password, email=args.email, api_key=api_key, replace_password=args.reset_password)
    except (AuthError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print("主人 studyadmin 已配置。原题库未改动，密码和 API Key 不会回显。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
