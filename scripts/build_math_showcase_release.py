#!/usr/bin/env python3
"""Create a minimal, checksummed release package for math.150.chat."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
FONTS = '''AMS-Regular Caligraphic-Bold Caligraphic-Regular Fraktur-Bold Fraktur-Regular Main-Bold Main-BoldItalic Main-Italic Main-Regular Math-BoldItalic Math-Italic SansSerif-Bold SansSerif-Italic SansSerif-Regular Script-Regular Size1-Regular Size2-Regular Size3-Regular Size4-Regular Typewriter-Regular'''.split()
FILES = [
    'backend/__init__.py',
    'backend/math_showcase.py',
    'deploy/study-agent-math-showcase.service',
    'deploy/study-agent-math-showcase.caddy',
    'frontend/math-showcase/index.html',
    'frontend/math-showcase/topics.html',
    'frontend/math-showcase/math.css',
    'frontend/math-showcase/math.js',
    'frontend/math-showcase/math-render.js',
    'frontend/math-showcase/topics.js',
    'frontend/math-showcase/math-mark.svg',
    'frontend/math-showcase/math-case.json',
    'frontend/math-showcase/math-topics.json',
    'frontend/vendor/katex/LICENSE',
    'frontend/vendor/katex/katex.min.css',
    'frontend/vendor/katex/katex.min.js',
    *[f'frontend/vendor/katex/fonts/KaTeX_{font}.woff2' for font in FONTS],
]
HELPER = ROOT / 'deploy' / 'activate-math-showcase.sh'


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_metadata() -> tuple[str | None, bool]:
    try:
        head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        dirty = bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip())
        return head, dirty
    except (OSError, subprocess.CalledProcessError):
        return None, True


def verify_generated_data() -> None:
    import sys

    sys.path.insert(0, str(ROOT / 'scripts'))
    from build_math_showcase import build_data, build_topics, digest

    for name, expected in (
        ('math-case.json', build_data()),
        ('math-topics.json', build_topics()),
    ):
        path = ROOT / 'frontend' / 'math-showcase' / name
        if not path.is_file():
            raise SystemExit(f'缺少 {path.relative_to(ROOT)}；先运行 scripts/build_math_showcase.py。')
        try:
            actual = json.loads(path.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise SystemExit(f'{path.relative_to(ROOT)} 不是有效 JSON：{exc}') from exc
        if digest(actual) != digest(expected):
            raise SystemExit(f'{path.relative_to(ROOT)} 已过期；先运行 scripts/build_math_showcase.py。')


def add_file(bundle: tarfile.TarFile, relative: str, payload: bytes) -> None:
    info = tarfile.TarInfo(relative)
    info.size = len(payload)
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = 'root'
    info.mtime = 0
    bundle.addfile(info, io.BytesIO(payload))


def main() -> int:
    parser = argparse.ArgumentParser(description='为 math.150.chat 制作独立、最小化发布包')
    parser.add_argument('--output', default='.runtime/math-showcase-release', help='本地发布产物目录')
    args = parser.parse_args()

    verify_generated_data()
    files: dict[str, bytes] = {}
    for relative in FILES:
        path = ROOT / relative
        if path.is_symlink() or not path.is_file():
            raise SystemExit(f'发布白名单文件缺失或为符号链接：{relative}')
        files[relative] = path.read_bytes()
    if HELPER.is_symlink() or not HELPER.is_file():
        raise SystemExit('缺少 deploy/activate-math-showcase.sh。')

    head, dirty = git_metadata()
    created = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    metadata = {
        'schema_version': 1,
        'site': 'math.150.chat',
        'created_at_utc': created,
        'source_commit': head,
        'working_tree_dirty': dirty,
        'file_count': len(files) + 1,
        'release_scope': 'read-only static showcase; no AI calls; independent service and Caddy vhost',
    }
    files['release.json'] = (json.dumps(metadata, ensure_ascii=False, indent=2) + '\n').encode()
    manifest = ''.join(f'{sha256(payload)}  {name}\n' for name, payload in sorted(files.items())).encode()

    output = Path(args.output)
    if not output.is_absolute():
        output = ROOT / output
    output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    temporary = output / f'.math-showcase-{stamp}.tar.gz.part'
    with temporary.open('wb') as raw:
        with gzip.GzipFile(filename='', mode='wb', fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as bundle:
                for relative, payload in sorted(files.items()):
                    add_file(bundle, relative, payload)
                add_file(bundle, 'MANIFEST.sha256', manifest)
    archive_hash = sha256(temporary.read_bytes())
    archive = output / f'math-showcase-{stamp}-{archive_hash[:10]}.tar.gz'
    if archive.exists():
        temporary.unlink()
        raise SystemExit(f'输出文件已存在，未覆盖：{archive}')
    temporary.replace(archive)

    helper = output / 'activate-math-showcase.sh'
    if helper.exists():
        helper.unlink()
    helper.write_bytes(HELPER.read_bytes())
    helper.chmod(0o755)
    helper_hash = sha256(helper.read_bytes())
    sums = output / 'SHA256SUMS'
    sums.write_text(f'{archive_hash}  {archive.name}\n{helper_hash}  {helper.name}\n', encoding='utf-8')
    (output / 'release.json').write_text(
        json.dumps({**metadata, 'archive': archive.name, 'archive_sha256': archive_hash}, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8',
    )
    print(f'发布包：{archive}')
    print(f'发布包 SHA256：{archive_hash}')
    print(f'Workbench 辅助文件：{helper}')
    print(f'校验清单：{sums}')
    print(f"源码 HEAD：{head or '不可用'}；工作树有未提交改动：{'是' if dirty else '否'}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
