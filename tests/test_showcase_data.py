"""National examples preserve production answers and label illustrative content."""
import hashlib
from datetime import datetime
import json
import math
from pathlib import Path
import re
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from backend.demo_presets import get_preset
from backend.showcase_bank import verify
from scripts.build_showcase_data import build, write_national_bank

ROOT = Path(__file__).resolve().parents[1]


class ShowcaseDataTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT/'frontend/showcase/data.json').read_text())

    def test_build_is_reproducible_without_opening_any_private_database(self):
        snapshot_day = datetime.fromisoformat(self.data['progress']['as_of']).astimezone()
        with patch.object(sqlite3, 'connect', side_effect=AssertionError('Private DB access')), \
                patch('scripts.build_showcase_data.datetime') as clock:
            clock.now.return_value = snapshot_day
            self.assertEqual(self.data, build())

    def test_both_examples_retain_exact_complete_production_answer(self):
        self.assertEqual([row['id'] for row in self.data['examples']], ['national-2023-q17', 'national-2025-q16'])
        runs = json.loads((ROOT/'frontend/showcase/pipeline.json').read_text())['examples']
        for example in self.data['examples']:
            original = get_preset(example['id'])
            self.assertEqual(example['question'], original['question'])
            self.assertEqual(example['source'], original['source'])
            self.assertIn('全国', example['source']['paper'])
            self.assertEqual(example['answer_json'], runs[example['id']]['xuefeng']['answer_json'])
            self.assertEqual(example['recording']['fingerprint'], runs[example['id']]['xuefeng']['fingerprint'])
            self.assertFalse(example['prepared_example'])

    def test_retired_question_and_fixed_logarithm_branches_are_absent(self):
        public = {key: self.data[key] for key in self.data if key != 'catalog'}
        text = json.dumps(public, ensure_ascii=False)
        for retired in ('上海', 'shanghai', '巴蜀', 'ellipse-focus', 'cube-section', 'pyramid-midpoint', 'log_a', '真数'):
            self.assertNotIn(retired, text)
        self.assertEqual(self.data['pool_examples'], [])
        self.assertEqual(self.data['library']['question_ids'], ['national-2023-q17', 'national-2025-q16'])
        self.assertNotIn('student_pdf', self.data['library'])
        self.assertNotIn('teacher_pdf', self.data['library'])

    def test_triangle_coordinates_reproduce_national_angles_and_height(self):
        example = self.data['geometry']
        self.assertTrue(example['prepared_diagram'])
        self.assertEqual(example['source_meta']['year'], 2023)
        geometry = example['answer_json']['geometry']
        self.assertEqual(geometry['status'], 'ready')
        self.assertEqual(geometry['issues'], [])
        points = {o['id']:o['coords'] for o in geometry['scenes'][0]['objects'] if o['kind'] == 'point'}
        a,b,c,d = [points[k] for k in ('A','B','C','D')]
        self.assertAlmostEqual(math.dist(a,b), 5)
        self.assertAlmostEqual(math.dist(c,d), 6)
        self.assertAlmostEqual(math.dist(a,c), 2*math.sqrt(10))
        sin_a = c[1]/math.dist(a,c)
        self.assertAlmostEqual(sin_a, 3*math.sqrt(10)/10)
        ca = [a[i]-c[i] for i in range(2)]
        cb = [b[i]-c[i] for i in range(2)]
        cos_c = sum(x*y for x,y in zip(ca,cb))/(math.dist(a,c)*math.dist(b,c))
        angle_c = math.acos(cos_c)
        self.assertAlmostEqual(angle_c, math.pi/4)
        angle_a = math.atan2(c[1],c[0])
        angle_b = math.pi-angle_a-angle_c
        self.assertAlmostEqual(angle_a+angle_b, 3*angle_c)
        self.assertAlmostEqual(2*math.sin(angle_a-angle_c), math.sin(angle_b))
        # The derived altitude may not appear before the second sub-question.
        for step in geometry['steps']:
            if step['step_key'].startswith('1-'):
                self.assertNotIn('CD', step['full_visible'])
            else:
                self.assertIn('CD', step['full_visible'])
        self.assertEqual(len(self.data['geometry_examples']), 1)

    def test_teaching_is_labeled_schematic_and_scaled_variant_is_correct(self):
        teaching = self.data['teaching']
        self.assertTrue(teaching['prepared_example'])
        self.assertIn('人工编排', teaching['label_note'])
        self.assertIn('不是真实', teaching['label_note'])
        self.assertEqual(len(teaching['steps']), 3)
        self.assertIn('4C', teaching['steps'][0]['standard_writing'])
        self.assertEqual(teaching['steps'][-1]['right_answer'], '$h=6$')
        variant = teaching['variant']
        self.assertEqual(variant['reference_id'], 'national-2023-q17')
        self.assertIn('原创', variant['source'])
        self.assertIn('不是模型生成结果', variant['source'])
        self.assertEqual(variant['answer'], '$12$')
        self.assertAlmostEqual(6*(10/5), 12)

    def test_constructed_diagnosis_separates_first_error_from_cause(self):
        diagnosis = self.data['diagnosis']
        self.assertTrue(diagnosis['prepared_example'])
        self.assertEqual(diagnosis['first_error'], 0)
        self.assertIn('人工构造', diagnosis['student_label'])
        self.assertIn('不是', diagnosis['student_label'])
        self.assertIn('4C', diagnosis['evidence'])
        self.assertIn('不足以', diagnosis['feedback'])
        self.assertNotIn('score', diagnosis)
        self.assertNotIn('cause_confirmed', diagnosis)

    def test_national_bank_rebuild_has_faithful_content_and_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            write_national_bank(self.data['examples'], destination)
            manifest = verify(destination)
            self.assertEqual(manifest['count'], 2)
            details = json.loads((destination/'part-0000.json').read_text())
            for qid, example in zip(('20230117','20250116'), self.data['examples']):
                self.assertEqual(details[qid]['question'], example['question'])
                self.assertEqual(details[qid]['answer'], example['answer_json']['final_answer'])
            for name in ('index.json','part-0000.json','manifest.json'):
                self.assertEqual((destination/name).read_bytes(), (ROOT/'frontend/showcase/question-bank'/name).read_bytes())

    def test_full_reference_catalog_is_retained_without_claiming_verified_mastery(self):
        original = json.loads((ROOT/'backend/routine_catalog.json').read_text())
        self.assertEqual(self.data['catalog'], original)
        known = {r['id'] for r in original['routines']}
        for routine in original['routines']:
            self.assertTrue(set(routine['confusable_ids']) <= known)
        self.assertEqual(self.data['progress']['completed_pipeline_runs'], 8)
        self.assertIn('不是诊断准确率', self.data['progress']['note'])
        self.assertEqual(self.data['library']['calendar'], [])

    def test_public_data_excludes_contacts_credentials_and_private_state(self):
        text = json.dumps(self.data, ensure_ascii=False)
        for value in ('@m.fudan.edu.cn', 'DEEPSEEK_API_KEY', 'worker_pid', 'job_id', 'review_runs', '/Users/'):
            self.assertNotIn(value, text)
        def inspect(value, key=''):
            if isinstance(value, dict):
                for field, child in value.items(): inspect(child, field)
            elif isinstance(value, list):
                for child in value: inspect(child, key)
            elif isinstance(value, str) and key not in ('url','fingerprint','source_hash'):
                self.assertIsNone(re.search(r'(?<!\d)\d{11}(?!\d)', value))
        inspect(self.data)


if __name__ == '__main__':
    unittest.main()
