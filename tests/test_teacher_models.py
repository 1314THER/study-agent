"""Teacher provider routing, legacy migration and independent credentials."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from fastapi import HTTPException
from backend import local_models, settings, solver
from tests.api_base import ApiTestCase


class TeacherSettingsTests(ApiTestCase):
    def test_defaults_and_independent_key_roundtrip(self):
        result = self.client.get('/settings').json()
        expected = {'liangliang': 'glm-4.7-flash', 'taotao': 'deepseek-flash',
                    'xuefeng': 'glm-5.3-flash', 'ji': 'gpt-6-astra'}
        for teacher, model in expected.items():
            for cfg in result['teachers'][teacher].values():
                self.assertEqual(cfg, {'model': model, 'reasoning_effort': 'medium'})
        self.assertFalse(result['api']['zhipu']['has_key'])
        response = self.client.put('/settings', json={'api': {
            'deepseek': {'api_key': 'ds-test-key'}, 'zhipu': {'api_key': 'glm-test-key'}},
            'teachers': {'ji': {'solver': {'reasoning_effort': 'high'}}}})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('glm-test-key', response.text)
        self.assertNotIn('ds-test-key', response.text)
        response = self.client.put('/settings', json={'api': {'zhipu': {'api_key': ''}}})
        self.assertTrue(response.json()['api']['zhipu']['has_key'])
        self.assertEqual(settings.get_api_key('deepseek'), 'ds-test-key')
        self.assertEqual(settings.get_api_key('zhipu'), 'glm-test-key')
        self.assertEqual(settings.get_teacher_config('ji')['solver']['reasoning_effort'], 'high')

    def test_old_ds_profiles_migrate_once_and_preserve_key_and_limits(self):
        old = {'teachers': {teacher: {stage: {'model': 'deepseek-v4-pro', 'reasoning_effort': 'low'}
                                    for stage in ('solver', 'verifier', 'formatter', 'grade')}
                            for teacher in settings.DEFAULTS['teachers']},
               'api': {'deepseek': {'api_key': 'ds-test-key'}}, 'limits': {'generate_count': 7}}
        Path(self.settings_json).write_text(json.dumps(old))
        self.assertEqual(settings.get_teachers(), settings.DEFAULTS['teachers'])
        self.assertEqual(settings.get_api_key('deepseek'), 'ds-test-key')
        self.assertEqual(settings.get_limits()['generate_count'], 7)
        self.client.put('/settings', json={'teachers': {'liangliang': {
            'solver': {'model': 'deepseek-flash', 'reasoning_effort': 'high'}}}})
        settings._cache.clear()
        self.assertEqual(settings.get_teacher_config('liangliang')['solver'],
                         {'model': 'deepseek-flash', 'reasoning_effort': 'high'})

    def test_glm_connection_probe_uses_saved_glm_key(self):
        settings.save_settings({'api': {'zhipu': {'api_key': 'glm-test-key'}}})
        with patch('httpx.post', return_value=SimpleNamespace(status_code=200)) as post:
            self.assertTrue(self.client.post('/settings/test', json={'provider': 'zhipu'}).json()['ok'])
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer glm-test-key')
        self.assertEqual(post.call_args.kwargs['json']['model'], 'glm-4.7-flash')


class TeacherRoutingTests(unittest.TestCase):
    def setUp(self):
        self.response = SimpleNamespace(status_code=200, json=lambda: {
            'choices': [{'message': {'content': 'answer'}}], 'usage': {'total_tokens': 3}})

    def test_glm_uses_own_endpoint_key_and_supported_efforts(self):
        with patch.object(settings, 'get_api_key', return_value='glm-only') as key, \
                patch.object(settings, 'get_api', return_value=deepcopy(settings.DEFAULTS['api'])), \
                patch.object(solver, 'get_api_key', side_effect=AssertionError('DS credential accessed')), \
                patch.object(solver.httpx, 'post', return_value=self.response) as post:
            for level, native in [('low', 'low'), ('medium', 'high'), ('high', 'max')]:
                self.assertEqual(solver.call_deepseek('system', 'question', model='glm-5.3-flash', reasoning_effort=level)[0], 'answer')
                self.assertEqual(post.call_args.kwargs['json']['reasoning_effort'], native)
                self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer glm-only')
                self.assertIn('open.bigmodel.cn', post.call_args.args[0])
            solver.call_deepseek('system', 'question', model='glm-4.7-flash', reasoning_effort='medium')
            body = post.call_args.kwargs['json']
            self.assertEqual(body['thinking'], {'type': 'enabled'})
            self.assertNotIn('reasoning_effort', body)
            key.assert_called_with('zhipu')

    def test_verifier_uses_configured_reasoning(self):
        cfg = deepcopy(settings.DEFAULTS['teachers']['xuefeng'])
        cfg['verifier']['reasoning_effort'] = 'high'
        with patch.object(settings, 'get_teacher_config', return_value=cfg), \
                patch.object(solver, 'call_deepseek', return_value=('[确认：可解]\n### 块1\n步骤1：变形\n标准过程：a=1\n详细过程：a=1', {})) as call:
            solver.step_verify_all('解答', '问题', '数列', teacher='xuefeng')
        self.assertEqual(call.call_args.kwargs['model'], 'glm-5.3-flash')
        self.assertEqual(call.call_args.kwargs['reasoning_effort'], 'high')

    def test_unconfigured_glm_does_not_use_ds(self):
        with patch.object(settings, 'get_api_key', return_value=''), \
                patch.object(solver, 'get_api_key', side_effect=AssertionError('DS fallback')), \
                patch.object(solver.httpx, 'post') as post:
            with self.assertRaisesRegex(ValueError, '智谱 API Key'):
                solver.call_deepseek('sys', 'user', model='glm-4.7-flash')
            post.assert_not_called()

    def test_cli_gets_model_effort_images_without_reading_api_keys(self):
        images = [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,aGVsbG8='}}]
        with patch.object(local_models, 'call_teacher', return_value=('answer', {})) as cli, \
                patch.object(solver, 'get_api_key', side_effect=AssertionError('DS key read')), \
                patch.object(settings, 'get_api_key', side_effect=AssertionError('GLM key read')):
            solver.call_deepseek('sys', 'question', model='gpt-6-astra', reasoning_effort='high', image_content=images)
            self.assertEqual(cli.call_args.kwargs['model'], 'gpt-6-astra')
            self.assertEqual(cli.call_args.kwargs['reasoning_effort'], 'high')
            self.assertEqual(cli.call_args.kwargs['image_content'], images)

    def test_cli_gateway_calls_private_adapter_and_blocks_nonlocal(self):
        class Unavailable(Exception):
            pass
        adapter = SimpleNamespace(run_prompt=Mock(return_value=('CLI answer', {})), CodexUnavailable=Unavailable)
        with patch.dict(sys.modules, {'backend.routine_codex': adapter}), \
                patch('backend.identity.current_identity', return_value=None), \
                patch.object(local_models, 'provider'):
            self.assertEqual(local_models.call_teacher('sys', 'q', reasoning_effort='high')[0], 'CLI answer')
            self.assertEqual(adapter.run_prompt.call_args.kwargs['model'], 'gpt-6-astra')
            self.assertEqual(adapter.run_prompt.call_args.kwargs['reasoning_effort'], 'high')
        with patch.dict(os.environ, {'STUDY_LOCAL_CODEX': '0'}):
            with self.assertRaises(HTTPException):
                local_models.call_teacher('sys', 'q')
        with patch('backend.identity.current_identity', return_value={'role': 'user'}):
            with self.assertRaises(HTTPException):
                local_models.call_teacher('sys', 'q')


if __name__ == '__main__':
    unittest.main()
