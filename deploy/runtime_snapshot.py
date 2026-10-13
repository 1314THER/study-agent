"""Verified owner-data snapshots shared by deployment and rollback.

Run backup/restore after stopping the service. Only the declared persistent
paths are managed; code, virtual environments and local Codex credentials are
never included. Snapshots may contain private settings and account data.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sqlite3
import stat

FILES = ('study_agent.db','mastery.db','.runtime/jobs.sqlite3',
         '.runtime/question_pool.db','.runtime/routine-review.sqlite3',
         'backend/patterns.yaml','backend/board_order.yaml','backend/settings.json','.env')
TREES = ('.runtime/question-pool','.runtime/question-assets','.runtime/routine-matching','.accounts')
MANAGED = FILES + TREES
MANIFEST = 'snapshot-manifest.json'


def safe_path(root, relative):
    parts = PurePosixPath(relative)
    if not relative or parts.is_absolute() or any(p in ('.','..') for p in parts.parts) or '\\' in relative:
        raise ValueError('快照路径无效')
    path = root
    for component in parts.parts:
        path = path/component
        if path.is_symlink():
            raise ValueError('运行数据包含符号链接：'+relative)
    return path


def regular(path):
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
        raise ValueError('运行数据包含特殊文件或硬链接：'+path.name)


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def sqlite_file(path):
    with path.open('rb') as stream:
        return stream.read(16)==b'SQLite format 3\x00'


def walk_files(root):
    for base, dirs, files in os.walk(root,followlinks=False):
        for name in dirs:
            path=Path(base)/name
            if path.is_symlink() or not path.is_dir():
                raise ValueError('运行目录包含符号链接或特殊目录')
        for name in files:
            path=Path(base)/name
            regular(path)
            yield path


def check_sqlite(path):
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':
            raise ValueError('数据库快照完整性校验失败：'+path.name)


def required_bytes(source):
    source=Path(source).resolve();total=0
    for name in MANAGED:
        path=safe_path(source,name)
        if not path.exists():continue
        if name in FILES:
            regular(path);total+=path.stat().st_size
            for suffix in ('-wal','-shm','-journal'):
                sidecar=safe_path(source,name+suffix)
                if sidecar.exists():regular(sidecar);total+=sidecar.stat().st_size
        else:total+=sum(p.stat().st_size for p in walk_files(path))
    return total


def backup(source, destination):
    source=Path(source).resolve();destination=Path(destination).absolute()
    if not source.is_dir() or destination.is_symlink() or (destination.exists() and any(destination.iterdir())):
        raise ValueError('源目录不存在，或快照目录不是空的独立目录')
    # A snapshot inside a managed directory would recursively copy itself.
    if any(destination.resolve().is_relative_to(source/name) for name in TREES):
        raise ValueError('快照不能保存在被备份的运行目录内')
    destination.mkdir(parents=True,exist_ok=True,mode=0o700);destination.chmod(0o700)
    manifest={'version':1,'source_root':str(source),'managed':list(MANAGED),'present':[],'files':{}}

    def copy_file(src,relative):
        regular(src);dest=safe_path(destination,relative);dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        is_sqlite=sqlite_file(src)
        if is_sqlite:
            with closing(sqlite3.connect(src.resolve().as_uri()+'?mode=ro',uri=True)) as original, closing(sqlite3.connect(dest)) as saved:
                original.backup(saved);saved.execute('PRAGMA journal_mode=DELETE');saved.commit()
            check_sqlite(dest)
        else:
            shutil.copyfile(src,dest)
            if sha256(src)!=sha256(dest):
                raise ValueError('备份期间文件发生变化：'+relative)
        dest.chmod(0o600)
        manifest['files'][relative]={'sha256':sha256(dest),'size':dest.stat().st_size,'sqlite':is_sqlite}

    for name in MANAGED:
        src=safe_path(source,name)
        if not src.exists():
            if name in ('study_agent.db','mastery.db'):
                raise ValueError('主人数据库不存在：'+name)
            continue
        manifest['present'].append(name)
        if name in FILES:
            if not src.is_file():raise ValueError('预期文件变成了目录：'+name)
            copy_file(src,name)
        else:
            if not src.is_dir():raise ValueError('预期运行目录变成了文件：'+name)
            safe_path(destination,name).mkdir(parents=True,exist_ok=True,mode=0o700)
            for path in walk_files(src):
                # The backup API merges WAL contents; sidecars must not return
                # alongside a normalized database on restoration.
                if any(path.name.endswith(suffix) and (base:=Path(str(path)[:-len(suffix)])).is_file() and sqlite_file(base)
                       for suffix in ('-wal','-shm','-journal')):
                    continue
                copy_file(path,path.relative_to(source).as_posix())
    m=destination/MANIFEST;m.write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');m.chmod(0o600)
    verify(destination)
    return manifest


def verify(snapshot):
    snapshot=Path(snapshot).absolute()
    if snapshot.is_symlink() or not snapshot.is_dir():raise ValueError('快照目录无效')
    manifest_path=safe_path(snapshot,MANIFEST);regular(manifest_path)
    manifest=json.loads(manifest_path.read_text())
    if manifest.get('version')!=1 or manifest.get('managed')!=list(MANAGED):raise ValueError('快照版本或数据范围无效')
    present=manifest.get('present');files=manifest.get('files')
    if not isinstance(present,list) or len(present)!=len(set(present)) or not set(present)<=set(MANAGED) or not isinstance(files,dict):
        raise ValueError('快照清单无效')
    actual={p.relative_to(snapshot).as_posix() for p in walk_files(snapshot)}-{MANIFEST}
    if actual!=set(files):raise ValueError('快照文件与清单不符')
    for name in present:
        path=safe_path(snapshot,name)
        if not (path.is_file() if name in FILES else path.is_dir()):raise ValueError('快照缺少已声明的数据：'+name)
    for name,info in files.items():
        if not any(name==root or (root in TREES and name.startswith(root+'/')) for root in present):raise ValueError('快照包含范围外的数据')
        path=safe_path(snapshot,name)
        if path.stat().st_size!=info.get('size') or sha256(path)!=info.get('sha256'):raise ValueError('快照摘要校验失败：'+name)
        if info.get('sqlite') is True:check_sqlite(path)
    return manifest


def restore(snapshot, target, uid=None, gid=None):
    manifest=verify(snapshot);snapshot=Path(snapshot).absolute();target=Path(target).absolute()
    if target.is_symlink() or not target.is_dir():raise ValueError('恢复目标目录无效')
    # Validate every destination before modifying the first one.
    for name in MANAGED:
        dest=safe_path(target,name)
        if dest.exists() and name in FILES:regular(dest)
        if dest.exists() and name in TREES:
            if not dest.is_dir():raise ValueError('恢复目标的运行目录变成了文件')
            list(walk_files(dest))
        for suffix in ('-wal','-shm','-journal') if name in FILES else ():
            sidecar=safe_path(target,name+suffix)
            if sidecar.exists():regular(sidecar)
    for name in MANAGED:
        dest=safe_path(target,name)
        if name in TREES:
            if dest.exists():shutil.rmtree(dest)
            if name in manifest['present']:
                dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                shutil.copytree(snapshot/name,dest)
        else:
            if name in manifest['present']:
                dest.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
                shutil.copyfile(snapshot/name,dest);dest.chmod(0o600)
            else:dest.unlink(missing_ok=True)
            for suffix in ('-wal','-shm','-journal'):Path(str(dest)+suffix).unlink(missing_ok=True)
        if dest.exists() and uid is not None:
            os.chown(dest,uid,gid)
            if dest.is_dir():
                for base,dirs,files in os.walk(dest):
                    for child in dirs+files:os.chown(Path(base)/child,uid,gid)
            for parent in dest.parents:
                if parent==target:break
                os.chown(parent,uid,gid)
    return manifest


def main():
    parser=argparse.ArgumentParser(description='停止服务后备份、验证或恢复主人全部持久数据')
    parser.add_argument('action',choices=['backup','verify','restore']);parser.add_argument('source',type=Path)
    parser.add_argument('destination',type=Path,nargs='?');parser.add_argument('--owner')
    args=parser.parse_args()
    if args.action=='verify':result=verify(args.source)
    else:
        if args.destination is None:parser.error('backup/restore 需要目标目录')
        if args.action=='backup':result=backup(args.source,args.destination)
        else:
            uid=gid=None
            if args.owner:
                import pwd
                user=pwd.getpwnam(args.owner);uid,gid=user.pw_uid,user.pw_gid
            result=restore(args.source,args.destination,uid,gid)
    print('运行数据快照已校验：'+str(len(result['files']))+' 个文件。')


if __name__=='__main__':
    try:main()
    except (ValueError,OSError,sqlite3.Error) as exc:raise SystemExit(str(exc)) from None
