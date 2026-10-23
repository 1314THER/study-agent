from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import unittest

from backend import routine_classification as rc
from scripts.build_routine_catalog import build, render
from tests.test_routine_graph import RoutineGraphTests


class CatalogExpansionTests(unittest.TestCase):
    def test_reproducible_catalog_and_retained_originals(self):
        catalog, old, families = build()
        self.assertEqual(catalog, rc.load_catalog())
        self.assertTrue(950 <= len(catalog['routines']) <= 1050)
        by_id = {r['id']: r for r in catalog['routines']}
        for r in old['routines']:
            for key in r:
                if key != 'exclusions':
                    self.assertEqual(by_id[r['id']][key], r[key])
            self.assertEqual(by_id[r['id']]['exclusions'][:len(r['exclusions'])], r['exclusions'])
        # Every added row carries a distinct concrete conversion, not a name-only variant.
        added = catalog['routines'][len(old['routines']):]
        self.assertEqual(len({tuple(r['key_steps']) for r in added}), len(added))
        self.assertTrue(all(r['signals'] and r['exclusions'] for r in added))
        markdown, report = render(catalog, old, families)
        self.assertEqual((rc.ROOT/'docs/routine-catalog.md').read_text(), markdown)
        self.assertEqual((rc.ROOT/'docs/routine-expansion.md').read_text(), report)

    def test_fixed_point_methods_retrieve_their_own_structures(self):
        catalog = rc.load_catalog()
        for words in ['两弦斜率和的定点', '两弦斜率积的定点', '弦端点构造线的韦达定点',
                      '椭圆三角参数弦定点', '切线交点定线与弦定点']:
            routine = next(r for r in catalog['routines'] if r['name'].startswith(words+'：'))
            item = {'question': routine['signals'][0], 'solution': routine['key_steps'][0], 'categories': ['解析几何']}
            self.assertIn(routine['id'], {r['id'] for r in rc.shortlist(item, catalog)})
        polar = [r for r in catalog['routines'] if '极点极线与接触弦' in r['name']]
        self.assertGreaterEqual(len(polar), 8)
        self.assertTrue(all('一般动弦不是接触弦' in r['exclusions'][0] for r in polar))


class CatalogEditTests(RoutineGraphTests):
    """Use the isolated owner/learner fixture, without calling any model."""

    def edit_body(self, rid='GEO-028', **changes):
        data = self.client.get('/routine-graph').json()
        node = next(n for n in data['nodes'] if n['id'] == rid)
        draft = {key: node[key] for key in ('name', 'category', 'signals', 'retrieval_terms', 'key_steps', 'exclusions', 'confusable_ids', 'aliases')}
        body = {'request_id': 'edit-test-request', 'expected_catalog_hash': data['catalog_hash'],
                'expected_review_revision': data['review_revision'], 'draft': draft,
                'review_status': 'pending', 'note': ''}
        body.update(changes)
        return body

    def test_status_only_keeps_hash_and_edit_resets_approval(self):
        before = self.client.get('/routine-graph').json()
        body = self.edit_body(review_status='reviewed', note='已核对斜率与退化边界')
        response = self.client.put('/routine-graph/routines/GEO-028', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertFalse(response.json()['content_changed'])
        self.assertEqual(response.json()['catalog_hash'], before['catalog_hash'])
        approved = self.client.get('/routine-graph').json()
        node = next(n for n in approved['nodes'] if n['id'] == 'GEO-028')
        self.assertEqual(node['catalog_review']['status'], 'reviewed')
        body = self.edit_body(request_id='edit-content-request')
        body['draft']['key_steps'].append('补检斜率不存在情形')
        response = self.client.put('/routine-graph/routines/GEO-028', json=body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['content_changed'])
        self.assertNotEqual(response.json()['catalog_hash'], before['catalog_hash'])
        self.assertEqual(response.json()['catalog_review']['status'], 'pending')
        history = self.client.get('/routine-graph/routines/GEO-028/history').json()['history']
        self.assertEqual(len(history), 2)
        self.assertEqual(history[-1]['review_before']['status'], 'reviewed')
        self.assertNotEqual(history[-1]['before'], history[-1]['after'])
        self.assertTrue(history[-1]['updated_at'])

    def test_stale_review_revision_and_idempotent_retry(self):
        body = self.edit_body(review_status='needs_changes', note='需要更明确的适用条件')
        first = self.client.put('/routine-graph/routines/GEO-028', json=body)
        self.assertEqual(first.status_code, 200, first.text)
        self.assertEqual(self.client.put('/routine-graph/routines/GEO-028', json=body).json(), first.json())
        self.assertEqual(len(self.client.get('/routine-graph/routines/GEO-028/history').json()['history']), 1)
        body['request_id'] = 'second-stale-request'
        self.assertEqual(self.client.put('/routine-graph/routines/GEO-028', json=body).status_code, 409)
        body['request_id'] = 'edit-test-request'
        body['note'] = '同编号不同内容'
        self.assertEqual(self.client.put('/routine-graph/routines/GEO-028', json=body).status_code, 409)

    def test_concurrent_reviews_cannot_overwrite_each_other(self):
        first = self.edit_body(review_status='reviewed')
        second = deepcopy(first)
        second.update(request_id='other-concurrent-request', review_status='needs_changes')
        # The request context is explicitly carried into worker threads by TestClient.
        from backend.data_paths import workspace
        from backend.identity import identity_context
        from tests.test_routine_review import OWNER
        def submit(body):
            with workspace(self.tmp.name), identity_context(OWNER):
                return self.client.put('/routine-graph/routines/GEO-028', json=body).status_code
        with ThreadPoolExecutor(max_workers=2) as executor:
            codes = list(executor.map(submit, [first, second]))
        self.assertEqual(sorted(codes), [200, 409])
        self.assertEqual(len(self.client.get('/routine-graph/routines/GEO-028/history').json()['history']), 1)

    def test_invalid_edit_missing_owner_and_export_roundtrip(self):
        body = self.edit_body()
        body['draft']['confusable_ids'] = ['NOT-999']
        self.assertEqual(self.client.put('/routine-graph/routines/GEO-028', json=body).status_code, 422)
        body = self.edit_body()
        body['draft']['name'] = self.catalog['routines'][0]['name']
        self.assertEqual(self.client.put('/routine-graph/routines/GEO-028', json=body).status_code, 409)
        body = self.edit_body(review_status='reviewed')
        self.assertEqual(self.client.put('/routine-graph/routines/GEO-028', json=body).status_code, 200)
        exported = self.client.get('/routine-graph/export')
        self.assertIn('attachment;', exported.headers['content-disposition'])
        self.assertEqual(len(rc.validate_catalog(exported.json())['routines']), len(self.catalog['routines']))
        self.assertEqual(exported.json()['routine_reviews']['GEO-028']['status'], 'reviewed')
        reused_create = {'request_id': body['request_id'], 'expected_catalog_hash': exported.json().get('catalog_hash', '0'*64), 'draft': self.draft()}
        self.assertEqual(self.client.post('/routine-graph/routines', json=reused_create).status_code, 409)
        from backend.identity import identity_context
        with identity_context({'id': 'user', 'username': 'user', 'role': 'user'}):
            for path in ['/routine-graph/export', '/routine-graph/routines/GEO-028/history']:
                self.assertEqual(self.client.get(path).status_code, 403)
            self.assertEqual(self.client.put('/routine-graph/routines/GEO-028', json=body).status_code, 403)

    def test_edit_preserves_question_decisions_layout_and_frozen_run(self):
        run = self.create_run()
        original = deepcopy(self.store.run(run['run_id'])['catalog'])
        self.store.decide(run['run_id'], __import__('backend.routine_review', fromlist=['DecisionRequest']).DecisionRequest(
            action='confirm', item_ids=[1], expected_revision=0))
        self.client.put('/routine-graph/layout', json={'expected_revision': 0, 'positions': {'GEO-028': {'x': 12, 'y': 34}}})
        body = self.edit_body()
        body['draft']['name'] += '（一般型）'
        saved = self.client.put('/routine-graph/routines/GEO-028', json=body)
        self.assertEqual(saved.status_code, 200, saved.text)
        data = self.client.get('/routine-graph').json()
        self.assertTrue(data['run_catalog_stale'])
        self.assertEqual(data['layout']['positions']['GEO-028'], {'x': 12, 'y': 34})
        self.assertEqual(self.store.run(run['run_id'])['catalog'], original)
        self.assertEqual(self.store.item(run['run_id'], 1)['review_status'], 'confirmed')


if __name__ == '__main__':
    unittest.main()
