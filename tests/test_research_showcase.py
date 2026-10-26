import copy
import hashlib
import json
import re
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
        self.assertEqual(page.count('class="topic-section"'), 10)
        self.assertEqual(page.count('class="topic-section highlights-topic"'), 1)
        self.assertEqual(page.count('class="topic-unit"'), 13)
        self.assertEqual(len(re.findall(r'<article class="perspective-cell(?: shared-cell)?"', page)), 26)
        self.assertEqual(page.count('class="perspective-cell shared-cell"'), 0)
        self.assertEqual(page.count('data-perspective="'), 2)
        self.assertIn('data-perspective="teaching"', page)
        self.assertIn('data-perspective="technical"', page)
        self.assertNotIn('data-perspective="mechanism"', page)
        self.assertEqual(page.count('class="topic-unit-grid topic-unit-shared"'), 0)
        self.assertEqual(page.count('class="highlight-point '), 7)
        self.assertEqual(page.count('class="highlight-pain"'), 6)
        self.assertIn('系统设计与研究亮点', page)
        self.assertIn('机制、研究与技术实现', page)
        self.assertIn('对应技术', page)
        self.assertIn('class="research-scope"', page)
        self.assertIn('/showcase/assets/fudan-emblem-white.png', page)
        self.assertIn('同一份解析，连接四种能力', page)
        self.assertIn('论文原文', page)
        self.assertEqual(page.count('class="chapter-transition"'), 11)
        self.assertEqual(page.count('class="chapter-bridge"'), 11)
        self.assertEqual(page.count('class="pain-point"'), 13)
        self.assertEqual(page.count('class="research-logic"'), 18)
        self.assertIn('id="launch-screen"', page)
        self.assertIn('id="launch-title"', page)
        self.assertIn('<h2 id="launch-title"', page)
        self.assertIn('id="heading-highlights"', page)
        self.assertNotIn('id="reading-progress"', page)
        self.assertIn('id="hero-art"', page)
        self.assertIn('class="hero-love"', page)
        self.assertIn('id="hero-ink-path"', page)
        self.assertIn('id="explore-start"', page)
        self.assertIn('href="#highlights"', page)
        self.assertEqual(page.count('href="https://150.chat/"'), 2)
        self.assertEqual(page.count('正式站（正在开发中）'), 2)
        self.assertEqual(page.count('class="launch-contact"'), 1)
        self.assertEqual(page.count('class="site-author"'), 1)
        self.assertEqual(page.count('href="mailto:qzshi25@m.fudan.edu.cn"'), 2)
        launch_start = page.index('id="launch-screen"')
        launch_end = page.index('</dialog>', launch_start)
        self.assertIn('施棋智', page[launch_start:launch_end])
        author_start = page.index('class="site-author"')
        author_end = page.index('</p>', author_start)
        self.assertIn('施棋智', page[author_start:author_end])
        for launch_element in ('id="launch-title"', 'id="hero-art"', 'id="hero-ink-path"', 'id="explore-start"'):
            self.assertGreater(page.index(launch_element), launch_start)
            self.assertLess(page.index(launch_element), launch_end)
        self.assertIn('id="scene-overview"', page)
        self.assertIn('id="scene-dataset"', page)
        self.assertIn('查看数据集规模', page)
        self.assertNotIn('inline-dataset-goals', page)
        self.assertLess(page.index('id="highlights"'), page.index('id="terms"'))
        self.assertLess(page.index('id="terms"'), page.index('id="single"'))
        self.assertIn('id="scene-dataset"', page)
        self.assertIn('href="#highlights"', page)
        self.assertEqual(page.count('class="dataset-metric"'), 4)
        for value in ('541', '359', '1,019', '23,261'):
            self.assertIn('>' + value + '</dd>', page)
        self.assertEqual(len(re.findall(r'<a class="[^"]*\barchitecture-node\b[^"]*"', page)), 10)
        self.assertEqual(re.findall(r'<a class="architecture-node hx-system-node" href="([^"]+)"', page),
                         ['#terms', '#single', '#time', '#library', '#exam', '#longterm',
                          '#teacher', '#school', '#agent', '#evolution'])
        self.assertEqual(re.findall(r'data-hx-motion="([^"]+)"', page),
                         ['system', 'method', 'time', 'ability', 'data', 'participation', 'evolution'])
        self.assertIn('data-hx-dimension="5"', page)
        self.assertIn('data-hx-evidence="5"', page)
        self.assertIn('data-hx-axis="5"', page)
        self.assertIn('data-hx-method="2"', page)
        primary_nav = re.search(r'<nav class="primary-nav".*?</nav>', page, re.S).group(0)
        self.assertNotRegex(primary_nav, r'<span[^>]*>\s*\d+')
        self.assertNotRegex(page, r'\bU\d{2}\b')
        self.assertNotIn('批注号', page)
        self.assertNotRegex(page, r'<span class="highlight-index">\s*0?\d+[/、.]')
        self.assertIn('>二级步骤</dt>', page)
        self.assertNotIn('保留题型与父步骤作用域', page)

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
