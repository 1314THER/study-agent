import copy
import hashlib
import json
import unittest

from scripts.build_research_showcase import PUBLIC, ROOT, build, validate_source_map


class ResearchShowcaseBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = json.loads((PUBLIC / 'research-content.json').read_text())
        cls.source_map = json.loads((ROOT / 'docs/showcase-content-map.json').read_text())

    def test_full_source_map_and_hashes_are_current(self):
        validate_source_map(self.content, self.source_map)

    def test_source_hash_change_blocks_regeneration(self):
        changed = copy.deepcopy(self.source_map)
        changed['chapters'][0]['sources'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Source hash changed'):
            validate_source_map(self.content, changed)

    def test_all_chapters_are_readable_without_client_rendering(self):
        page = build(self.content)
        self.assertEqual(page.count('class="chapter chapter-'), 14)
        self.assertIn('同一份解析，连接四种能力', page)
        self.assertIn('论文原文', page)
        self.assertEqual(page.count('class="chapter-transition"'), 14)
        self.assertEqual(page.count('class="chapter-bridge"'), 14)
        self.assertEqual(page.count('class="pain-point"'), 14)
        self.assertEqual(page.count('class="research-logic"'), 14)
        self.assertNotIn('id="opening-skip"', page)
        self.assertNotIn('id="reading-progress"', page)
        self.assertIn('id="opening-enter"', page)
        self.assertIn('study-agent项目介绍页面', page)

    def test_page_content_does_not_select_a_shanghai_exam(self):
        page = build(self.content)
        self.assertNotIn('上海卷', page)
        self.assertNotIn('上海市', page)

    def test_handwriting_font_covers_current_constructed_inputs(self):
        fonts = PUBLIC / 'fonts'
        coverage = json.loads((fonts / 'coverage.json').read_text())
        records_raw = (PUBLIC / 'recordings.json').read_bytes()
        self.assertEqual(coverage['inputs']['recordings_sha256'], hashlib.sha256(records_raw).hexdigest())
        self.assertEqual(coverage['missing_codepoints'], [])
        raw_font = (fonts / coverage['file']).read_bytes()
        self.assertEqual(raw_font[:4], b'wOF2')
        self.assertEqual(hashlib.sha256(raw_font).hexdigest(), coverage['sha256'])
        self.assertIn('SIL OPEN FONT LICENSE Version 1.1', (fonts / 'OFL.txt').read_text())
        self.assertEqual(hashlib.sha256((fonts / 'OFL.txt').read_bytes()).hexdigest(), coverage['license_sha256'])
        records = json.loads(records_raw)
        inputs = [c['student_answer'] for c in records['cases']]
        inputs.extend(f.get('input') or '' for f in records['teaching']['frames'])
        requested = {ord(c) for c in ''.join(inputs) if not c.isspace()}
        self.assertLessEqual(requested, set(coverage['covered_codepoints']))


if __name__ == '__main__':
    unittest.main()
