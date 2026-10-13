"""The demo's exported public bank contains JSON and images, never live DBs."""
import hashlib
import json
from pathlib import Path
import re

FILE_NAME = re.compile(r'^(?:index\.json|part-[0-9]{4}\.json|images/[0-9a-f]{64}\.png)$')


def manifest(directory):
    root = Path(directory)
    path = root / 'manifest.json'
    if root.is_symlink() or path.is_symlink() or not path.is_file():
        raise ValueError('缺少公开题库，请先生成或上传题库文件。')
    data = json.loads(path.read_text())
    if data.get('version') != 1 or type(data.get('count')) is not int or data['count'] < 1:
        raise ValueError('题库清单格式无效。')
    files = data.get('files')
    if not isinstance(files, dict) or 'index.json' not in files or len(files) > 10000:
        raise ValueError('题库文件清单无效。')
    for name, entry in files.items():
        if not FILE_NAME.fullmatch(name) or not isinstance(entry, dict) or not re.fullmatch('[0-9a-f]{64}', str(entry.get('sha256', ''))):
            raise ValueError('题库文件名或校验值无效。')
        if type(entry.get('size')) is not int or entry['size'] < 1:
            raise ValueError('题库文件大小无效。')
    if len(data.get('parts', {})) != data['count'] or any(name not in files for name in data['parts'].values()):
        raise ValueError('题目与分片清单不一致。')
    return data


def verify(directory):
    root = Path(directory)
    data = manifest(root)
    expected = set(data['files']) | {'manifest.json'}
    actual = set()
    for path in root.rglob('*'):
        if path.is_symlink() or not (path.is_file() or path.is_dir()):
            raise ValueError('公开题库包含链接或特殊文件。')
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise ValueError('题库文件缺失或含清单外的文件。')
    for name, entry in data['files'].items():
        path = root / name
        if path.stat().st_size != entry['size'] or hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('题库文件校验失败：' + name)
    index = json.loads((root / 'index.json').read_text())
    if len(index) != data['count'] or len({row['id'] for row in index}) != data['count']:
        raise ValueError('题目总数或编号不一致。')
    return data
