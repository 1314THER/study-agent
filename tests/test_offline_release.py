"""Run the deployment's actual Git transfer block against isolated repositories."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.name=='posix' and shutil.which('git') and shutil.which('bash'),'Git/Bash POSIX tests')
class OfflineReleaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.source=self.root/'source';self.server=self.root/'server'
        self.git(self.root,'init','-q','-b','main',str(self.source))
        self.git(self.source,'config','user.name','Release test');self.git(self.source,'config','user.email','release@example.test')
        (self.source/'.gitignore').write_text('runtime.db\n')
        (self.source/'app.txt').write_text('old')
        self.git(self.source,'add','.');self.git(self.source,'commit','-qm','old');self.old=self.git(self.source,'rev-parse','HEAD').stdout.strip()
        self.git(self.root,'clone','-q',str(self.source),str(self.server))
        (self.source/'app.txt').write_text('new')
        self.git(self.source,'add','.');self.git(self.source,'commit','-qm','new');self.target=self.git(self.source,'rev-parse','HEAD').stdout.strip()
        self.bundle=self.root/'release.bundle';self.git(self.source,'bundle','create',str(self.bundle),'main')
        self.git(self.server,'remote','set-url','origin','http://127.0.0.1:1/unreachable.git')
        (self.server/'runtime.db').write_text('keep server data')
        script=(ROOT/'deploy/sync-sites.sh').read_text()
        start=script.index('# The offline bootstrap passes')
        end=script.index('STAGING=$(mktemp',start)
        self.block=script[start:end]

    def git(self,cwd,*args):
        return subprocess.run(['git',*args],cwd=cwd,text=True,capture_output=True,check=True)

    def transfer(self,target=None):
        env={**os.environ,'APP_DIR':str(self.server),'TARGET':target or self.target,'OLD_COMMIT':self.old,'STUDY_SYNC_BUNDLE':str(self.bundle)}
        return subprocess.run(['bash','-c','set -Eeuo pipefail\ngit_owner() { git -C "$APP_DIR" "$@"; }\n'+self.block],env=env,text=True,capture_output=True,timeout=15)

    def test_offline_fetch_does_not_need_github_or_change_live_checkout(self):
        result=self.transfer();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(self.git(self.server,'rev-parse','HEAD').stdout.strip(),self.old)
        self.assertEqual((self.server/'app.txt').read_text(),'old')
        self.assertEqual((self.server/'runtime.db').read_text(),'keep server data')
        self.assertEqual(self.git(self.server,'rev-parse','refs/study-agent-sync/bundle-'+self.target).stdout.strip(),self.target)

    def test_wrong_release_commit_is_rejected(self):
        result=self.transfer(self.old)
        self.assertNotEqual(result.returncode,0)
        self.assertIn('与指定发布提交不同',result.stderr)
        self.assertEqual(self.git(self.server,'rev-parse','HEAD').stdout.strip(),self.old)

    def test_damaged_bundle_is_rejected(self):
        self.bundle.write_bytes(b'not a Git bundle')
        result=self.transfer();self.assertNotEqual(result.returncode,0)
        self.assertEqual((self.server/'runtime.db').read_text(),'keep server data')

    def test_candidate_dependency_install_uses_only_the_local_wheelhouse(self):
        script=(ROOT/'deploy/sync-sites.sh').read_text()
        start=script.index('if ! cmp -s "$STAGING/requirements.old"')
        end=script.index('"$STAGING/.venv/bin/python" -c',start)
        block=script[start:end]
        stage=self.root/'stage';(stage/'code').mkdir(parents=True)
        (stage/'requirements.old').write_text('old');(stage/'code/requirements.txt').write_text('new')
        wheelhouse=self.root/'wheelhouse';wheelhouse.mkdir()
        recorded=self.root/'arguments'
        env={**os.environ,'STAGING':str(stage),'STUDY_SYNC_WHEELHOUSE':str(wheelhouse),'RECORDED':str(recorded)}
        result=subprocess.run(['bash','-c','set -Eeuo pipefail\nrunuser() { printf "%s\\n" "$@" > "$RECORDED"; }\n'+block],env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,0,result.stderr)
        args=recorded.read_text().splitlines()
        self.assertIn('--no-index',args);self.assertIn('--find-links',args)
        for argument in ('--only-binary=:all:', '--disable-pip-version-check', '--no-cache-dir', 'PIP_CONFIG_FILE=/dev/null'):
            self.assertIn(argument,args)
        for variable in ('PIP_FIND_LINKS', 'PIP_INDEX_URL', 'PIP_EXTRA_INDEX_URL'):
            self.assertEqual(args[args.index(variable)-1],'-u')
        self.assertEqual(args[args.index('--find-links')+1],str(wheelhouse))
        self.assertIn(str(stage/'.venv/bin/python'),args)
        self.assertEqual((self.server/'runtime.db').read_text(),'keep server data')

    def test_missing_wheelhouse_stops_before_installing(self):
        script=(ROOT/'deploy/sync-sites.sh').read_text();start=script.index('if ! cmp -s "$STAGING/requirements.old"');end=script.index('"$STAGING/.venv/bin/python" -c',start)
        stage=self.root/'missing-stage';(stage/'code').mkdir(parents=True)
        (stage/'requirements.old').write_text('old');(stage/'code/requirements.txt').write_text('new')
        env={**os.environ,'STAGING':str(stage),'STUDY_SYNC_WHEELHOUSE':str(self.root/'missing-wheelhouse')}
        result=subprocess.run(['bash','-c','set -Eeuo pipefail\nrunuser() { exit 99; }\n'+script[start:end]],env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,1)
        self.assertIn('离线依赖目录不可用',result.stderr)

    def test_symlink_wheelhouse_stops_before_installing(self):
        script=(ROOT/'deploy/sync-sites.sh').read_text();start=script.index('if ! cmp -s "$STAGING/requirements.old"');end=script.index('"$STAGING/.venv/bin/python" -c',start)
        stage=self.root/'symlink-stage';(stage/'code').mkdir(parents=True)
        (stage/'requirements.old').write_text('old');(stage/'code/requirements.txt').write_text('new')
        wheels=self.root/'wheels';wheels.mkdir()
        wheel_link=self.root/'wheel-link';wheel_link.symlink_to(wheels,target_is_directory=True)
        env={**os.environ,'STAGING':str(stage),'STUDY_SYNC_WHEELHOUSE':str(wheel_link)}
        result=subprocess.run(['bash','-c','set -Eeuo pipefail\nrunuser() { exit 99; }\n'+script[start:end]],env=env,text=True,capture_output=True)
        self.assertEqual(result.returncode,1)
        self.assertIn('离线依赖目录不可用',result.stderr)

    def test_release_metadata_enforces_the_import_gate_and_rejects_invalid_flags(self):
        import json
        bootstrap=(ROOT/'deploy/bootstrap-offline.sh').read_text()
        start=bootstrap.index('if [[ -f release.json ]]; then')
        end=bootstrap.index('[[ -f release.bundle',start)
        block=bootstrap[start:end]
        for flag,expected in ((True,'1'),(False,'0'),('1',None)):
            with self.subTest(flag=flag):
                (self.root/'release.json').write_text(json.dumps({'require_question_import':flag}))
                result=subprocess.run(['bash','-c','set -Eeuo pipefail\n'+block+'\nprintf "%s\\n" "${STUDY_SYNC_REQUIRE_QUESTION_IMPORT:-0}"'],cwd=self.root,
                                      env={**os.environ,'STUDY_SYNC_REQUIRE_QUESTION_IMPORT':'0'},text=True,capture_output=True)
                if expected is None:self.assertNotEqual(result.returncode,0)
                else:
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertEqual(result.stdout.splitlines()[-1],expected)
