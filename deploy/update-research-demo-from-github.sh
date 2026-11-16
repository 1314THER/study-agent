#!/usr/bin/env bash
# Fetch a pinned GitHub commit into an isolated directory and update only Demo.
set -Eeuo pipefail
umask 077

TARGET_COMMIT=${1:-721bf863c4b23b57669b8dabad04c826b6d69c5a}
CHECK_ONLY=${2:-}
REPOSITORY=https://github.com/1314THER/study-agent.git
DEMO_ROOT=/opt/study-agent-demo
DEMO_PYTHON=$DEMO_ROOT/.venv/bin/python

fail() { echo "错误：$*" >&2; exit 1; }
[[ $EUID -eq 0 ]] || fail '请在服务器 root 终端运行。'
[[ $# -le 2 && $TARGET_COMMIT =~ ^[0-9a-f]{40}$ ]] || fail '需要完整的 40 位 Git 提交 SHA。'
[[ -z $CHECK_ONLY || $CHECK_ONLY == --check-only ]] || fail '第二个参数仅接受 --check-only。'
for tool in git python3 timeout flock systemctl curl runuser realpath sha256sum; do
  command -v "$tool" >/dev/null || fail "缺少命令：$tool"
done
[[ -d $DEMO_ROOT/releases && -L $DEMO_ROOT/current && -x $DEMO_PYTHON ]] \
  || fail '现有 Demo 不是 /opt/study-agent-demo/{current,releases,.venv} 布局；请先核对，不自动改装服务。'
systemctl is-active --quiet study-agent-demo || fail 'Demo 服务当前未运行，请先核对服务状态。'

install -d -m 0700 /root/study-agent-demo-updates
exec 8>/root/study-agent-demo-updates/github-update.lock
flock -n 8 || fail '另一个 GitHub Demo 更新正在运行。'
WORK_DIR=$(mktemp -d /root/study-agent-demo-updates/update-XXXXXXXX)
SOURCE_DIR=$WORK_DIR/source
OUTPUT_DIR=$WORK_DIR/release
echo "独立拉取目录：$WORK_DIR"
echo "目标 GitHub 提交：$TARGET_COMMIT"
git init -q "$SOURCE_DIR"
git -C "$SOURCE_DIR" remote add origin "$REPOSITORY"
timeout 300 git -C "$SOURCE_DIR" -c http.lowSpeedLimit=1000 -c http.lowSpeedTime=30 \
  fetch --no-tags --depth=1 origin "$TARGET_COMMIT"
git -C "$SOURCE_DIR" checkout -q --detach FETCH_HEAD
[[ $(git -C "$SOURCE_DIR" rev-parse HEAD) == "$TARGET_COMMIT" ]] || fail 'GitHub 拉取版本与目标不一致。'

python3 "$SOURCE_DIR/scripts/build_research_release.py" --output "$OUTPUT_DIR"
read -r ARCHIVE_NAME EXPECTED_SHA RELEASE_ID < <(python3 - "$OUTPUT_DIR" "$TARGET_COMMIT" <<'PY'
import json,re,sys
from pathlib import Path
root=Path(sys.argv[1]); meta=json.loads((root/'release.json').read_text())
assert meta['git_head']==sys.argv[2] and not meta['includes_uncommitted_files']
identifier=meta['release_id']; assert re.fullmatch(r'research-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}',identifier)
name=identifier+'.tar.gz'
parts=(root/(name+'.sha256')).read_text().split()
assert len(parts)==2 and parts[1]==name and re.fullmatch('[0-9a-f]{64}',parts[0])
print(name,parts[0],identifier)
PY
)
[[ -n $ARCHIVE_NAME && -n $EXPECTED_SHA && -n $RELEASE_ID ]] || fail '无法读取本次发布清单。'
(cd "$OUTPUT_DIR" && sha256sum -c SHA256SUMS)
bash -n "$OUTPUT_DIR/activate-demo.sh"
bash "$OUTPUT_DIR/activate-demo.sh" "$OUTPUT_DIR/$ARCHIVE_NAME" "$EXPECTED_SHA" --check-only
if [[ $CHECK_ONLY == --check-only ]]; then
  echo "候选已通过校验，未切换 Demo：$RELEASE_ID"
  exit 0
fi
bash "$OUTPUT_DIR/activate-demo.sh" "$OUTPUT_DIR/$ARCHIVE_NAME" "$EXPECTED_SHA"
echo "已从 GitHub 更新 Demo：$TARGET_COMMIT / $RELEASE_ID"
echo '访问：https://demo.150.chat/'
