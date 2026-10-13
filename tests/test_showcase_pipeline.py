"""Check the exported production runs are complete and mathematically consistent."""
import json
from pathlib import Path
import re
import unittest

ROOT=Path(__file__).resolve().parents[1]


class ShowcasePipelineTests(unittest.TestCase):
    def test_all_three_questions_have_four_distinct_completed_runs(self):
        data=json.loads((ROOT/'frontend/showcase/pipeline.json').read_text())
        self.assertEqual(set(data['examples']),{'national-2025-q16','national-2023-q17','shanghai-2024-q18'})
        for example,runs in data['examples'].items():
            self.assertEqual(set(runs),{'liangliang','taotao','xuefeng','ji'})
            answers=[]
            for teacher,run in runs.items():
                result=run['answer_json']
                self.assertEqual(result['source'],'pipeline');self.assertEqual(result['teacher'],teacher)
                self.assertNotIn('error',result);self.assertFalse(result.get('formatter_fallback'))
                chunks=result['chunk_results'];self.assertEqual(len(chunks),2)
                self.assertEqual(len({c['chunk_id'] for c in chunks}),2)
                for chunk in chunks:
                    for step in chunk['steps']:
                        for field in ('title','standard_writing','detailed_writing'):
                            self.assertTrue(step.get(field), (example,teacher,field))
                        self.assertEqual(len(step['step_difficulty']['dimensions']),5)
                for stage in ('solver','verifier','formatter'):
                    self.assertTrue(run['stages'][stage]['content'])
                    self.assertGreater(run['stages'][stage]['usage']['total_tokens'],0)
                self.assertGreater(result['token_usage']['total_tokens'],0)
                final=re.sub(r'\s+','',result['final_answer'])
                if example=='national-2025-q16':self.assertIn('7-(3m+7)(-2)^m',final)
                elif example=='national-2023-q17':self.assertIn('sqrt{10}',final);self.assertIn('6',final)
                else:self.assertIn('(1,2)',final);self.assertTrue('infty' in final)
                answers.append(json.dumps(chunks,ensure_ascii=False,sort_keys=True))
            self.assertEqual(len(set(answers)),4)
