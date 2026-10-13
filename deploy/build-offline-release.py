"""Package one real main commit for manual ECS publishing, without private data."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tarfile
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def git(*arguments):
    return subprocess.check_output(['git','-C',str(ROOT),*arguments])


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def build(destination, require_question_import=False):
    commit=git('rev-parse','HEAD').decode().strip()
    branch=git('symbolic-ref','--short','HEAD').decode().strip()
    if branch!='main' or not re.fullmatch('[0-9a-f]{40}',commit):
        raise ValueError('请在 main 的真实本地提交上制作发布包')
    if git('diff','--name-only').strip() or git('diff','--cached','--name-only').strip():
        raise ValueError('先提交并验收本轮代码，再制作固定版本发布包')
    destination=Path(destination).absolute();destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='study-offline-release-') as temporary:
        package=Path(temporary)
        subprocess.run(['git','-C',str(ROOT),'bundle','create',str(package/'release.bundle'),'main'],check=True)
        subprocess.run(['git','-C',str(ROOT),'bundle','verify',str(package/'release.bundle')],check=True,stdout=subprocess.DEVNULL)
        for name in ('bootstrap-offline.sh','sync-sites.sh'):
            (package/name).write_bytes(git('show',commit+':deploy/'+name))
            subprocess.run(['bash','-n',str(package/name)],check=True)
        for relative in ('backend/showcase.py','frontend/showcase/index.html','frontend/showcase/app.js','frontend/showcase/style.css','frontend/showcase/data.json'):
            git('cat-file','-e',commit+':'+relative)
        manifest={'version':1,'commit':commit,'demo_mode':'showcase','require_question_import':bool(require_question_import),
                  'requirements_sha256':hashlib.sha256(git('show',commit+':requirements.txt')).hexdigest(),
                  'private_data_included':False,'dependencies_included':False}
        (package/'release.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        files=sorted(package.iterdir())
        (package/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in files))
        with tarfile.open(destination,'w:gz') as tar:
            for path in sorted(package.iterdir()):tar.add(path,arcname=path.name,recursive=False)
    destination.chmod(0o600)
    checksum=sha(destination)
    destination.with_name(destination.name+'.sha256').write_text(checksum+'  '+destination.name+'\n')
    return {'archive':str(destination),'commit':commit,'sha256':checksum,'size_mib':round(destination.stat().st_size/1024**2,2)}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='用已验收的真实 Git 提交制作源码离线包，不复制私人题库或密钥')
    parser.add_argument('destination',type=Path)
    parser.add_argument('--require-question-import',action='store_true')
    arguments=parser.parse_args()
    try:print(json.dumps(build(arguments.destination,arguments.require_question_import),ensure_ascii=False))
    except (ValueError,OSError,subprocess.CalledProcessError) as error:raise SystemExit(str(error)) from None
