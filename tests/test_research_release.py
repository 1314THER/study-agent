"""Check the local release artifact without touching a server or model API."""
import io
import html
import json
from pathlib import Path
import re
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from scripts.build_research_release import ROOT, build, checked_file, extract_archive, public_paths, validate_content, verify_directory


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

    def test_release_includes_independent_vision_assets_and_complete_static_content(self):
        target = self.directory / 'vision-roundtrip'
        target.mkdir()
        extract_archive(Path(self.result['archive']), target)
        manifest = verify_directory(target)
        for filename in ('vision-content.json', 'vision.css', 'vision.js'):
            self.assertIn('frontend/showcase/' + filename, manifest['files'])
        public = target / 'frontend/showcase'
        vision = json.loads((public / 'vision-content.json').read_text())
        research = json.loads((public / 'research-content.json').read_text())
        page = (public / 'index.html').read_text()
        self.assertNotIn('vision', research)
        self.assertEqual(len(research['chapters']), 15)
        self.assertEqual([len(group['rows']) for group in vision['groups']], [21, 17, 17, 8])
        changes = re.findall(r'<article\b[^>]*class="[^"]*\bvision-change\b[^"]*"[^>]*>.*?</article>', page, re.S)
        self.assertEqual(len(changes), 63)
        self.assertLess(page.index('id="vision"'), page.index('id="highlights"'))
        rows = [row for group in vision['groups'] for row in group['rows']]
        for row, change in zip(rows, changes):
            text = html.unescape(re.sub(r'<[^>]+>', '', change))
            for field in ('aspect', 'before', 'after'):
                self.assertIn(row[field], text)
            for feature in row['features']:
                self.assertIn(feature['label'], text)
                self.assertIn('href="' + feature['target'] + '"', change)
                self.assertIn(feature['status'], text)
        self.assertNotIn('<table', page[page.index('id="vision"'):page.index('id="highlights"')])
        self.assertEqual(page.count('class="vision-disclosure"'), 4)
        self.assertEqual(page.count('class="vision-more"'), 4)
        for group in vision['groups']:
            self.assertIn('aria-controls="vision-more-' + group['id'] + '"', page)

    def test_modified_public_asset_fails_integrity_validation(self):
        target = self.directory / 'tampered'
        target.mkdir()
        extract_archive(Path(self.result['archive']), target)
        with (target / 'frontend/showcase/app.js').open('a') as output:
            output.write('\n// unexpected modification\n')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            verify_directory(target)

    def test_summary_label_cannot_hide_a_missing_sequence_answer(self):
        data = json.loads((ROOT / 'frontend/showcase/pipeline.json').read_text())
        result = data['examples']['national-2025-q16']['liangliang']['answer_json']
        result['final_answer'] = '各块答案汇总'
        for chunk in result['chunk_results']:
            chunk['final_answer'] = '0'
        path = self.directory / 'missing-sequence-answer.json'
        path.write_text(json.dumps(data))
        def source(root, name):
            return path if name == 'frontend/showcase/pipeline.json' else checked_file(root, name)
        with patch('scripts.build_research_release.checked_file', side_effect=source):
            with self.assertRaisesRegex(ValueError, 'Sequence final answer'):
                validate_content(ROOT)

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
