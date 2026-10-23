"""Safe by default: import checks a bundle without writing unless --apply is used."""
import argparse
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from backend.storage.migration import snapshot, import_bundle, export_cloud, verify_import
from backend.storage.database import Database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--owner", required=True)
    snap.add_argument("--accounts")
    snap.add_argument("--output", required=True)
    load = sub.add_parser("import")
    load.add_argument("--bundle", required=True)
    load.add_argument("--asset-root", required=True)
    load.add_argument("--apply", action="store_true")
    export = sub.add_parser("export")
    export.add_argument("--output", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--bundle", required=True)
    verify.add_argument("--asset-root", required=True)
    args = parser.parse_args()
    if args.command == "snapshot":
        result = snapshot(args.owner, args.accounts, args.output)
        print(json.dumps({"databases": len(result["databases"]), "assets": len(result["assets"])}))
    elif args.command == "import":
        print(json.dumps(import_bundle(Database(), args.bundle, args.asset_root, apply=args.apply)))
    elif args.command == "verify":
        print(json.dumps(verify_import(Database(), args.bundle, args.asset_root)))
    else:
        export_cloud(Database(), args.output)
        print("Cloud export complete; back up the private asset directory separately.")


if __name__ == "__main__":
    main()
