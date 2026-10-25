"""Check the local release artifact without touching a server or model API."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from scripts.build_research_release import ROOT, build, extract_archive, public_paths, verify_directory


class ResearchReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='research-release-test-')
        cls.directory = Path(cls.temporary.name)
        cls.result = build(cls.directory / 'artifacts')

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_archive_contains_only_public_files_and_validates_after_extraction(self):
        target = self.directory / 'roundtrip'
        target.mkdir()
        extract_archive(Path(self.result['archive']), target)
        manifest = verify_directory(target)
        self.assertEqual(set(manifest['files']), public_paths(ROOT) | {'activate-demo.sh', 'verify-release.py'})
        self.assertFalse(manifest['private_data_included'])
        self.assertEqual(manifest['git_head'], self.result['git_head'])
        self.assertNotIn('backend/database.py', manifest['files'])
        self.assertNotIn('frontend/showcase/fonts/build_subset.py', manifest['files'])

    def test_modified_public_asset_fails_integrity_validation(self):
        target = self.directory / 'tampered'
        target.mkdir()
        extract_archive(Path(self.result['archive']), target)
        with (target / 'frontend/showcase/app.js').open('a') as output:
            output.write('\n// unexpected modification\n')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            verify_directory(target)

    def test_archive_cannot_write_a_path_outside_its_destination(self):
        target = self.directory / 'unsafe'
        target.mkdir()
        archive = self.directory / 'unsafe.tar.gz'
        with tarfile.open(archive, 'w:gz') as bundle:
            entry = tarfile.TarInfo('../escaped.txt')
            entry.size = 4
            bundle.addfile(entry, io.BytesIO(b'data'))
        with self.assertRaisesRegex(ValueError, 'Unsafe release path'):
            extract_archive(archive, target)
        self.assertFalse((self.directory / 'escaped.txt').exists())
        self.assertEqual(list(target.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
