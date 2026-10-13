"""Graph edits are isolated from review decisions and protected by owner access."""
from contextlib import ExitStack
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend.data_paths import workspace
from backend.identity import identity_context
from backend import question_pool as pool, routine_classification as rc, routine_review as rr, routine_graph as graph
from tests.test_routine_review import OWNER, CONFIG, fake


class RoutineGraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,{'STUDY_AGENT_DATA_DIR':'','STUDY_DEMO_AI_CONFIG':''}))
        self.stack.enter_context(workspace(self.tmp.name));self.stack.enter_context(identity_context(OWNER))
        self.app=FastAPI();self.app.include_router(graph.router);self.app.include_router(graph.page_router)
        self.client=TestClient(self.app);self.catalog=rc.load_catalog();self.store=rr.get_store()

    def create_run(self):
        pool.import_records({'name':'graph-test','kind':'json','revision':'1'},[
            {'source_key':str(i),'question':f'集合 A={{1,{i+1}}} 的子集有多少个？','solution':'每个元素取或不取。',
             'answer':'4','categories':['集合与逻辑用语'],'completeness':'complete','raw':{}} for i in range(1,15)])
        run=self.store.create('graph-test-run',self.catalog,CONFIG,pool.storage_path())
        rr.execute_run(self.store,run['run_id'],fake)
        return run

    def draft(self):
        return {'name':'自定义分类讨论测试','category':'集合与逻辑用语','signals':['含参且可能退化'],
                'retrieval_terms':['含参','退化'],'key_steps':['找临界点','逐类检验'],
                'exclusions':['条件固定且不退化时直接求解'],'confusable_ids':[],'aliases':[]}

    def test_existing_relationships_only_and_catalog_coverage(self):
        d=self.client.get('/routine-graph').json()
        self.assertIsNone(d['run'])
        self.assertEqual(len([n for n in d['nodes'] if n['kind']=='routine']),288)
        self.assertEqual(len([n for n in d['nodes'] if n['kind']=='category']),12)
        self.assertEqual({e['kind'] for e in d['edges']},{'contains','confusable'})
        existing={tuple(sorted((r['id'],other))) for r in self.catalog['routines'] for other in r['confusable_ids']}
        self.assertEqual({(e['source'],e['target']) for e in d['edges'] if e['kind']=='confusable'},existing)

    def test_counts_follow_human_review_and_current_batch(self):
        run=self.create_run()
        self.store.decide(run['run_id'],rr.DecisionRequest(action='confirm',item_ids=[1,2],expected_revision=0))
        d=self.client.get('/routine-graph').json();node=next(n for n in d['nodes'] if n['id']=='SET-014')
        self.assertEqual((node['total'],node['pending'],node['confirmed']),(14,12,2))
        self.assertEqual(d['run']['run_id'],run['run_id'])
        self.assertEqual(self.client.get('/routine-graph?run_id=unknown').status_code,404)

    def test_layout_persistence_conflicts_and_invalid_nodes(self):
        self.create_run();original=self.store.run()['review_counts']
        data={'expected_revision':0,'positions':{'SET-014':{'x':-100,'y':234}}}
        self.assertEqual(self.client.put('/routine-graph/layout',json=data).status_code,200)
        self.assertEqual(self.client.get('/routine-graph').json()['layout']['positions']['SET-014'],{'x':-100,'y':234})
        self.assertEqual(self.client.put('/routine-graph/layout',json=data).status_code,409)
        data['expected_revision']=1;data['positions']={'unknown':{'x':1,'y':2}}
        self.assertEqual(self.client.put('/routine-graph/layout',json=data).status_code,422)
        self.assertEqual(self.client.get('/routine-graph').json()['layout']['revision'],1)
        self.assertEqual(self.store.run()['review_counts'],original)

    def test_manual_routine_shared_with_review_and_retry_is_idempotent(self):
        run=self.create_run();d=self.client.get('/routine-graph').json()
        body={'request_id':'manual-create-test','expected_catalog_hash':d['catalog_hash'],'draft':self.draft()}
        response=self.client.post('/routine-graph/routines',json=body)
        self.assertEqual(response.status_code,201,response.text);rid=response.json()['routine_id']
        self.assertEqual(rid,'SET-029')
        self.assertEqual(self.client.post('/routine-graph/routines',json=body).json()['routine_id'],rid)
        self.assertEqual(len(rr.reference_store().read()['catalog']['routines']),289)
        self.assertIn(rid,{g['id'] for g in self.store.groups(run['run_id'])['groups']})
        self.store.decide(run['run_id'],rr.DecisionRequest(action='assign',item_ids=[1],expected_revision=0,primary_id=rid))
        self.assertEqual(self.store.item(run['run_id'],1)['primary_id'],rid)
        self.assertEqual(len(self.client.get('/routine-graph').json()['nodes']),302)

    def test_manual_creation_rejects_stale_duplicate_or_invalid_drafts(self):
        d=self.client.get('/routine-graph').json();body={'request_id':'bad-draft-test','expected_catalog_hash':d['catalog_hash'],'draft':self.draft()}
        body['expected_catalog_hash']='0'*64
        self.assertEqual(self.client.post('/routine-graph/routines',json=body).status_code,409)
        body['expected_catalog_hash']=d['catalog_hash'];body['draft']['name']=self.catalog['routines'][0]['name']
        self.assertEqual(self.client.post('/routine-graph/routines',json=body).status_code,409)
        body['draft']=self.draft();body['draft']['confusable_ids']=['UNKNOWN-001']
        self.assertEqual(self.client.post('/routine-graph/routines',json=body).status_code,422)
        self.assertEqual(len(rr.reference_store().read()['catalog']['routines']),288)

    def test_guest_cannot_read_or_edit_graph(self):
        with identity_context({'id':'guest','username':'guest','role':'guest'}):
            for url in ['/routine-graph','/routine-graph.html']:
                self.assertEqual(self.client.get(url).status_code,403)
            self.assertEqual(self.client.put('/routine-graph/layout',json={'expected_revision':0}).status_code,403)
            self.assertEqual(self.client.post('/routine-graph/routines',json={}).status_code,403)
