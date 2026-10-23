"""Send locally collected JSONL candidates to the owner's cloud import API."""
import argparse
from getpass import getpass
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
import httpx


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", required=True)
    parser.add_argument("--file", type=Path, required=True)
    parser.add_argument("--kind", default="pool.pool_items")
    args = parser.parse_args()
    url = urlsplit(args.server)
    if url.scheme != "https" and not (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost", "::1")):
        parser.error("服务器须使用 HTTPS，本机 loopback 除外")
    if url.username or url.password or url.path not in ("", "/") or url.query or url.fragment:
        parser.error("请提供不含账号密码和路径的服务器根地址")
    with httpx.Client(base_url=args.server, follow_redirects=False, timeout=60) as client:
        response = client.post("/api/v1/auth/login", json={"login": "studyadmin", "password": getpass("主人密码："), "device_name": "题源导入命令"})
        response.raise_for_status()
        tokens = response.json()
        client.headers["Authorization"] = "Bearer " + tokens["access_token"]
        count = 0
        try:
            with args.file.open() as f:
                for line in f:
                    if not line.strip(): continue
                    record = json.loads(line)
                    external_id = str(record.get("fingerprint") or record.get("id") or hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False).encode()).hexdigest())
                    result = client.post("/api/v1/admin/records", json={"kind": args.kind, "external_id": external_id, "data": record})
                    result.raise_for_status(); count += 1
        finally:
            client.delete("/api/v1/auth/devices/" + tokens["device_session_id"]).raise_for_status()
    print(f"已导入或复用 {count} 条来源记录；发布仍需主人审核。")


if __name__ == "__main__": main()
