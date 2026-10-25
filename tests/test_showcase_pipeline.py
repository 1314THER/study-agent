"""Check the exported production runs are complete and mathematically consistent."""
import json
import hashlib
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class ShowcasePipelineTests(unittest.TestCase):
    def test_national_questions_have_four_distinct_completed_runs(self):
        data=json.loads((ROOT/'frontend/showcase/pipeline.json').read_text())
        self.assertEqual(set(data['examples']),{'national-2025-q16','national-2023-q17'})
        # Locked before removing the retired local-paper example. These checks
        # protect the complete real responses, usage, timestamps and metadata.
        expected = {
            'national-2025-q16': '8b8117212eb419b51a9d8dbd8a6fe8046b551d04b527ce6d0dedbe6b32a728fa',
            'national-2023-q17': '7c5233bda18c28fdd3243fb35e2eed7343f92a59c5f0cb20c94995e7d4dde9e5',
        }
        for example,runs in data['examples'].items():
            digest = hashlib.sha256(json.dumps(runs, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            self.assertEqual(digest, expected[example], 'Saved production output was rewritten')
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
                    self.assertEqual(run['stages'][stage]['model'], {'liangliang':'glm-4.7-flash','taotao':'deepseek-flash','xuefeng':'glm-5.3-flash','ji':'gpt-6-astra'}[teacher])
                    self.assertEqual(run['stages'][stage]['reasoning_effort'], 'medium')
                    if teacher == 'ji':
                        self.assertEqual(run['stages'][stage]['resolved_model'], 'gpt-6-astra')
                        self.assertEqual(run['stages'][stage]['provider'], 'codex_cli')
                    self.assertGreater(run['stages'][stage]['usage']['total_tokens'],0)
                self.assertGreater(result['token_usage']['total_tokens'],0)
                solution_text = result['final_answer'] + ''.join(
                    chunk.get('final_answer', '') + ''.join(
                        step.get('standard_writing', '') + step.get('detailed_writing', '')
                        for step in chunk['steps'])
                    for chunk in chunks)
                final=re.sub(r'\s+','',solution_text)
                if example=='national-2025-q16':self.assertIn('7-(3m+7)(-2)^m',final)
                elif example=='national-2023-q17':self.assertIn('sqrt{10}',final);self.assertIn('6',final)
                answers.append(json.dumps(chunks,ensure_ascii=False,sort_keys=True))
            self.assertEqual(len(set(answers)),4)

    def test_targeted_recording_keeps_other_national_runs_and_discards_retired_cache(self):
        from scripts import run_showcase_pipeline as recorder
        import copy
        original = json.loads((ROOT/'frontend/showcase/pipeline.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            destination = root/'frontend/showcase/pipeline.json'
            destination.parent.mkdir(parents=True)
            published = copy.deepcopy(original)
            published['examples']['retired-local-paper'] = {'unreviewed': {'content':'must not publish'}}
            destination.write_text(json.dumps(published))
            result = copy.deepcopy(original['examples']['national-2023-q17']['xuefeng'])
            result['run_at'] = '2026-10-25T12:00:00+08:00'
            with patch.object(recorder, 'ROOT', root), patch.object(recorder, 'CACHE', root/'cache'), \
                 patch.object(recorder.settings, 'get_api_key', return_value='test-only-key'), \
                 patch.object(recorder.solver, 'call_deepseek'), \
                 patch.object(recorder, 'run_one', return_value=('national-2023-q17','xuefeng',result)) as run, \
                 patch.object(sys, 'argv', ['record','--example','national-2023-q17','--teacher','xuefeng']):
                recorder.main()
            run.assert_called_once()
            saved = json.loads(destination.read_text())
            self.assertEqual(set(saved['examples']), {'national-2023-q17','national-2025-q16'})
            self.assertEqual(saved['examples']['national-2025-q16'], original['examples']['national-2025-q16'])
            for teacher in ('liangliang','taotao','ji'):
                self.assertEqual(saved['examples']['national-2023-q17'][teacher], original['examples']['national-2023-q17'][teacher])
            self.assertEqual(saved['examples']['national-2023-q17']['xuefeng'], result)

    def test_recording_rejects_non_national_examples_before_any_model_call(self):
        from scripts import run_showcase_pipeline as recorder
        with patch.object(recorder.settings, 'get_api_key') as key, \
             patch.object(sys, 'argv', ['record','--example','shanghai-2024-q18']):
            with self.assertRaises(SystemExit) as error:
                recorder.main()
        self.assertEqual(error.exception.code, 2)
        key.assert_not_called()
