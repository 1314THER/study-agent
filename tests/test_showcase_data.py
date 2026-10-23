"""Verify public examples retain their mathematics and existing relationships."""
import json
import math
import re
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from backend.demo_presets import get_preset
from scripts.build_showcase_data import build, asset_sources

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
        for frame in geometry['scenes'][0].get('frames',[geometry['scenes'][0]]):
            points={o['id']:o['coords'] for o in frame['objects'] if o['kind']=='point'}
            for point in ('E','F','G','H'):
                self.assertAlmostEqual(points[point][2],frame['value'])
            for a,b in [('E','F'),('F','G'),('G','H'),('H','E')]:
                self.assertAlmostEqual(math.dist(points[a],points[b]),2)
        self.assertNotIn('section',geometry['steps'][0]['full_visible'])
        self.assertIn('section',geometry['steps'][1]['full_visible'])

    def test_ellipse_focus_lengths_and_right_angle_match_the_prepared_proof(self):
        example=next(e for e in self.data['geometry_examples'] if e['id']=='ellipse-focus')
        self.assertIn('自拟',example['source'])
        geometry=example['answer_json']['geometry']
        self.assertEqual(geometry['status'],'ready');self.assertEqual(geometry['issues'],[])
        for frame in geometry['scenes'][0].get('frames',[geometry['scenes'][0]]):
            points={o['id']:o['coords'] for o in frame['objects'] if o['kind']=='point'}
            x,y=points['P'];self.assertAlmostEqual(x*x/5+y*y,1)
            u=math.dist(points['P'],points['F1']);v=math.dist(points['P'],points['F2'])
            self.assertAlmostEqual(u+v,2*math.sqrt(5));self.assertAlmostEqual(u*v,2)
            self.assertAlmostEqual(u*u+v*v,16)
        self.assertIn('PF1',geometry['steps'][0]['full_visible'])
        self.assertNotIn('PF2',geometry['steps'][0]['full_visible'])
        self.assertIn('PF2',geometry['steps'][1]['full_visible'])
        self.assertIn('一种位置',example['source'])

    def test_pyramid_midpoint_perpendiculars_and_volume_are_semantically_correct(self):
        example=next(e for e in self.data['geometry_examples'] if e['id']=='pyramid-midpoint')
        geometry=example['answer_json']['geometry']
        self.assertEqual(geometry['status'],'ready');self.assertEqual(geometry['issues'],[])
        for frame in geometry['scenes'][0].get('frames',[geometry['scenes'][0]]):
            points={o['id']:o['coords'] for o in frame['objects'] if o['kind']=='point'}
            a,b,c,p,e=[points[k] for k in ('A','B','C','P','E')]
            for left,right in [(a,b),(a,c),(b,c),(p,a),(p,b)]:self.assertAlmostEqual(math.dist(left,right),2)
            self.assertAlmostEqual(math.dist(p,c),math.sqrt(6))
            self.assertEqual(e,[(x+y)/2 for x,y in zip(a,b)])
            pe=[x-y for x,y in zip(p,e)];ab=[x-y for x,y in zip(b,a)];ce=[x-y for x,y in zip(c,e)]
            self.assertAlmostEqual(sum(x*y for x,y in zip(pe,ab)),0)
            self.assertAlmostEqual(sum(x*y for x,y in zip(pe,ce)),0)
            ac=[x-y for x,y in zip(c,a)];ap=[x-y for x,y in zip(p,a)]
            cross=[ab[1]*ac[2]-ab[2]*ac[1],ab[2]*ac[0]-ab[0]*ac[2],ab[0]*ac[1]-ab[1]*ac[0]]
            volume=abs(sum(x*y for x,y in zip(cross,ap)))/6
            self.assertAlmostEqual(volume,1)
        self.assertEqual(geometry['steps'][0]['full_visible'],['E','PE'])
        self.assertNotIn('CE',geometry['steps'][0]['full_visible'])
        self.assertNotIn('base-area',geometry['steps'][2]['full_visible'])
        self.assertIn('base-area',geometry['steps'][3]['full_visible'])

    def test_geometry_hint_groups_only_reveal_current_or_previous_constructions(self):
        self.assertEqual(len(self.data['geometry_examples']),3)
        for example in self.data['geometry_examples']:
            answer=example['answer_json'];geometry=answer['geometry']
            text_keys={f"{c['chunk_id']}-{s['step_number']}" for c in answer['chunk_results'] for s in c['steps']}
            self.assertEqual(text_keys,{s['step_key'] for s in geometry['steps']})
            for step in geometry['steps']:
                for group in step['hint_groups']:
                    self.assertTrue(set(group['visible'])<=set(step['full_visible']))
                    self.assertTrue(group['text'])
            self.assertNotIn('script',geometry)

    def test_prepared_teaching_and_self_authored_transfer_keep_domain_and_solution(self):
        teaching=self.data['teaching']
        self.assertEqual(len(teaching['steps']),3)
        self.assertIn('预制',teaching['label_note'])
        self.assertIn('x>1',teaching['steps'][1]['standard_writing'])
        self.assertIn('交集',teaching['steps'][2]['standard_writing'])
        variant=teaching['variant']
        self.assertIn('自拟',variant['source']);self.assertEqual(variant['answer'],'$(1,2)$')
        for x in (1.01,1.5,1.99):self.assertLess(math.log2(3*x-3),math.log2(x+1))
        for x in (2,2.1,5):self.assertGreaterEqual(math.log2(3*x-3),math.log2(x+1))
        self.assertLessEqual(3*1-3,0)

    def test_pool_evidence_is_manually_prepared_and_uses_only_known_routines(self):
        known={r['id'] for r in self.data['catalog']['routines']}
        self.assertEqual(len(self.data['pool_examples']),3)
        for example in self.data['pool_examples']:
            self.assertEqual(example['review_status'],'预制审核样例')
            self.assertIn('人工编排',example['match']['status'])
            self.assertIn(example['routine_id'],known)
            self.assertTrue(set(example['match']['auxiliary_ids'])<=known)
            self.assertEqual(example['routine_id'],example['match']['primary_id'])
            self.assertTrue(example['match']['evidence_fragments'])
            self.assertNotIn('owner_question_id',example)
            if example.get('original_page_url'):
                self.assertTrue(example['original_page_url'].startswith('/showcase/assets/'))
                self.assertIn('非原卷扫描件',example['original_page_label'])
                self.assertEqual(example['correct_option'],'B')

    def test_question_vectors_are_reproducible_self_authored_and_have_no_active_content(self):
        originals=asset_sources()
        self.assertEqual(set(originals),{'ellipse-question.svg','ellipse-page.svg','pyramid-question.svg','pyramid-page.svg'})
        for filename,source in originals.items():
            self.assertEqual((ROOT/'frontend/showcase/assets'/filename).read_text(),source)
            tree=ET.fromstring(source)
            self.assertTrue(tree.tag.endswith('svg'))
            self.assertIn('自拟',source)
            for element in tree.iter():
                self.assertNotIn(element.tag.split('}')[-1],('script','foreignObject','iframe','image'))
                self.assertFalse(any(k.lower().startswith('on') or k.endswith('href') for k in element.attrib))
            if filename.endswith('-page.svg'):self.assertIn('非高考原卷扫描件',source)

    def test_progress_labels_local_automation_without_claiming_server_or_human_success(self):
        progress=self.data['progress']
        self.assertEqual(progress['as_of'],'2026-10-13');self.assertEqual(progress['scope'],'本机快照')
        self.assertEqual(progress['pool_items'],23255)
        self.assertEqual(progress['classified']+progress['errors'],progress['pool_items'])
        self.assertEqual(progress['primary_matches'],17005)
        self.assertEqual(progress['human_confirmed'],0)
        self.assertFalse(progress['server_import_confirmed'])
        self.assertIn('待人工审核',progress['note'])
        self.assertNotIn('accuracy',progress)

    def test_library_keeps_public_fixed_questions_and_marks_prepared_schedules(self):
        library=self.data['library']
        self.assertEqual(len(library['items']),6)
        self.assertEqual(library['question_ids'],[q['id'] for q in library['items']])
        self.assertTrue(all(q['prepared_example'] for q in library['items']))
        for entry in library['calendar']:
            self.assertRegex(entry['date'],r'^2026-10-\d{2}$')
            self.assertIn(entry['view'],('diagnosis','teaching'))
            self.assertTrue(any(word in entry['note'] for word in ('预制','自拟')))
        self.assertEqual(library['student_pdf'],'/showcase/assets/student-paper.pdf')
        self.assertEqual(library['teacher_pdf'],'/showcase/assets/teacher-paper.pdf')

    def test_reference_catalog_and_confusable_links_are_exact_existing_content(self):
        original=json.loads((ROOT/'backend/routine_catalog.json').read_text())
        self.assertEqual(self.data['catalog'],original)
        known={r['id'] for r in original['routines']}
        self.assertEqual(len(known),len(original["routines"]))
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
