#!/usr/bin/env bash
# Launch from a checksum-verified offline package, without contacting GitHub.
set -Eeuo pipefail
umask 077
[[ $EUID == 0 ]] || { echo '请在服务器 root 终端执行。' >&2; exit 2; }
sync_commit=${1:-}
[[ $sync_commit =~ ^[0-9a-f]{40}$ ]] || { echo '需要完整的 40 位发布 SHA。' >&2; exit 2; }
shift
package_dir=$(cd -- "$(dirname -- "$0")" && pwd -P)
cd "$package_dir"
sha256sum --strict --check SHA256SUMS
if [[ -f release.json ]]; then
    require_import=$(python3 - <<'PY'
import json
with open('release.json', encoding='utf-8') as stream:
    release = json.load(stream)
flag = release.get('require_question_import', False)
if type(flag) is not bool:
    raise SystemExit('离线发布的题库前置条件无效。')
print('1' if flag else '0')
PY
)
    if [[ $require_import == 1 ]]; then
        export STUDY_SYNC_REQUIRE_QUESTION_IMPORT=1
        echo '本次展示版发布会先核验原题池与审核数据是否已导入。'
    fi
fi
[[ -f release.bundle && ! -L release.bundle && -f sync-sites.sh && ! -L sync-sites.sh ]] || { echo '离线包文件不完整。' >&2; exit 1; }
if [[ -e wheelhouse || -L wheelhouse ]]; then
    [[ -d wheelhouse && ! -L wheelhouse ]] || { echo '离线依赖目录不可用。' >&2; exit 1; }
fi
bash -n sync-sites.sh
sync_workspace=$(mktemp -d /var/tmp/study-agent-offline.XXXXXXXX)
trap 'rm -rf -- "$sync_workspace"' EXIT
chown root:studyagent "$sync_workspace"
chmod 750 "$sync_workspace"
install -o root -g studyagent -m 640 release.bundle "$sync_workspace/release.bundle"
install -o root -g root -m 700 sync-sites.sh "$sync_workspace/sync-sites.sh"
if [[ -d wheelhouse ]]; then
    # This package's native wheels target the ECS runtime reported in the log.
    /opt/study-agent/.venv/bin/python - <<'PY'
import platform, sys, sysconfig
if sys.version_info[:2]!=(3,14) or platform.system()!='Linux' or platform.machine()!='x86_64' or sysconfig.get_config_var('Py_GIL_DISABLED'):
    raise SystemExit('该依赖包只适用于 Linux x86_64 的标准 Python 3.14，请按实际服务器环境重新制作。')
libc, version = platform.libc_ver()
if libc != 'glibc' or tuple(map(int, version.split('.')[:2])) < (2, 28):
    raise SystemExit('该依赖包需要 glibc 2.28 或以上，请按实际服务器环境重新制作。')
PY
    install -d -o root -g studyagent -m 750 "$sync_workspace/wheelhouse"
    for wheel in wheelhouse/*.whl; do
        [[ -f $wheel && ! -L $wheel ]] || { echo '离线 wheel 文件无效。' >&2; exit 1; }
        install -o root -g studyagent -m 640 "$wheel" "$sync_workspace/wheelhouse/"
    done
    STUDY_SYNC_WHEELHOUSE="$sync_workspace/wheelhouse" STUDY_SYNC_BUNDLE="$sync_workspace/release.bundle" \
        /bin/bash "$sync_workspace/sync-sites.sh" "$sync_commit" "$@"
else
    STUDY_SYNC_BUNDLE="$sync_workspace/release.bundle" /bin/bash "$sync_workspace/sync-sites.sh" "$sync_commit" "$@"
fi
