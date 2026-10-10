"""Snapshot the owner's AI connection into a private, read-only demo config.

This script prints only provider availability; never keys or config contents.
"""

import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile


def prepare(source, output):
    source = Path(source).resolve()
    output = Path(output).resolve()
    sys.path.insert(0, str(source))
    # Read owner defaults/settings/.env, rather than a visitor workspace override.
    for name in ("STUDY_DEMO_AI_CONFIG", "STUDY_AGENT_DATA_DIR"):
        os.environ.pop(name, None)
    import backend.settings as settings
    api = deepcopy(settings.get_api())
    for provider in ("deepseek",):
        api[provider]["api_key"] = settings.get_api_key(provider)
    config = {"api": api, "teachers": deepcopy(settings.get_teachers()),
              "limits": deepcopy(settings.get_limits())}
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, staging = tempfile.mkstemp(prefix=".ai-config-", dir=str(output.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(config, stream, ensure_ascii=False, indent=2)
        os.chmod(staging, 0o600)
        os.replace(staging, output)
    finally:
        if os.path.exists(staging):
            os.unlink(staging)
    for provider in ("deepseek",):
        print(provider + " AI 配置：" + ("已就绪" if api[provider].get("api_key") else "尚未配置密钥"), flush=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    prepare(args.source, args.output)
