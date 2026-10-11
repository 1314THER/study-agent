#!/usr/bin/env python3
"""Export a frozen routine-review prompt or import its manually obtained reply."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routine_review import get_store
from backend.routine_web_review import export_packet, import_packet


def main(argv=None):
    parser = argparse.ArgumentParser(description="网页手动复核套路匹配；不调用模型或浏览器")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--export", metavar="RUN_ID")
    action.add_argument("--import", dest="import_packet_id", metavar="PACKET_ID")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--response", type=Path, help="本地网页响应 JSON 文件")
    args = parser.parse_args(argv)
    store = get_store()  # Enforces the existing owner identity guard.
    runtime = ROOT / ".runtime"
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    if args.export:
        packet = export_packet(store, args.export, limit=args.limit)
        prompt_path = runtime / f"routine-web-{packet['packet_id']}.txt"
        metadata_path = runtime / f"routine-web-{packet['packet_id']}.json"
        prompt_path.write_text(packet["prompt"] + "\n", encoding="utf-8")
        metadata_path.write_text(json.dumps(packet["metadata"], ensure_ascii=False, indent=2) + "\n",
                                 encoding="utf-8")
        prompt_path.chmod(0o600)
        metadata_path.chmod(0o600)
        print(f"提示词：{prompt_path}\n元信息：{metadata_path}\n包编号：{packet['packet_id']}")
        return 0
    if args.response is None:
        parser.error("--import 必须同时提供 --response LOCAL_FILE")
    if not args.response.is_file():
        parser.error("响应文件不存在")
    result = import_packet(store, args.import_packet_id, args.response.read_text(encoding="utf-8"))
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
