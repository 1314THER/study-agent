#!/usr/bin/env bash
set -Eeuo pipefail

DEMO_SOURCE=/root/study-agent-demo-source-$(date +%Y%m%d-%H%M%S)
DEMO_OUTPUT=/root/study-agent-demo-release-$(date +%Y%m%d-%H%M%S)

clone_repo() {
git clone --depth 1 --single-branch --branch codex/wenxia-reviewer-demo \
-c http.version=HTTP/1.1 -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=45 \
https://github.com/1314THER/study-agent.git "$DEMO_SOURCE"
}

clone_ok=0
for attempt in 1 2 3 4 5; do
echo "== GitHub 拉取尝试 $attempt/5 =="
if clone_repo; then clone_ok=1; break; fi
rm -rf "$DEMO_SOURCE"
if [ "$attempt" -lt 5 ]; then echo "失败，20 秒后重试..."; sleep 20; fi
done
[ "$clone_ok" = 1 ] || { echo "连续 5 次拉取失败，请稍后再跑。"; exit 1; }

cd "$DEMO_SOURCE"
[ -f frontend/showcase/handwriting.js ] || { echo "GitHub 未包含最新版。"; exit 1; }

mkdir -p "$DEMO_OUTPUT"
python3 -B scripts/build_research_release.py --output "$DEMO_OUTPUT"

cd "$DEMO_OUTPUT"
sha256sum -c SHA256SUMS
release_id=$(python3 -c 'import json; print(json.load(open("release.json"))["release_id"])')
DEMO_PACKAGE="$DEMO_OUTPUT/$release_id.tar.gz"
DEMO_SHA=$(sha256sum "$DEMO_PACKAGE" | cut -d' ' -f1)

bash activate-demo.sh "$DEMO_PACKAGE" "$DEMO_SHA" --check-only
bash activate-demo.sh "$DEMO_PACKAGE" "$DEMO_SHA"

curl -fsS https://demo.150.chat/health && echo " -- demo 健康检查通过"
