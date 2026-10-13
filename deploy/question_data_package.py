"""Private question-pool transfer; never manages accounts or application settings."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sqlite3
import stat
import tempfile

DATABASES = ('.runtime/question_pool.db', '.runtime/routine-review.sqlite3')
PREFIXES = ('.runtime/question-pool/files/', '.runtime/question-pool/sources/',
            '.runtime/question-pool/collections/', '.runtime/question-pool/conversion-cache/')
STATE_FILES = ('.runtime/routine-matching/state.json', '.runtime/routine-matching/graph.json')
MANIFEST = 'question-data-manifest.json'
LEDGER = 'data-import-backup.json'
DRIVERS = ('import-question-data.sh', 'question_data_merge.py', 'question_data_package.py')
COMMIT = 'c9a8d378d01ef2599d6a45680956379e805c0055'


def safe_path(root, relative):
    parts = PurePosixPath(relative)
    if not relative or parts.is_absolute() or '\\' in relative or relative != parts.as_posix() or any(p in ('.', '..') for p in parts.parts):
        raise ValueError('数据包包含无效路径')
    path = Path(root)
    if path.is_symlink():
        raise ValueError('数据根目录不能是符号链接')
    for part in parts.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError('数据路径包含链接：' + relative)
    return path


def allowed(relative):
    if relative in DATABASES or relative in STATE_FILES:
        return True
    if re.fullmatch(r'\.runtime/question-assets/[0-9a-f]{64}\.png', relative):
        return True
    return relative.startswith(PREFIXES) and not any(p in ('.git', '.env', '.accounts', '.codex') for p in PurePosixPath(relative).parts)


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('数据包包含链接或特殊文件：' + path.name)


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def database_copy(source, target):
    regular(source)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with closing(sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True)) as original, closing(sqlite3.connect(target)) as saved:
        original.backup(saved)
        saved.execute('PRAGMA journal_mode=DELETE')
        saved.commit()
    target.chmod(0o600)
    database_check(target)


def database_check(path):
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('数据库完整性校验失败：' + path.name)
        if db.execute('PRAGMA foreign_key_check').fetchone() is not None:
            raise ValueError('数据库引用校验失败：' + path.name)


def counts(root):
    with closing(sqlite3.connect(safe_path(root, DATABASES[0]).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        result = {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                  for table in ('pool_items', 'pool_sources', 'pool_occurrences')}
        if db.execute('SELECT COUNT(*) FROM pool_items WHERE formal_question_id IS NOT NULL').fetchone()[0] or db.execute('SELECT COUNT(*) FROM pool_commits').fetchone()[0]:
            raise ValueError('题池含正式题库引用，需要另行迁移正式题库；本工具不会更改学习数据库')
    with closing(sqlite3.connect(safe_path(root, DATABASES[1]).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        result['review_runs'] = db.execute('SELECT COUNT(*) FROM review_runs').fetchone()[0]
        result['review_items'] = db.execute('SELECT COUNT(*) FROM review_items').fetchone()[0]
    return result


def write_json(path, value):
    temporary = path.with_name(path.name + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    temporary.chmod(0o600)
    temporary.replace(path)


def export(source, destination, required_files):
    source, destination = Path(source).resolve(), Path(destination).absolute()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError('导出目录必须为空')
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    files = {}
    for relative in DATABASES:
        database_copy(safe_path(source, relative), safe_path(destination, relative))
    # Worker PIDs and job IDs are local process state, not portable review data.
    with closing(sqlite3.connect(destination / DATABASES[1])) as db:
        db.execute('UPDATE review_runs SET worker_pid=NULL,job_id=NULL')
        db.execute("UPDATE review_runs SET status='interrupted',stop=1,reason='已迁移审核快照，可按需继续' WHERE status IN ('running','queued')")
        db.commit()
    for relative in sorted(set(required_files) | {name for name in STATE_FILES if safe_path(source, name).exists()}):
        if not allowed(relative) or relative in DATABASES:
            raise ValueError('题池导出包含范围外路径：' + relative)
        original, saved = safe_path(source, relative), safe_path(destination, relative)
        regular(original)
        saved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(original, saved)
        saved.chmod(0o600)
        if digest(original) != digest(saved):
            raise ValueError('导出期间文件变化：' + relative)
    for path in destination.rglob('*'):
        if path.is_file() and path.name != '.DS_Store':
            relative = path.relative_to(destination).as_posix()
            files[relative] = {'size':path.stat().st_size, 'sha256':digest(path)}
    manifest = {'version':1, 'kind':'question-pool-transfer', 'required_commit':COMMIT, 'counts':counts(destination), 'files':files}
    write_json(destination / MANIFEST, manifest)
    verify(destination, check_drivers=False)
    return manifest


def verify(package, check_drivers=True):
    package = Path(package).absolute()
    manifest_path = safe_path(package, MANIFEST); regular(manifest_path)
    manifest = json.loads(manifest_path.read_text())
    if manifest.get('version') != 1 or manifest.get('kind') != 'question-pool-transfer' or manifest.get('required_commit') != COMMIT:
        raise ValueError('题池数据包版本无效')
    files = manifest.get('files')
    if not isinstance(files, dict) or not set(DATABASES) <= set(files):
        raise ValueError('题池数据清单不完整')
    for relative, info in files.items():
        if not allowed(relative):
            raise ValueError('题池数据包包含范围外文件')
        path = safe_path(package, relative); regular(path)
        if path.stat().st_size != info.get('size') or digest(path) != info.get('sha256'):
            raise ValueError('题池文件校验失败：' + relative)
    extras = set(DRIVERS) | {MANIFEST, 'SHA256SUMS'} if check_drivers else {MANIFEST}
    actual = set()
    for base, directories, filenames in os.walk(package, followlinks=False):
        for name in directories:
            path = Path(base) / name
            if path.is_symlink():
                raise ValueError('题池数据包包含目录链接')
        for name in filenames:
            if name == '.DS_Store':
                continue
            path = Path(base) / name; regular(path)
            actual.add(path.relative_to(package).as_posix())
    if actual - extras != set(files) or (check_drivers and not set(DRIVERS) <= actual):
        raise ValueError('题池文件与清单不一致')
    for relative in DATABASES:
        database_check(package / relative)
    if counts(package) != manifest.get('counts'):
        raise ValueError('题数与数据清单不一致')
    return manifest


def preflight_files(package, target, manifest):
    for relative, info in manifest['files'].items():
        if relative in DATABASES:
            continue
        dest = safe_path(target, relative)
        if dest.exists():
            regular(dest)
            if dest.stat().st_size != info['size'] or digest(dest) != info['sha256']:
                raise ValueError('服务器同名附件或图谱数据不同，未覆盖：' + relative)


def capacity(package, target, staging):
    manifest = verify(package)
    preflight_files(package, target, manifest)
    imported = sum(i['size'] for i in manifest['files'].values())
    existing = sum(safe_path(target, r).stat().st_size for r in DATABASES if safe_path(target, r).exists())
    # Two candidate passes, backup, installation temporary files, SQLite overhead.
    required = imported * 2 + existing * 3 + 256 * 1024 * 1024
    free = shutil.disk_usage(staging).free
    if free < required:
        raise ValueError(f'空间不足：需 {required//1024**2} MiB，可用 {free//1024**2} MiB；尚未停止网站')
    print(f'数据空间已检查：需预留 {required//1024**2} MiB。', flush=True)


def make_parents(path, root, uid, gid):
    missing = []
    parent = path.parent
    while parent != root:
        if not parent.exists():
            missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700)
        if uid is not None:
            os.chown(directory, uid, gid)


def atomic_install(source, target, uid=None, gid=None):
    descriptor, name = tempfile.mkstemp(prefix='.question-data-install.', dir=target.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(0o600)
        if uid is not None:
            os.chown(temporary, uid, gid)
        with temporary.open('rb') as stream:
            os.fsync(stream.fileno())
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


def apply(package, candidate, target, backup, uid=None, gid=None):
    package, candidate, target, backup = map(lambda p:Path(p).absolute(), (package,candidate,target,backup))
    manifest = verify(package); preflight_files(package, target, manifest)
    for relative in DATABASES:
        database_check(safe_path(candidate, relative))
    backup.mkdir(parents=True, exist_ok=True, mode=0o700)
    if any(backup.iterdir()):
        raise ValueError('导入备份目录必须为空')
    ledger = {'version':1, 'ready':False, 'databases':{}, 'added_files':[]}
    write_json(backup / LEDGER, ledger)
    for relative in DATABASES:
        source = safe_path(target, relative)
        ledger['databases'][relative] = source.exists()
        if source.exists():
            database_copy(source, safe_path(backup, relative))
    ledger['ready'] = True; write_json(backup / LEDGER, ledger)
    for relative in sorted(manifest['files']):
        if relative in DATABASES:
            continue
        dest = safe_path(target, relative)
        if not dest.exists():
            # Persist the rollback record before the corresponding mutation.
            ledger['added_files'].append(relative); write_json(backup / LEDGER, ledger)
            make_parents(dest, target, uid, gid)
            atomic_install(package / relative, dest, uid, gid)
    for relative in DATABASES:
        dest = safe_path(target, relative)
        make_parents(dest, target, uid, gid)
        for suffix in ('-wal','-shm','-journal'):
            sidecar = safe_path(target, relative + suffix)
            if sidecar.exists():
                regular(sidecar); sidecar.unlink()
        atomic_install(candidate / relative, dest, uid, gid)
    verify_live(package, target)
    print(f"原题池与审核数据已安装：{manifest['counts']['pool_items']:,} 道原题。", flush=True)


def rollback(target, backup, uid=None, gid=None):
    target, backup = Path(target).absolute(), Path(backup).absolute()
    ledger_path = safe_path(backup, LEDGER)
    if not ledger_path.exists():
        return
    regular(ledger_path); ledger = json.loads(ledger_path.read_text())
    if ledger.get('version') != 1:
        raise ValueError('数据回滚清单无效')
    if not ledger.get('ready'):
        return
    if set(ledger['databases']) != set(DATABASES) or any(not allowed(r) or r in DATABASES for r in ledger['added_files']):
        raise ValueError('回滚数据范围无效')
    for relative, was_present in ledger['databases'].items():
        if was_present:
            database_check(safe_path(backup, relative))
        safe_path(target, relative)
    for relative, was_present in ledger['databases'].items():
        dest = safe_path(target, relative)
        for suffix in ('-wal','-shm','-journal'):
            sidecar = safe_path(target, relative + suffix)
            if sidecar.exists():
                regular(sidecar); sidecar.unlink()
        if was_present:
            atomic_install(backup / relative, dest, uid, gid)
        else:
            dest.unlink(missing_ok=True)
    for relative in reversed(ledger['added_files']):
        dest = safe_path(target, relative)
        if dest.exists():
            regular(dest); dest.unlink()
    print('已恢复导入前的服务器题池和审核数据。', flush=True)


def verify_live(package, target):
    manifest = verify(package)
    for relative in DATABASES:
        database_check(safe_path(target, relative))
    source = sqlite3.connect((Path(package)/DATABASES[0]).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)
    with closing(source), closing(sqlite3.connect(safe_path(target,DATABASES[0]).resolve().as_uri()+'?mode=ro',uri=True)) as live:
        for identifier, fingerprint in source.execute('SELECT id,fingerprint FROM pool_items'):
            if live.execute('SELECT fingerprint FROM pool_items WHERE id=?',(identifier,)).fetchone() != (fingerprint,):
                raise ValueError('导入后原题编号/指纹校验失败')
    with closing(sqlite3.connect((Path(package)/DATABASES[1]).resolve().as_uri()+'?mode=ro&immutable=1',uri=True)) as source, closing(sqlite3.connect(safe_path(target,DATABASES[1]).resolve().as_uri()+'?mode=ro',uri=True)) as live:
        for run_id, item_id, content_hash in source.execute('SELECT run_id,item_id,content_hash FROM review_items'):
            if live.execute('SELECT content_hash FROM review_items WHERE run_id=? AND item_id=?',(run_id,item_id)).fetchone() != (content_hash,):
                raise ValueError('导入后审核题目引用校验失败')
    preflight_files(package, target, manifest)
    for relative in manifest['files']:
        if relative not in DATABASES:
            path = safe_path(target, relative)
            if not path.is_file():
                raise ValueError('导入后附件缺失：' + relative)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['export','verify','capacity','apply','rollback','verify-live'])
    parser.add_argument('paths', nargs='+')
    args = parser.parse_args()
    expected = {'export':3,'verify':1,'capacity':3,'apply':4,'rollback':2,'verify-live':2}
    if len(args.paths) != expected[args.action]:
        parser.error('参数数量错误')
    paths = list(map(Path,args.paths))
    uid = gid = None
    if args.action in ('apply','rollback'):
        import pwd
        owner = pwd.getpwnam('studyagent'); uid, gid = owner.pw_uid, owner.pw_gid
    if args.action == 'export':
        required = json.loads(paths[2].read_text())
        result = export(paths[0],paths[1],required['paths'])
    elif args.action == 'verify':
        result = verify(paths[0])
    elif args.action == 'capacity':
        capacity(*paths); return
    elif args.action == 'apply':
        apply(*paths,uid,gid); return
    elif args.action == 'rollback':
        rollback(*paths,uid,gid); return
    else:
        verify_live(*paths); print('导入后的题池与附件已校验。'); return
    print(json.dumps(result['counts'], ensure_ascii=False), flush=True)


if __name__ == '__main__':
    try:
        main()
    except (ValueError,OSError,sqlite3.Error) as exc:
        raise SystemExit(str(exc)) from None
