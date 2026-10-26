#!/usr/bin/env bash
# Install an isolated, read-only math.150.chat release without touching demo.150.chat.
set -Eeuo pipefail
umask 077

BASE=/opt/study-agent-math-showcase
RELEASES=$BASE/releases
UNIT=study-agent-math-showcase
CADDY_SNIPPET=/etc/caddy/study-agent-math-showcase.caddy
UNIT_FILE=/etc/systemd/system/$UNIT.service
CADDYFILE=/etc/caddy/Caddyfile
ARCHIVE=${1:-}
EXPECTED_SHA=${2:-}
BACKUP=
STAGING=
RELEASE_DIR=
OLD_CURRENT=
OLD_ACTIVE=0
OLD_ENABLED=0
HAD_CADDYFILE=0
HAD_CADDY_SNIPPET=0
HAD_UNIT=0
TRANSACTION=0

die() { echo "$*" >&2; exit 2; }

if [[ $EUID -ne 0 ]]; then die '请在阿里云 Workbench 的 root 终端运行。'; fi
if [[ ${1:-} == --rollback ]]; then
    [[ $# -eq 2 ]] || die '用法：activate-math-showcase.sh --rollback <备份目录>'
    BACKUP_INPUT=$2
    command -v systemctl >/dev/null || die '找不到 systemctl 命令。'
    command -v caddy >/dev/null || die '找不到 caddy 命令。'
    ROLLBACK_BACKUP=$(readlink -f -- "$BACKUP_INPUT" 2>/dev/null || true)
    ROLLBACK_ROOT=$(readlink -f -- "$BASE/backups" 2>/dev/null || true)
    [[ -n $ROLLBACK_ROOT && $ROLLBACK_BACKUP == "$ROLLBACK_ROOT/"* && -d $ROLLBACK_BACKUP && ! -L $BACKUP_INPUT ]] || die '备份目录必须是本脚本在独立 math 站目录下生成的普通目录。'
    [[ -f $ROLLBACK_BACKUP/Caddyfile && -f $ROLLBACK_BACKUP/service.was-active && -f $ROLLBACK_BACKUP/service.was-enabled ]] || die '备份目录缺少完整快照。'
    [[ $(cat "$ROLLBACK_BACKUP/backup.type" 2>/dev/null || true) == math-showcase ]] || die '备份标记无效。'
    systemctl stop "$UNIT" >/dev/null 2>&1 || true
    cp -a "$ROLLBACK_BACKUP/Caddyfile" "$CADDYFILE"
    if [[ $(cat "$ROLLBACK_BACKUP/had-caddy-snippet" 2>/dev/null || true) == 1 ]]; then
        cp -a "$ROLLBACK_BACKUP/study-agent-math-showcase.caddy" "$CADDY_SNIPPET"
    else
        rm -f -- "$CADDY_SNIPPET"
    fi
    if [[ $(cat "$ROLLBACK_BACKUP/had-unit" 2>/dev/null || true) == 1 ]]; then
        cp -a "$ROLLBACK_BACKUP/study-agent-math-showcase.service" "$UNIT_FILE"
    else
        rm -f -- "$UNIT_FILE"
    fi
    if [[ -f $ROLLBACK_BACKUP/current ]]; then
        PRIOR_CURRENT=$(cat "$ROLLBACK_BACKUP/current")
        PRIOR_REAL=$(readlink -m -- "$PRIOR_CURRENT")
        [[ $PRIOR_REAL == "$RELEASES/"* && -d $PRIOR_REAL ]] || die '备份中的旧 current 不在 math 发布目录内。'
        ln -sfnT -- "$PRIOR_CURRENT" "$BASE/current"
    else
        rm -f -- "$BASE/current"
    fi
    systemctl daemon-reload
    caddy validate --config "$CADDYFILE"
    systemctl reload caddy
    if [[ $(cat "$ROLLBACK_BACKUP/service.was-enabled") == 1 ]]; then systemctl enable "$UNIT"; else systemctl disable "$UNIT" 2>/dev/null || true; fi
    if [[ $(cat "$ROLLBACK_BACKUP/service.was-active") == 1 ]]; then
        systemctl start "$UNIT"
        curl --noproxy '*' --max-time 5 -fsS http://127.0.0.1:8002/health >/dev/null || die '旧 math 服务恢复后健康检查未通过。'
    fi
    echo "已恢复 math.150.chat 配置快照：$ROLLBACK_BACKUP"
    echo 'demo.150.chat 与 study-agent 服务未由本脚本修改。'
    exit 0
fi
[[ $# -eq 2 ]] || die '用法：activate-math-showcase.sh <tar.gz路径> <SHA256>'
[[ $EXPECTED_SHA =~ ^[0-9a-fA-F]{64}$ ]] || die '第二个参数必须是 64 位 SHA256。'
[[ -f $ARCHIVE && ! -L $ARCHIVE ]] || die '发布包必须是普通文件，不能是符号链接。'
[[ -f $CADDYFILE ]] || die '找不到 /etc/caddy/Caddyfile；请先确认 Caddy 已部署。'
command -v caddy >/dev/null || die '找不到 caddy 命令。'
command -v systemctl >/dev/null || die '找不到 systemctl 命令。'
command -v curl >/dev/null || die '找不到 curl 命令。'

ACTUAL_SHA=$(sha256sum -- "$ARCHIVE" | awk '{print $1}')
[[ ${ACTUAL_SHA,,} == ${EXPECTED_SHA,,} ]] || die "发布包 SHA256 不匹配：实际为 $ACTUAL_SHA"
RELEASE_ID=${ACTUAL_SHA:0:16}

if [[ -e $BASE && ( ! -d $BASE || -L $BASE ) ]]; then die "$BASE 已存在且不是普通目录，停止以避免覆盖。"; fi
install -d -o root -g root -m 755 "$BASE" "$RELEASES"
install -d -o root -g root -m 700 "$BASE/backups"
if [[ -e $BASE/current && ! -L $BASE/current ]]; then die "$BASE/current 不是符号链接，停止以避免覆盖。"; fi
if [[ -L $BASE/current ]]; then
    OLD_CURRENT=$(readlink -- "$BASE/current")
    CURRENT_REAL=$(readlink -f -- "$BASE/current" || true)
    [[ $CURRENT_REAL == "$RELEASES/"* ]] || die "当前入口指向 $CURRENT_REAL，不属于独立 math 发布目录。"
fi
if systemctl is-active --quiet "$UNIT"; then OLD_ACTIVE=1; fi
if systemctl is-enabled --quiet "$UNIT" 2>/dev/null; then OLD_ENABLED=1; fi

if [[ -f $UNIT_FILE ]] && ! grep -Fq 'ExecStart=/usr/bin/python3 -m backend.math_showcase --host 127.0.0.1 --port 8002' "$UNIT_FILE"; then
    die "$UNIT_FILE 已存在且不是本展示站服务，停止以避免接管其他服务。"
fi
if [[ -f $CADDY_SNIPPET ]] && ! grep -Fq '# Separate vhost for math.150.chat.' "$CADDY_SNIPPET"; then
    die "$CADDY_SNIPPET 已存在且不是本展示站配置，停止以避免覆盖。"
fi
IMPORT_LINE="import $CADDY_SNIPPET"
IMPORT_COUNT=$(grep -Fxc "$IMPORT_LINE" "$CADDYFILE" || true)
(( IMPORT_COUNT <= 1 )) || die "Caddyfile 中 math 配置导入行重复，请先人工核对。"

STAGING=$(mktemp -d "$RELEASES/.candidate.XXXXXXXX")
chmod 700 "$STAGING"
python3 - "$ARCHIVE" "$STAGING" <<'PY'
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

archive, output = Path(sys.argv[1]), Path(sys.argv[2])
fonts = '''AMS-Regular Caligraphic-Bold Caligraphic-Regular Fraktur-Bold Fraktur-Regular Main-Bold Main-BoldItalic Main-Italic Main-Regular Math-BoldItalic Math-Italic SansSerif-Bold SansSerif-Italic SansSerif-Regular Script-Regular Size1-Regular Size2-Regular Size3-Regular Size4-Regular Typewriter-Regular'''.split()
allowed = {
    'backend/__init__.py', 'backend/math_showcase.py',
    'deploy/study-agent-math-showcase.service', 'deploy/study-agent-math-showcase.caddy',
    'frontend/math-showcase/index.html', 'frontend/math-showcase/topics.html',
    'frontend/math-showcase/math.css', 'frontend/math-showcase/math.js',
    'frontend/math-showcase/math-render.js', 'frontend/math-showcase/topics.js',
    'frontend/math-showcase/math-mark.svg', 'frontend/math-showcase/math-case.json',
    'frontend/math-showcase/math-topics.json',
    'frontend/math-showcase/assets/fudan-favicon.png',
    'frontend/math-showcase/assets/fudan-favicon-180.png',
    'frontend/vendor/katex/LICENSE',
    'frontend/vendor/katex/katex.min.css', 'frontend/vendor/katex/katex.min.js',
    'release.json',
}
allowed.update(f'frontend/vendor/katex/fonts/KaTeX_{name}.woff2' for name in fonts)
required = allowed | {'MANIFEST.sha256'}
seen = set()
size_sum = 0
try:
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if not members or len(members) > 64:
            raise ValueError('归档文件数量不符合白名单')
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or str(path) != member.name:
                raise ValueError(f'不安全的归档路径：{member.name}')
            if member.name not in required or member.name in seen:
                raise ValueError(f'归档含未知或重复文件：{member.name}')
            if not member.isfile() or member.size < 0 or member.size > 8 * 1024 * 1024:
                raise ValueError(f'归档含非普通文件或异常大小：{member.name}')
            size_sum += member.size
            if size_sum > 32 * 1024 * 1024:
                raise ValueError('归档解压后超过 32 MiB')
            seen.add(member.name)
        if seen != required:
            raise ValueError('归档文件清单不完整：' + ', '.join(sorted(required - seen)))
        for member in members:
            target = output.joinpath(*PurePosixPath(member.name).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            stream = bundle.extractfile(member)
            if stream is None:
                raise ValueError(f'无法读取归档文件：{member.name}')
            with target.open('xb') as handle:
                handle.write(stream.read())
            target.chmod(0o644)
except (OSError, tarfile.TarError, ValueError) as exc:
    raise SystemExit(f'发布包结构检查失败：{exc}')

manifest_path = output / 'MANIFEST.sha256'
manifest = {}
for line in manifest_path.read_text(encoding='utf-8').splitlines():
    digest, separator, name = line.partition('  ')
    path = PurePosixPath(name)
    if not separator or len(digest) != 64 or path.is_absolute() or '..' in path.parts or name in manifest:
        raise SystemExit('MANIFEST.sha256 格式无效。')
    manifest[name] = digest
if set(manifest) != allowed:
    raise SystemExit('MANIFEST.sha256 与文件白名单不一致。')
for name, expected in manifest.items():
    actual = hashlib.sha256((output / name).read_bytes()).hexdigest()
    if actual != expected:
        raise SystemExit(f'文件摘要不匹配：{name}')
metadata = json.loads((output / 'release.json').read_text(encoding='utf-8'))
if metadata.get('schema_version') != 1 or metadata.get('site') != 'math.150.chat':
    raise SystemExit('release.json 不是 math.150.chat 发布包。')
PY

RELEASE_DIR=$RELEASES/$RELEASE_ID
if [[ -e $RELEASE_DIR ]]; then
    if [[ $(readlink -f -- "$BASE/current" 2>/dev/null || true) == "$RELEASE_DIR" ]] && systemctl is-active --quiet "$UNIT"; then
        curl --noproxy '*' --max-time 5 -fsS http://127.0.0.1:8002/health
        rm -rf -- "$STAGING"
        STAGING=
        echo "math.150.chat 发布 $RELEASE_ID 已经处于运行状态。"
        exit 0
    fi
    die "发布目录 $RELEASE_DIR 已存在；为保护已有文件，本脚本不覆盖它。"
fi

if getent passwd studymath >/dev/null; then
    [[ $(getent passwd studymath | cut -d: -f7) == /usr/sbin/nologin ]] || die 'studymath 账号已存在且不是禁用登录的服务账号。'
    getent group studymath >/dev/null || die 'studymath 账号存在但缺少同名服务组。'
else
    getent group studymath >/dev/null && die 'studymath 同名组已存在但服务账号不存在，请先人工核对。'
    useradd --system --no-create-home --user-group --home-dir /nonexistent --shell /usr/sbin/nologin studymath
fi

BACKUP=$BASE/backups/$(date -u +%Y%m%dT%H%M%SZ)-$RELEASE_ID
install -d -o root -g root -m 700 "$BACKUP"
cp -a "$CADDYFILE" "$BACKUP/Caddyfile"
HAD_CADDYFILE=1
if [[ -e $CADDY_SNIPPET ]]; then cp -a "$CADDY_SNIPPET" "$BACKUP/study-agent-math-showcase.caddy"; HAD_CADDY_SNIPPET=1; fi
if [[ -e $UNIT_FILE ]]; then cp -a "$UNIT_FILE" "$BACKUP/study-agent-math-showcase.service"; HAD_UNIT=1; fi
if [[ -n $OLD_CURRENT ]]; then printf '%s\n' "$OLD_CURRENT" > "$BACKUP/current"; fi
printf '%s\n' "$OLD_ACTIVE" > "$BACKUP/service.was-active"
printf '%s\n' "$OLD_ENABLED" > "$BACKUP/service.was-enabled"
printf '%s\n' math-showcase > "$BACKUP/backup.type"
printf '%s\n' "$HAD_CADDY_SNIPPET" > "$BACKUP/had-caddy-snippet"
printf '%s\n' "$HAD_UNIT" > "$BACKUP/had-unit"

mv -- "$STAGING" "$RELEASE_DIR"
STAGING=
chown -R root:root "$RELEASE_DIR"
find "$RELEASE_DIR" -type d -exec chmod 755 {} +
find "$RELEASE_DIR" -type f -exec chmod 644 {} +

rollback() {
    local code=$?
    trap - EXIT
    if (( code != 0 && TRANSACTION == 1 )); then
        echo "切换失败，正在恢复 math.150.chat 入口。备份：$BACKUP" >&2
        systemctl stop "$UNIT" >/dev/null 2>&1 || true
        if [[ -n $OLD_CURRENT ]]; then ln -sfnT -- "$OLD_CURRENT" "$BASE/current"; else rm -f -- "$BASE/current"; fi
        if (( HAD_CADDYFILE == 1 )); then cp -a "$BACKUP/Caddyfile" "$CADDYFILE"; fi
        if (( HAD_CADDY_SNIPPET == 1 )); then cp -a "$BACKUP/study-agent-math-showcase.caddy" "$CADDY_SNIPPET"; else rm -f -- "$CADDY_SNIPPET"; fi
        if (( HAD_UNIT == 1 )); then cp -a "$BACKUP/study-agent-math-showcase.service" "$UNIT_FILE"; else rm -f -- "$UNIT_FILE"; fi
        systemctl daemon-reload >/dev/null 2>&1 || true
        if caddy validate --config "$CADDYFILE" >/dev/null 2>&1; then systemctl reload caddy >/dev/null 2>&1 || true; fi
        if (( OLD_ENABLED == 1 )); then systemctl enable "$UNIT" >/dev/null 2>&1 || true; else systemctl disable "$UNIT" >/dev/null 2>&1 || true; fi
        if (( OLD_ACTIVE == 1 )); then systemctl start "$UNIT" >/dev/null 2>&1 || true; fi
        echo '恢复尝试完成；请按 systemctl、journalctl 和 caddy validate 的结果核对服务。' >&2
    fi
    if [[ -n $STAGING && -d $STAGING ]]; then rm -rf -- "$STAGING"; fi
    exit "$code"
}
trap rollback EXIT
TRANSACTION=1

install -d -o root -g root -m 755 /etc/caddy /etc/systemd/system
install -m 644 "$RELEASE_DIR/deploy/study-agent-math-showcase.caddy" "$CADDY_SNIPPET"
install -m 644 "$RELEASE_DIR/deploy/study-agent-math-showcase.service" "$UNIT_FILE"
if (( IMPORT_COUNT == 0 )); then printf '\n%s\n' "$IMPORT_LINE" >> "$CADDYFILE"; fi
caddy validate --config "$CADDYFILE"
systemctl daemon-reload
ln -sfnT -- "$RELEASE_DIR" "$BASE/current"
systemctl enable --now "$UNIT"

ready=0
for _ in $(seq 1 30); do
    if curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:8002/health | python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("ok") is True and d.get("mode")=="math-showcase" and d.get("ai_enabled") is False else 1)'; then
        ready=1
        break
    fi
    sleep 1
done
if (( ready != 1 )); then journalctl -u "$UNIT" -n 40 --no-pager >&2; die 'math.150.chat 本机健康检查未通过。'; fi
curl --noproxy '*' --max-time 5 -fsS http://127.0.0.1:8002/ >/dev/null || die 'math.150.chat 首页本机检查未通过。'
caddy validate --config "$CADDYFILE"
systemctl reload caddy
TRANSACTION=0
trap - EXIT
echo "math.150.chat 已通过本机健康检查，发布目录：$RELEASE_DIR"
echo "旧 math 发布保存在 $BASE/releases/；部署回滚快照保存在 $BACKUP。"
echo '本脚本不会停止、重启或修改 study-agent-demo、study-agent，也不会开放 8002 到公网。'
