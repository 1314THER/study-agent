"""Build a demo-only working-tree snapshot; no SSH, downloads or owner files.

The generated activation script is intended for a reviewed, manual Workbench run.
Its fixed-layout checks deliberately refuse older/different service installations.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CHAPTERS = ['overview', 'concepts', 'dataset', 'single', 'diagnosis', 'library', 'routines',
            'exam', 'career', 'agent', 'teacher', 'school', 'modes', 'mcp', 'evolution']
EXAMPLES = {'national-2023-q17', 'national-2025-q16'}
TEACHERS = {'liangliang', 'taotao', 'xuefeng', 'ji'}
BACKEND = {'backend/__init__.py', 'backend/showcase.py', 'backend/showcase_bank.py'}
BANK_NAME = re.compile(r'^(?:index\.json|part-[0-9]{4}\.json|images/[0-9a-f]{64}\.png)$')
SECRET_KEYS = {'api_key', 'apikey', 'access_token', 'refresh_token', 'password',
               'authorization', 'cookie', 'private_key', 'secret_key'}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_name(name: str) -> str:
    path = PurePosixPath(name)
    if (not isinstance(name, str) or not name or path.is_absolute() or '\\' in name
            or '\x00' in name or path.as_posix() != name
            or any(part in ('.', '..') or part.startswith('.') for part in path.parts)):
        raise ValueError('Unsafe release path: ' + repr(name))
    return name


def checked_file(root: Path, name: str) -> Path:
    relative_name(name)
    path = root / name
    for parent in [root, *[root / Path(*PurePosixPath(name).parts[:i])
                           for i in range(1, len(PurePosixPath(name).parts) + 1)]]:
        if parent.is_symlink():
            raise ValueError('Symlink in public release: ' + name)
    if not path.is_file() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('Missing regular public file: ' + name)
    path.resolve().relative_to(root.resolve())
    return path


def public_paths(root: Path) -> set[str]:
    """Read the real server allowlist without importing business/application code."""
    source = checked_file(root, 'backend/showcase.py').read_text()
    tree = ast.parse(source)
    paths = None
    allowed = (ast.Expression, ast.Set, ast.Tuple, ast.List, ast.Constant, ast.BinOp,
               ast.Add, ast.GeneratorExp, ast.comprehension, ast.Name, ast.Load, ast.Store)
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'ASSET_PATHS'
                                                for t in node.targets):
            paths = set(ast.literal_eval(node.value))
        elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
              and isinstance(node.value.func, ast.Attribute)
              and isinstance(node.value.func.value, ast.Name)
              and node.value.func.value.id == 'ASSET_PATHS' and node.value.func.attr == 'update'):
            if paths is None or len(node.value.args) != 1 or node.value.keywords:
                raise ValueError('Unsupported public allowlist update')
            expression = ast.Expression(node.value.args[0])
            if any(not isinstance(part, allowed) for part in ast.walk(expression)):
                raise ValueError('Public allowlist is no longer a static expression')
            paths.update(eval(compile(expression, '<public-assets>', 'eval'), {'__builtins__': {}}, {}))
    if not paths or any(not isinstance(p, str) or not p.startswith('/') for p in paths):
        raise ValueError('Missing static ASSET_PATHS')
    result = BACKEND | {'frontend/showcase/index.html'} | {'frontend' + p for p in paths}
    bank_path = 'frontend/showcase/question-bank/manifest.json'
    bank = json.loads(checked_file(root, bank_path).read_text())
    if bank.get('version') != 1 or type(bank.get('count')) is not int or bank['count'] < 1:
        raise ValueError('Invalid public question-bank manifest')
    files = bank.get('files', {})
    if not isinstance(files, dict) or not files or len(files) > 10000:
        raise ValueError('Invalid public question-bank files')
    for name in files:
        if not BANK_NAME.fullmatch(name):
            raise ValueError('Unapproved bank asset: ' + name)
        result.add('frontend/showcase/question-bank/' + name)
    for name in result:
        relative_name(name)
        if name not in BACKEND and not name.startswith('frontend/'):
            raise ValueError('Non-public payload: ' + name)
        if Path(name).suffix.lower() in ('.db', '.sqlite', '.sqlite3', '.pem', '.key', '.env'):
            raise ValueError('Private file type in release: ' + name)
        checked_file(root, name)
    return result


def scan_public(name: str, content: bytes) -> None:
    if Path(name).suffix.lower() not in ('.py', '.html', '.js', '.css', '.json', '.svg', '.sh'):
        return
    text = content.decode('utf-8')
    if (re.search(r'sk-[A-Za-z0-9_-]{24,}', text)
            or re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', text)
            or re.search(r'(?i)\bBearer\s+[A-Za-z0-9._~-]{24,}', text)):
        raise ValueError('Credential-like value in public file: ' + name)
    if name.endswith('.json'):
        def walk(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.lower() in SECRET_KEYS:
                        raise ValueError('Credential field in public JSON: ' + name)
                    walk(item)
            elif isinstance(value, list):
                for item in value:
                    walk(item)
        walk(json.loads(text))


def validate_content(root: Path) -> None:
    read = lambda name: json.loads(checked_file(root, 'frontend/showcase/' + name).read_text())
    content = read('research-content.json')
    if [c.get('id') for c in content.get('chapters', [])] != CHAPTERS:
        raise ValueError('All 15 research chapters must exist in order')
    for chapter in content['chapters']:
        if not chapter.get('body') or not chapter.get('source_docs'):
            raise ValueError('Chapter body/source mapping missing: ' + chapter['id'])
    data, pipeline = read('data.json'), read('pipeline.json')
    if {e.get('id') for e in data.get('examples', [])} != EXAMPLES:
        raise ValueError('Only the two reviewed national-paper examples may be exported')
    if set(pipeline.get('examples', {})) != EXAMPLES:
        raise ValueError('Unexpected or missing national pipeline example')
    for example, runs in pipeline['examples'].items():
        if set(runs) != TEACHERS:
            raise ValueError('Four recorded teachers required: ' + example)
        for teacher, run in runs.items():
            result = run.get('answer_json', {})
            chunks = result.get('chunk_results', [])
            if (result.get('error') or result.get('formatter_fallback') or len(chunks) != 2
                    or not result.get('final_answer') or not run.get('run_at')):
                raise ValueError('Incomplete recorded mathematics: ' + example + '/' + teacher)
            for chunk in chunks:
                if not chunk.get('steps') or any(not s.get('standard_writing') or not s.get('detailed_writing')
                                                  for s in chunk['steps']):
                    raise ValueError('Missing mathematical step content')
            for stage in ('solver', 'verifier', 'formatter'):
                if not run.get('stages', {}).get(stage, {}).get('content'):
                    raise ValueError('Missing production stage output')
            # Some authorized recordings put the exact answers in chunk_results
            # and use a summary label at the top. Validate both saved answer fields.
            answer = re.sub(r'\s+', '', result['final_answer'] + ''.join(
                chunk.get('final_answer', '') for chunk in chunks)).replace('\\\\', '\\')
            if example == 'national-2023-q17' and not ('3\\sqrt{10}' in answer and '6' in answer):
                raise ValueError('Triangle final answer no longer matches the reviewed case')
            if example == 'national-2025-q16' and '7-(3m+7)(-2)^m' not in answer:
                raise ValueError('Sequence final answer no longer matches the reviewed case')
    recordings = read('recordings.json')
    cases = recordings.get('cases', [])
    if len(cases) != 6 or len({c.get('id') for c in cases}) != 6:
        raise ValueError('Six fixed comparison cases required')
    for case in cases:
        if case.get('constructed_student') is not True or case.get('example_id') not in EXAMPLES:
            raise ValueError('Comparison must use a constructed national-paper example')
        for condition in ('basic', 'same_information', 'system'):
            output = case.get(condition, {})
            if output.get('status') != 'recorded' or not output.get('content'):
                raise ValueError('Comparison output not recorded: ' + case['id'] + '/' + condition)
    teaching, generation = recordings.get('teaching', {}), recordings.get('generation', {})
    if teaching.get('status') != 'recorded' or len(teaching.get('frames', [])) < 3:
        raise ValueError('Recorded teaching frames missing')
    if generation.get('status') != 'recorded' or not isinstance(generation.get('structured'), dict):
        raise ValueError('Actual generation result missing; rejection results must also be preserved')
    bank_root = root / 'frontend/showcase/question-bank'
    bank = json.loads((bank_root / 'manifest.json').read_text())
    for name, entry in bank['files'].items():
        raw = checked_file(bank_root, name).read_bytes()
        if sha(raw) != entry.get('sha256') or len(raw) != entry.get('size'):
            raise ValueError('Public bank checksum mismatch: ' + name)
    index = json.loads((bank_root / 'index.json').read_text())
    if len(index) != bank['count'] or len(bank.get('parts', {})) != bank['count']:
        raise ValueError('Public bank item count mismatch')
    actual = {p.relative_to(bank_root).as_posix() for p in bank_root.rglob('*') if p.is_file()}
    if actual != set(bank['files']) | {'manifest.json'}:
        raise ValueError('Unlisted public bank files')


def verify_directory(root: Path) -> dict:
    if root.is_symlink():
        raise ValueError('Candidate root may not be a symlink')
    root = root.resolve()
    manifest = json.loads(checked_file(root, 'release.json').read_text())
    if (manifest.get('schema_version') != 1 or manifest.get('target') != 'study-agent-demo'
            or manifest.get('private_data_included') is not False
            or not re.fullmatch('[0-9a-f]{40}', manifest.get('git_head', ''))
            or not re.fullmatch(r'research-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}', manifest.get('release_id', ''))):
        raise ValueError('Invalid demo release metadata')
    expected = public_paths(root) | {'activate-demo.sh', 'verify-release.py'}
    if set(manifest.get('files', {})) != expected:
        raise ValueError('Manifest is not exactly the reviewed public allowlist')
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('Links or special files in candidate')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != expected | {'release.json'}:
        raise ValueError('Candidate contains unlisted or missing files')
    for name, entry in manifest['files'].items():
        raw = checked_file(root, name).read_bytes()
        if entry.get('sha256') != sha(raw) or entry.get('size') != len(raw):
            raise ValueError('Release file checksum mismatch: ' + name)
        scan_public(name, raw)
    validate_content(root)
    return manifest


def extract_archive(archive: Path, destination: Path) -> None:
    if destination.is_symlink() or not destination.is_dir() or any(destination.iterdir()):
        raise ValueError('Extraction destination must be an empty real directory')
    names, total = set(), 0
    with tarfile.open(archive, 'r:gz') as bundle:
        members = bundle.getmembers()
        if len(members) > 20000:
            raise ValueError('Too many archive entries')
        for entry in members:
            name = relative_name(entry.name)
            if name in names or not entry.isfile() or entry.size < 0:
                raise ValueError('Duplicate, linked or non-file archive entry')
            names.add(name)
            total += entry.size
            if total > 250 * 1024 * 1024:
                raise ValueError('Archive exceeds the reviewed size limit')
        for entry in members:
            path = destination / entry.name
            path.parent.mkdir(parents=True, exist_ok=True)
            with bundle.extractfile(entry) as source, path.open('xb') as output:
                shutil.copyfileobj(source, output)
            path.chmod(0o644)


ACTIVATE = r'''#!/usr/bin/env bash
# Reviewed demo-only update. No network install, owner unit or Caddy mutation.
set -Eeuo pipefail
umask 077
BASE=/opt/study-agent-demo
UNIT=study-agent-demo
PY=$BASE/.venv/bin/python
ARCHIVE=${1:-}
EXPECTED=${2:-}
CHECK_ONLY=${3:-}
STAGE= RELEASE= BACKUP= OLD= LINK=
DRAINED=0
STOPPED=0
SWITCHED=0
SUCCESS=0
[[ $EUID -eq 0 && -f $ARCHIVE && $EXPECTED =~ ^[0-9a-f]{64}$ && ( -z $CHECK_ONLY || $CHECK_ONLY == --check-only ) ]] || {
  echo '用法（root）：bash activate-demo.sh <发布包.tar.gz> <SHA256> [--check-only]' >&2; exit 2;
}
for command in python3 curl systemctl runuser flock realpath sha256sum find install cmp; do command -v "$command" >/dev/null; done
[[ $(sha256sum "$ARCHIVE" | cut -d' ' -f1) == "$EXPECTED" ]] || { echo '发布包 SHA256 不符。' >&2; exit 1; }
[[ -d $BASE/releases && -L $BASE/current && -x $PY ]] || { echo '不是已安装的独立 demo 布局，停止。' >&2; exit 1; }
OLD=$(realpath "$BASE/current")
[[ $OLD == "$BASE/releases/"* && -d $OLD && $OLD != *$'\n'* ]] || { echo 'current 未指向独立 demo releases，停止。' >&2; exit 1; }
[[ $(systemctl show "$UNIT" -p User --value) == studydemo && $(systemctl show "$UNIT" -p Group --value) == studydemo ]] || { echo 'demo 服务账号不匹配，停止。' >&2; exit 1; }
[[ $(systemctl show "$UNIT" -p WorkingDirectory --value) == "$BASE/current" ]] || { echo 'demo WorkingDirectory 不匹配，停止。' >&2; exit 1; }
EXEC=$(systemctl show "$UNIT" -p ExecStart --value)
printf '%s\n' "$EXEC" | python3 -c 'import re,shlex,sys; value=sys.stdin.read(); m=re.search(r"argv\[\]=(.*?)\s+;",value); expected=[sys.argv[1],"-m","uvicorn","backend.showcase:app","--host","127.0.0.1","--port","8001","--workers","1"]; raise SystemExit(0 if m and shlex.split(m.group(1))==expected else "demo ExecStart 不匹配，停止")' "$PY"
[[ -z $(systemctl show "$UNIT" -p DropInPaths --value) ]] || { echo 'demo 存在额外 unit override，先人工核对，停止。' >&2; exit 1; }
systemctl show "$UNIT" -p Environment --value | python3 -c 'import sys; value=sys.stdin.read(); raise SystemExit("存在外部题库路径覆盖，停止" if "STUDY_SHOWCASE_BANK_ROOT=" in value else 0)'
systemctl is-active --quiet "$UNIT" || { echo 'demo 当前未运行，先核实原服务，停止。' >&2; exit 1; }
exec 9>"$BASE/.research-release.lock"
flock -n 9 || { echo '另一 demo 发布正在运行。' >&2; exit 1; }
if [[ -f /opt/study-agent-sync/sync.lock ]]; then exec 8</opt/study-agent-sync/sync.lock; flock -n 8 || { echo '双站同步正在运行，请稍后。' >&2; exit 1; }; fi
health() {
  curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS "$1" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("ok") is True and d.get("mode")=="demo" and d.get("demo_mode")=="showcase" and d.get("ai_enabled") is False else 1)'
}
restore() {
  local code=$?
  trap - EXIT INT TERM
  if (( SUCCESS == 0 )); then
    if (( SWITCHED == 1 || STOPPED == 1 )); then
      systemctl stop "$UNIT" || true
      LINK="$BASE/.research-restore.$$"
      if ! { ln -s "$OLD" "$LINK" && mv -Tf "$LINK" "$BASE/current"; }; then
        echo "旧 demo 入口恢复失败，需人工处理；备份：$BACKUP" >&2
        exit "$code"
      fi
      if systemctl start "$UNIT"; then
        local restored=0
        for _ in {1..20}; do if health http://127.0.0.1:8001/health >/dev/null 2>&1; then restored=1; break; fi; sleep 1; done
        if (( restored )); then echo "发布失败，已恢复旧 demo：$OLD" >&2; else echo "旧 demo 健康检查失败，需人工处理；备份：$BACKUP" >&2; fi
      else echo "旧 demo 启动失败，需人工处理；备份：$BACKUP" >&2; fi
    elif (( DRAINED )); then
      curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS -H 'Content-Type: application/json' -d '{"draining":false}' http://127.0.0.1:8001/_internal/deploy-drain >/dev/null || echo '无法退出 demo drain，请人工核对。' >&2
    fi
  fi
  [[ -z $LINK || ! -L $LINK ]] || rm -f -- "$LINK"
  if [[ -n $STAGE && $STAGE == "$BASE/releases/.research-staging."* && -d $STAGE ]]; then rm -rf -- "$STAGE"; fi
  exit "$code"
}
trap restore EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
STAGE=$(mktemp -d "$BASE/releases/.research-staging.XXXXXXXX")
# Parse tar entries first; never use tar extractall or accept links/traversal.
python3 - "$ARCHIVE" "$STAGE" <<'PY'
from pathlib import Path,PurePosixPath
import sys,tarfile,shutil
root=Path(sys.argv[2]); names=set(); size=0
with tarfile.open(sys.argv[1],'r:gz') as tar:
 entries=tar.getmembers()
 if len(entries)>20000: raise SystemExit('发布包文件过多')
 for e in entries:
  p=PurePosixPath(e.name)
  if (not e.isfile() or e.size<0 or e.name in names or p.is_absolute() or p.as_posix()!=e.name or '\\' in e.name or any(x in ('.','..') or x.startswith('.') for x in p.parts)): raise SystemExit('发布包路径或文件类型无效')
  names.add(e.name);size+=e.size
  if size>250*1024*1024: raise SystemExit('发布包过大')
 for e in entries:
  p=root/e.name;p.parent.mkdir(parents=True,exist_ok=True)
  with tar.extractfile(e) as source,p.open('xb') as output: shutil.copyfileobj(source,output)
PY
python3 "$STAGE/verify-release.py" --verify-directory "$STAGE" >/dev/null
[[ $(sha256sum "$0" | cut -d' ' -f1) == $(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["files"]["activate-demo.sh"]["sha256"])' "$STAGE/release.json") ]] || { echo '激活脚本与包内清单不同，停止。' >&2; exit 1; }
ID=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["release_id"])' "$STAGE/release.json")
RELEASE="$BASE/releases/$ID"
if [[ -e $RELEASE || -L $RELEASE ]]; then
  [[ -d $RELEASE && ! -L $RELEASE ]] || { echo '候选路径不是独立目录，停止。' >&2; exit 1; }
  python3 "$RELEASE/verify-release.py" --verify-directory "$RELEASE" >/dev/null
  cmp -s "$STAGE/release.json" "$RELEASE/release.json" || { echo '候选目录内容与本包不同，停止。' >&2; exit 1; }
  rm -rf -- "$STAGE"
  STAGE=
else
  find "$STAGE" -type d -exec chmod 755 {} +
  find "$STAGE" -type f -exec chmod 644 {} +
  mv -- "$STAGE" "$RELEASE"
  STAGE=
fi
runuser -u studydemo -- env PYTHONDONTWRITEBYTECODE=1 "$PY" -c 'import os,sys; root=os.path.realpath(sys.argv[1]); os.chdir(root); sys.path.insert(0,root); import fastapi,uvicorn,backend; assert os.path.realpath(backend.__file__)==root+"/backend/__init__.py"; from backend.showcase import app,ASSET_PATHS; from backend.showcase_bank import verify; print("demo imports OK")' "$RELEASE"
runuser -u studydemo -- "$PY" "$RELEASE/verify-release.py" --verify-directory "$RELEASE" >/dev/null
if [[ $CHECK_ONLY == --check-only ]]; then SUCCESS=1; echo "候选验证通过，未停站或切换：$RELEASE"; exit 0; fi
if [[ $OLD == "$RELEASE" ]]; then health http://127.0.0.1:8001/health >/dev/null; health https://demo.150.chat/health >/dev/null; SUCCESS=1; echo "本包已激活且健康：$RELEASE"; exit 0; fi
BACKUP="$BASE/backups/$ID"
[[ ! -e $BACKUP ]] || { echo '备份目录已存在，停止。' >&2; exit 1; }
install -d -m 700 "$BASE/backups" "$BACKUP"
printf '%s\n' "$OLD" >"$BACKUP/previous-current.txt"
cp -- "$RELEASE/release.json" "$BACKUP/new-release.json"
python3 "$RELEASE/verify-release.py" --backup-public "$OLD" --output "$BACKUP/previous-public.tar.gz" >/dev/null
DRAINED=1
curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS -H 'Content-Type: application/json' -d '{"draining":true}' http://127.0.0.1:8001/_internal/deploy-drain >/dev/null
idle=0
for _ in {1..30}; do
 if curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS http://127.0.0.1:8001/_internal/deploy-status | "$PY" -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("mode")=="demo" and d.get("demo_mode")=="showcase" and d.get("draining") is True and d.get("active_requests")==0 and d.get("active_jobs")==0 else 1)'; then idle=1; break; fi
 sleep 1
done
(( idle )) || { echo 'demo 尚有活动请求，未停站。' >&2; exit 1; }
STOPPED=1
systemctl stop "$UNIT"
LINK="$BASE/.research-current.$$"
ln -s "$RELEASE" "$LINK"
mv -Tf "$LINK" "$BASE/current"
LINK=
SWITCHED=1
systemctl start "$UNIT"
ready=0
for _ in {1..30}; do if health http://127.0.0.1:8001/health >/dev/null 2>&1; then ready=1; break; fi; sleep 1; done
(( ready )) || { echo '新 demo 本地健康检查失败。' >&2; exit 1; }
curl --noproxy '*' --connect-timeout 2 --max-time 8 -fsS http://127.0.0.1:8001/home.html -o "$BACKUP/served-home.html"
[[ $(sha256sum "$BACKUP/served-home.html" | cut -d' ' -f1) == $(sha256sum "$RELEASE/frontend/showcase/index.html" | cut -d' ' -f1) ]] || { echo 'demo 首页不是本次快照。' >&2; exit 1; }
health https://demo.150.chat/health >/dev/null
SUCCESS=1
echo "demo 发布完成：$RELEASE"
echo "旧版本及备份：$OLD；$BACKUP"
echo '未修改正式站服务、数据库、配置、Caddy 或 Python 依赖。'
'''


def build(destination: Path, root: Path = ROOT) -> dict:
    root = root.resolve()
    selected = public_paths(root)
    validate_content(root)
    commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True).strip()
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('A real local Git HEAD is required')
    status = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain', '--',
                                      *sorted(selected)], text=True)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='study-demo-release-') as temporary:
        stage = Path(temporary)
        for name in sorted(selected):
            raw = checked_file(root, name).read_bytes()
            scan_public(name, raw)
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (stage / 'activate-demo.sh').write_text(ACTIVATE)
        (stage / 'verify-release.py').write_bytes(Path(__file__).read_bytes())
        files = {p.relative_to(stage).as_posix(): {'sha256': sha(p.read_bytes()), 'size': p.stat().st_size}
                 for p in sorted(stage.rglob('*')) if p.is_file()}
        digest = sha(json.dumps(files, sort_keys=True, separators=(',', ':')).encode())
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        identifier = 'research-' + stamp + '-' + digest[:12]
        manifest = {'schema_version': 1, 'target': 'study-agent-demo', 'release_id': identifier,
                    'git_head': commit, 'snapshot_kind': 'working_tree_files',
                    'includes_uncommitted_files': bool(status.strip()),
                    'private_data_included': False, 'dependencies_included': False,
                    'files_fingerprint': digest, 'files': files}
        (stage / 'release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        verify_directory(stage)
        subprocess.run(['bash', '-n', str(stage / 'activate-demo.sh')], check=True)
        archive = destination / (identifier + '.tar.gz')
        if archive.exists():
            raise ValueError('Release archive already exists')
        with tarfile.open(archive, 'w:gz') as bundle:
            for path in sorted(stage.rglob('*')):
                if path.is_file():
                    entry = bundle.gettarinfo(str(path), arcname=path.relative_to(stage).as_posix())
                    entry.uid = entry.gid = 0
                    entry.uname = entry.gname = ''
                    entry.mode = 0o644
                    with path.open('rb') as stream:
                        bundle.addfile(entry, stream)
        archive.chmod(0o600)
        activate = destination / 'activate-demo.sh'
        activate.write_text(ACTIVATE)
        activate.chmod(0o600)
        checksum = sha(archive.read_bytes())
        archive.with_suffix(archive.suffix + '.sha256').write_text(checksum + '  ' + archive.name + '\n')
        (destination / 'SHA256SUMS').write_text(checksum + '  ' + archive.name + '\n'
                                               + sha(activate.read_bytes()) + '  activate-demo.sh\n')
        (destination / 'release.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
        return {'archive': str(archive), 'sha256': checksum, 'release_id': identifier,
                'git_head': commit, 'includes_uncommitted_files': manifest['includes_uncommitted_files'],
                'public_file_count': len(selected), 'size_mib': round(archive.stat().st_size / 1024 ** 2, 2)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--verify-directory', type=Path)
    modes.add_argument('--backup-public', type=Path)
    modes.add_argument('--extract-archive', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / '.runtime/research-showcase-release')
    args = parser.parse_args()
    try:
        if args.verify_directory:
            data = verify_directory(args.verify_directory)
            print(json.dumps({'ok': True, 'release_id': data['release_id']}, ensure_ascii=False))
        elif args.backup_public:
            selected = public_paths(args.backup_public)
            with tarfile.open(args.output, 'x:gz') as tar:
                for name in sorted(selected):
                    path = checked_file(args.backup_public, name)
                    scan_public(name, path.read_bytes())
                    tar.add(path, arcname=name, recursive=False)
            args.output.chmod(0o600)
        elif args.extract_archive:
            extract_archive(args.extract_archive, args.output)
            print(json.dumps({'ok': True, 'extracted_to': str(args.output)}))
        else:
            print(json.dumps(build(args.output), ensure_ascii=False, indent=2))
    except (ValueError, OSError, subprocess.CalledProcessError, tarfile.TarError) as error:
        raise SystemExit(str(error)) from None


if __name__ == '__main__':
    main()
