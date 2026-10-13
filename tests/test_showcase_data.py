"""Verify public examples retain their mathematics and existing relationships."""
import json
import math
import re
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch

from backend.demo_presets import get_preset
from scripts.build_showcase_data import build

ROOT=Path(__file__).resolve().parents[1]


class ShowcaseDataTests(unittest.TestCase):
    def setUp(self):
        self.data=json.loads((ROOT/'frontend/showcase/data.json').read_text())

    def test_build_is_reproducible_and_never_reads_private_databases(self):
        with patch.object(sqlite3,'connect',side_effect=AssertionError('Private DB access')):
            self.assertEqual(self.data,build())
        for example in self.data['examples']:
            self.assertEqual(example,get_preset(example['id']))

    def test_cube_sections_are_coplanar_and_keep_area_in_every_compiled_frame(self):
        geometry=self.data['geometry']['answer_json']['geometry']
        self.assertEqual(geometry['status'],'ready');self.assertEqual(geometry['issues'],[])
        for frame in geometry['scenes'][0]['frames']:
            points={o['id']:o['coords'] for o in frame['objects'] if o['kind']=='point'}
            for point in ('E','F','G','H'):
                self.assertAlmostEqual(points[point][2],frame['value'])
            for a,b in [('E','F'),('F','G'),('G','H'),('H','E')]:
                self.assertAlmostEqual(math.dist(points[a],points[b]),2)
        self.assertNotIn('section',geometry['steps'][0]['full_visible'])
        self.assertIn('section',geometry['steps'][1]['full_visible'])

    def test_reference_catalog_and_confusable_links_are_exact_existing_content(self):
        original=json.loads((ROOT/'backend/routine_catalog.json').read_text())
        self.assertEqual(self.data['catalog'],original)
        known={r['id'] for r in original['routines']}
        self.assertEqual(len(known),288)
        for routine in original['routines']:
            self.assertTrue(set(routine['confusable_ids'])<=known)

    def test_diagnosis_demonstrates_a_domain_omission_without_inventing_a_score(self):
        diagnosis=self.data['diagnosis']
        original=get_preset('shanghai-2024-q18')['question']
        self.assertIn(original.split('\n')[0],diagnosis['question'])
        self.assertEqual(diagnosis['first_error'],1)
        self.assertIn('x>1',diagnosis['evidence']);self.assertIn('(1,2)',diagnosis['evidence'])
        self.assertNotIn('score',diagnosis)
        for x in (1.1,1.5,1.9):
            self.assertLess(math.log2(2*x-2),math.log2(x))
        self.assertLessEqual(2*.5-2,0)  # Student's broader interval includes undefined logs.

    def test_public_data_excludes_application_contacts_and_private_state(self):
        text=json.dumps(self.data,ensure_ascii=False)
        for value in ('@m.fudan.edu.cn','DEEPSEEK_API_KEY','worker_pid','job_id','review_runs','/Users/'):
            self.assertNotIn(value,text)
        def inspect(value, key=''):
            if isinstance(value,dict):
                for field,child in value.items():inspect(child,field)
            elif isinstance(value,list):
                for child in value:inspect(child,key)
            elif isinstance(value,str) and key!='url':
                self.assertIsNone(re.search(r'(?<!\d)\d{11}(?!\d)',value))
        inspect(self.data)


if __name__=='__main__':unittest.main()
