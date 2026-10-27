import copy
from decimal import Decimal
import hashlib
import html
from html.parser import HTMLParser
import json
import re
import unittest
from urllib.parse import urlsplit

from scripts.build_research_showcase import CHAPTER_IDS, PUBLIC, ROOT, TOPIC_IDS, TOPICS, build, validate_source_map
from scripts.showcase_vision import validate_vision


class VisionChangeParser(HTMLParser):
    """Read each delivered teaching chain without executing client scripts."""

    def __init__(self):
        super().__init__()
        self.groups = []
        self.changes = []
        self.group = self.change = self.link = None
        self.article_depth = 0

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if attributes.get('data-vision-group'):
            self.group = attributes['data-vision-group']
            self.groups.append(self.group)
        if tag == 'article':
            if self.change is not None:
                self.article_depth += 1
            elif 'vision-change' in attributes.get('class', '').split():
                self.change = {'group': self.group, 'text': '', 'links': [], 'hidden': False, 'tags': []}
                self.changes.append(self.change)
                self.article_depth = 1
        if self.change is not None:
            self.change['tags'].append(tag)
            if 'hidden' in attributes and tag != 'button':
                self.change['hidden'] = True
            if tag == 'a':
                self.link = {'target': attributes.get('href'), 'text': ''}
                self.change['links'].append(self.link)
            if attributes.get('data-feature-state') and self.change['links']:
                self.change['links'][-1]['status'] = attributes['data-feature-state']

    def handle_data(self, data):
        if self.change is not None:
            self.change['text'] += data
        if self.link is not None:
            self.link['text'] += data

    def handle_endtag(self, tag):
        if tag == 'a':
            self.link = None
        elif tag == 'article' and self.change is not None:
            self.article_depth -= 1
            if not self.article_depth:
                self.change = self.link = None


class ResearchShowcaseBuildTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.content = json.loads((PUBLIC / 'research-content.json').read_text())
        cls.source_map = json.loads((ROOT / 'docs/showcase-content-map.json').read_text())
        cls.vision = json.loads((PUBLIC / 'vision-content.json').read_text())

    def test_full_source_map_and_hashes_are_current(self):
        validate_source_map(self.content, self.source_map)

    def test_research_buttons_have_complete_editorial_summaries(self):
        page = build(self.content)
        studies = [study for chapter in self.content['chapters'] for study in chapter.get('research', [])]
        self.assertEqual(len(studies), 18)
        self.assertEqual(page.count('data-study-summary='), 18)
        for study in studies:
            self.assertTrue(study['short_summary'].endswith('。'))
            self.assertIn('data-study-summary="' + html.escape(study['short_summary'], quote=True) + '"', page)
        for invalid in ('', '尚未完成的摘要', '字' * 72 + '。'):
            changed = copy.deepcopy(self.content)
            next(chapter for chapter in changed['chapters'] if chapter['research'])['research'][0]['short_summary'] = invalid
            with self.subTest(summary=invalid), self.assertRaisesRegex(ValueError, 'Research short summary'):
                validate_source_map(changed, self.source_map)

    def test_source_hash_change_blocks_regeneration(self):
        changed = copy.deepcopy(self.source_map)
        changed['chapters'][0]['sources'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Source hash changed'):
            validate_source_map(self.content, changed)

    def test_all_chapters_are_readable_without_client_rendering(self):
        page = build(self.content)
        self.assertEqual(page.count('class="topic-section"'), 10)
        self.assertEqual(page.count('class="topic-section highlights-topic"'), 1)
        self.assertEqual(page.count('class="topic-section vision-topic"'), 1)
        self.assertEqual(len(re.findall(r'<section class="topic-section(?: [^"]+)?"', page)), 12)
        self.assertEqual([chapter['id'] for chapter in self.content['chapters']], CHAPTER_IDS)
        self.assertEqual(len(self.content['chapters']), 15)
        self.assertEqual(len(re.findall(r'<section class="topic-unit(?: [^"]+)?"', page)), 13)
        self.assertEqual(len(re.findall(r'<article class="perspective-cell(?: shared-cell)?"', page)), 19)
        self.assertNotIn('unit-tech-fold', page)
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
        single = next(chapter for chapter in self.content['chapters'] if chapter['id'] == 'single')
        self.assertIn(single['title'], page)
        self.assertIn('论文原文', page)
        self.assertEqual(len(re.findall(r'<a class="chapter-transition(?: [^"]+)?"', page)), 12)
        self.assertEqual(len(re.findall(r'<div class="chapter-bridge(?: [^"]+)?"', page)), 12)
        self.assertEqual(page.count('class="pain-point"'), 13)
        self.assertEqual(page.count('class="research-logic"'), 18)
        self.assertIn('id="launch-screen"', page)
        self.assertIn('id="launch-title"', page)
        self.assertIn('<h2 id="launch-title"', page)
        self.assertIn('<h1 id="heading-vision"', page)
        self.assertIn('<h2 id="heading-highlights"', page)
        self.assertEqual(len(re.findall(r'<h1\b', page)), 1)
        self.assertNotIn('id="reading-progress"', page)
        self.assertIn('id="hero-art"', page)
        self.assertIn('class="hero-love"', page)
        self.assertIn('id="hero-ink-path"', page)
        self.assertIn('id="explore-start"', page)
        self.assertRegex(page, r'<a id="explore-start"[^>]* href="#vision"')
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
        self.assertLess(launch_end, page.index('id="vision"'))
        self.assertLess(page.index('id="vision"'), page.index('id="highlights"'))
        self.assertLess(page.index('id="terms"'), page.index('id="single"'))
        self.assertIn('id="scene-dataset"', page)
        self.assertIn('href="#highlights"', page)
        self.assertEqual(page.count('class="dataset-metric"'), 4)
        for value in ('541', '359', '1,019', '23,261'):
            self.assertIn('>' + value + '</dd>', page)
        self.assertEqual(len(re.findall(r'<a class="[^"]*\barchitecture-node\b[^"]*"', page)), 13)
        self.assertEqual(re.findall(r'<a class="architecture-node hx-system-node" href="([^"]+)"', page),
                         ['#terms', '#terms', '#terms', '#terms',
                          '#single', '#time', '#library', '#exam', '#longterm',
                          '#teacher', '#school', '#agent', '#evolution'])
        for word in ('课时', '知识点', '步骤', '套路'):
            self.assertIn('<strong>' + word + '</strong>', page)
        self.assertEqual(re.findall(r'data-hx-motion="([^"]+)"', page),
                         ['system', 'method', 'time', 'ability', 'data', 'participation', 'evolution'])
        self.assertIn('data-hx-dimension="5"', page)
        self.assertIn('data-hx-evidence="5"', page)
        self.assertIn('data-hx-axis="5"', page)
        self.assertIn('data-hx-method="2"', page)
        primary_nav = re.search(r'<nav class="primary-nav".*?</nav>', page, re.S).group(0)
        self.assertEqual(re.findall(r'<a href="#([^"]+)"', primary_nav), TOPIC_IDS)
        self.assertEqual(len(TOPICS), 12)
        self.assertEqual(TOPIC_IDS[:2], ['vision', 'highlights'])
        self.assertNotRegex(primary_nav, r'<span[^>]*>\s*\d+')
        self.assertNotRegex(page, r'\bU\d{2}\b')
        self.assertNotIn('批注号', page)
        self.assertNotRegex(page, r'<span class="highlight-index">\s*0?\d+[/、.]')
        self.assertIn('>二级步骤</dt>', page)
        self.assertNotIn('保留题型与父步骤作用域', page)

    def test_vision_is_independent_of_the_fifteen_research_units(self):
        self.assertNotIn('vision', self.content)
        self.assertNotIn('vision', CHAPTER_IDS)
        self.assertEqual(TOPICS[0]['sources'], [])
        mapping = self.source_map['vision']
        self.assertEqual(mapping['content_file'], 'frontend/showcase/vision-content.json')
        self.assertEqual(mapping['content_sha256'], hashlib.sha256((PUBLIC / 'vision-content.json').read_bytes()).hexdigest())
        self.assertEqual([source['file'] for source in mapping['sources']], self.vision['source_docs'])
        self.assertEqual(mapping['sources'][0]['file'], 'docs/教学愿景与社会价值.md')
        self.assertEqual(mapping['counts'], {'students': 21, 'teachers': 17, 'schools': 17, 'society': 8})
        self.assertEqual(self.vision['status'], '教学愿景')
        self.assertEqual(self.vision['headline'], '让每个学生，都能获得适合自己的学习支持。')
        self.assertIn('大语言模型', self.vision['subtitle'])
        self.assertNotIn('LLM大模型', self.vision['subtitle'])
        self.assertEqual(self.content['highlights']['manifesto_en'], 'The purpose of AI is not to assist humanity, but to surpass it.')
        self.assertIn(self.content['highlights']['manifesto_en'], build(self.content))

    def test_vision_content_hash_change_blocks_regeneration(self):
        changed = copy.deepcopy(self.source_map)
        changed['vision']['content_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Vision content changed'):
            validate_source_map(self.content, changed)

    def test_vision_source_hash_change_blocks_regeneration(self):
        changed = copy.deepcopy(self.source_map)
        changed['vision']['sources'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'Vision source hash changed'):
            validate_source_map(self.content, changed)

    def test_vision_sources_require_full_reading_and_their_line_counts(self):
        for field, value, message in (
                ('read_completeness', 'partial', 'Vision source was not fully read'),
                ('line_count', 0, 'Vision source hash changed')):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.source_map)
                changed['vision']['sources'][0][field] = value
                with self.assertRaisesRegex(ValueError, message):
                    validate_source_map(self.content, changed)

    def test_all_63_vision_changes_have_complete_readable_chains_without_javascript(self):
        page = re.sub(r'<script\b[^>]*>.*?</script>', '', build(self.content), flags=re.S)
        parser = VisionChangeParser()
        parser.feed(page)
        counts = {'students': 21, 'teachers': 17, 'schools': 17, 'society': 8}
        self.assertEqual([group['id'] for group in self.vision['groups']], list(counts))
        self.assertEqual(parser.groups, list(counts))
        self.assertEqual(len(parser.changes), 63)
        for group in self.vision['groups']:
            with self.subTest(group=group['id']):
                changes = [change for change in parser.changes if change['group'] == group['id']]
                self.assertEqual(len(group['rows']), counts[group['id']])
                self.assertEqual(len(changes), counts[group['id']])
                for source, change in zip(group['rows'], changes):
                    self.assertEqual(set(source), {'aspect', 'before', 'after', 'features', 'short_vision'})
                    self.assertFalse(change['hidden'])
                    for field in ('aspect', 'before', 'after'):
                        self.assertIn(source[field], change['text'])
                    self.assertLess(change['text'].index(source['before']), change['text'].index(source['after']))
                    self.assertTrue(source['features'])
                    for feature in source['features']:
                        links = [link for link in change['links'] if feature['label'] in link['text']]
                        self.assertEqual(len(links), 1)
                        self.assertEqual(links[0]['target'], feature['target'])
                        self.assertEqual(links[0].get('status'), feature['status'])
                        self.assertIn(feature['status'], change['text'])
                    self.assertNotIn('table', change['tags'])
        vision_start, highlights_start = page.index('id="vision"'), page.index('id="highlights"')
        self.assertLess(vision_start, highlights_start)
        self.assertIn(html.escape(self.vision['subtitle']), page[vision_start:highlights_start])
        self.assertIn('<details class="vision-fallback"', page[vision_start:highlights_start])
        self.assertNotIn('<table', page[vision_start:highlights_start])

    def test_vision_galaxies_retain_all_short_cards_and_native_fallbacks(self):
        page = build(self.content)
        self.assertEqual(page.count('class="vision-card"'), 63)
        self.assertEqual(page.count('class="vision-fallback"'), 63)
        self.assertNotIn('vision-disclosure', page)
        self.assertIn('id="vision-dialog"', page)
        self.assertIn('aria-labelledby="vision-dialog-title"', page)
        for group in self.vision['groups']:
            for index, row in enumerate(group['rows'], 1):
                self.assertTrue(0 < len(row['short_vision']) <= 14)
                self.assertIn(html.escape(row['short_vision']), page)
                self.assertIn('id="vision-change-' + group['id'] + '-' + str(index) + '"', page)

    def test_vision_feature_states_and_targets_link_to_existing_topics(self):
        page = build(self.content)
        ids = set(re.findall(r'\bid="([^"]+)"', page))
        allowed_targets = {'#' + key for key in TOPIC_IDS if key != 'vision'}
        states = set()
        for group in self.vision['groups']:
            for row in group['rows']:
                for feature in row['features']:
                    with self.subTest(group=group['id'], aspect=row['aspect'], feature=feature['label']):
                        self.assertEqual(set(feature), {'label', 'target', 'status'})
                        self.assertIn(feature['target'], allowed_targets)
                        self.assertIn(feature['target'][1:], ids)
                        self.assertIn(feature['status'], {'已有基础', '设计方案', '研究方向'})
                        self.assertIn('href="' + feature['target'] + '"', page)
                        states.add(feature['status'])
        self.assertEqual(states, {'已有基础', '设计方案', '研究方向'})

    def test_incomplete_or_untraceable_vision_content_is_rejected(self):
        cases = (
            ('missing row', lambda value: value['groups'][0]['rows'].pop(), 'Incomplete vision comparisons'),
            ('missing column', lambda value: value['groups'][0]['rows'][0].pop('after'), 'all four columns'),
            ('missing short vision', lambda value: value['groups'][0]['rows'][0].pop('short_vision'), 'all four columns'),
            ('long short vision', lambda value: value['groups'][0]['rows'][0].update(short_vision='字' * 15), 'fourteen characters'),
            ('unknown target', lambda value: value['groups'][0]['rows'][0]['features'][0].update(target='#absent-topic'), 'Unknown vision feature target'),
            ('unqualified status', lambda value: value['groups'][0]['rows'][0]['features'][0].update(status='全部实现'), 'implementation status'),
        )
        for name, change, message in cases:
            with self.subTest(case=name):
                value = copy.deepcopy(self.vision)
                change(value)
                with self.assertRaisesRegex(ValueError, message):
                    validate_vision(value)

    def test_vision_has_one_floating_skip_link_before_its_content(self):
        page = build(self.content)
        skip_links = re.findall(r'<a class="vision-skip"[^>]*\bdata-vision-skip\b[^>]*>.*?</a>', page)
        self.assertEqual(len(skip_links), 1)
        self.assertIn('href="#highlights"', skip_links[0])
        self.assertIn('跳过愿景，查看项目亮点', skip_links[0])
        self.assertLess(page.index(skip_links[0]), page.index('id="vision"'))

    def test_model_cost_example_uses_the_published_rates_and_exact_arithmetic(self):
        price = self.vision['cost_estimate']
        self.assertEqual((price['model'], price['currency']), ('GLM-5.3-Flash', 'CNY'))
        self.assertEqual((price['input_per_million'], price['output_per_million']), (0.8, 2.8))
        self.assertEqual((price['input_tokens'], price['output_tokens']), (10000, 2000))
        # Six study days plus one rest day per week, as confirmed by the project owner.
        self.assertEqual((price['daily_interactions'], price['days']), (200, 6))
        cost = (Decimal(str(price['input_per_million'])) * price['input_tokens']
                + Decimal(str(price['output_per_million'])) * price['output_tokens']) / 1000000
        weekly = cost * price['daily_interactions'] * price['days']
        self.assertEqual(cost, Decimal('0.0136'))
        self.assertEqual(weekly, Decimal('16.32'))
        self.assertEqual(price['source'], 'https://docs.bigmodel.cn/cn/guide/start/pricing')
        page = build(self.content)
        self.assertIn('¥0.0136', page)
        self.assertIn('每天 200 次，连续 6 天（一周）', page)
        self.assertIn('约 ¥16.32 / 周 / 人', page)
        self.assertIn('10,000 输入 + 2,000 输出 Token / 次', page)
        self.assertIn('模型 API 费用', page)
        self.assertIn('完整服务预算', page)
        self.assertIn('href="' + price['source'] + '"', page)

    def test_three_policy_connections_keep_official_sources_and_their_scope(self):
        expected = [
            'https://www.moe.gov.cn/jyb_xxgk/moe_1777/moe_1778/202107/t20210724_546576.html?type=2',
            'https://hudong.moe.gov.cn/srcsite/A01/s7048/202504/t20250416_1187476.html',
            'https://www.gov.cn/zhengce/202501/content_6999913.htm',
        ]
        self.assertEqual([policy['url'] for policy in self.vision['policies']], expected)
        page = build(self.content)
        policy_markup = re.search(r'<section class="vision-policy".*?</section>', page, re.S).group(0)
        self.assertEqual(policy_markup.count('<article>'), 3)
        for policy in self.vision['policies']:
            self.assertIn(urlsplit(policy['url']).hostname, {'www.moe.gov.cn', 'hudong.moe.gov.cn', 'www.gov.cn'})
            self.assertTrue(policy['mechanism'])
            self.assertTrue(policy['scope'])
            self.assertIn('href="' + html.escape(policy['url'], quote=True) + '"', policy_markup)
            self.assertIn(html.escape(policy['document']), policy_markup)
            self.assertIn(policy['url'], self.source_map['vision']['public_sources'])
        self.assertIn('义务教育', self.vision['policies'][0]['scope'])
        self.assertIn('普通高中', self.vision['policies'][0]['scope'])

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
