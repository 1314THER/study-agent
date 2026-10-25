"""Full-pool ledger tests use a temporary owner workspace and a fake provider."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from backend.data_paths import workspace, background_lease
from backend.identity import identity_context
from backend import question_pool as pool, routine_classification as rc, routine_review as rr

OWNER={'id':'studyadmin','username':'studyadmin','role':'owner'}
CONFIG={'model':'test','base_url':'https://example.test/v1','temperature':.1,'max_tokens':4096}


def fake(system,user,item):
    return {'primary_routine_id':'SET-014','secondary_routine_ids':[], 'candidate_routine_ids':[],
            'confidence':'high','composite':False,'needs_review':False,'review_reasons':[],
            'method_summary':'两个元素分别选择取或不取','evidence':[{'field':'question','quote':item['question']}],
            'representative_score':80,'variant_features':['两个元素'],'suggested_routine':None,'novelty_checks':[]}


class RoutineReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.stack=ExitStack(); self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ,{'STUDY_AGENT_DATA_DIR':'','STUDY_DEMO_AI_CONFIG':''}))
        self.stack.enter_context(workspace(self.tmp.name)); self.stack.enter_context(identity_context(OWNER))
        self.catalog=rc.load_catalog(); self.store=rr.get_store()
        pool.import_records({'name':'test','kind':'json','revision':'1'},[self.record(i) for i in range(1,14)])
        self.app=FastAPI();self.app.include_router(rr.router);self.app.include_router(rr.page_router)
        self.client=TestClient(self.app)

    def record(self,n):
        return {'source_key':str(n),'question':f'集合 A={{1,{n+1}}} 的子集有多少个？','solution':'每个元素取或不取。',
                'answer':'4','categories':['集合与逻辑用语'],'completeness':'complete','year':2025,'raw':{}}

    def create(self,key='test-request-0001'):
        return self.store.create(key,self.catalog,CONFIG,pool.storage_path())

    def create_legacy_snapshot(self,key):
        # Keep testing cached/human results from snapshots created by old versions.
        with self.store.connection() as conn,conn:
            conn.execute("UPDATE review_runs SET status='archived',stop=1")
        return self.create(key)

    def run_fake(self,run,caller=fake,**kwargs):
        return rr.execute_run(self.store,run['run_id'],caller,**kwargs)

    def test_all_items_snapshot_unlimited_groups_and_idempotent_start(self):
        run=self.create();self.assertEqual(run['total'],13)
        self.assertEqual(self.create()['run_id'],run['run_id'])
        pool.update_item(1,{'question':'后来修改的原题'})
        self.assertNotEqual(self.store.item(run['run_id'],1)['item']['question'],'后来修改的原题')
        self.assertTrue(self.store.item(run['run_id'],1)['source_stale'])
        finished=self.run_fake(run)
        self.assertEqual(finished['counts'],{'classified':13})
        group=next(g for g in self.store.groups(run['run_id'])['groups'] if g['id']=='SET-014')
        self.assertEqual(group['total'],13)
        self.assertEqual(self.store.rows(run['run_id'],{'routine_id':'SET-014'},page_size=5)['total'],13)
        report=self.client.get('/routine-review/runs/'+run['run_id']+'/report')
        self.assertEqual(report.status_code,200)
        self.assertIn('| 快照总题数 | 13 |',report.text)
        self.assertIn('| SET-014 |',report.text)
        self.assertIn('| 13 | 0 | 0 |',report.text)

    def test_missing_solution_and_graphic_are_attempted_not_new_routines(self):
        pool.update_item(1,{'solution':''});pool.update_item(2,{'completeness':'deferred_graphic'})
        run=self.create();finished=self.run_fake(run)
        self.assertEqual(finished['processed'],13)
        for iid in (1,2):
            row=self.store.item(run['run_id'],iid)
            self.assertEqual(row['kind'],'insufficient_content');self.assertEqual(row['needs_content'],1)

    def test_migrated_pool_images_and_review_originals_use_current_workspace(self):
        from PIL import Image
        from backend.question_assets import pool_asset_data
        root=pool.files_directory().parent
        figure=root/'snapshots/revision/figure.png';figure.parent.mkdir(parents=True)
        Image.new('RGB',(30,20),'white').save(figure)
        original='/old-mac/project/.runtime/question-pool/snapshots/revision'
        raw={'source_root':original,'original_file':original+'/figure.png',
             'image_refs':[{'path':'figure.png','label':'迁移题图'}]}
        with sqlite3.connect(pool.storage_path()) as conn:
            conn.execute('UPDATE pool_occurrences SET raw_json=? WHERE item_id=1',(json.dumps(raw),))
        data=pool_asset_data(pool.get_item(1))
        self.assertEqual(len(data['assets']),1);self.assertEqual(data['missing'],[])
        run=self.create();saved=self.store.item(run['run_id'],1)
        self.assertIn(figure.resolve(),rr.asset_paths(saved['occurrences']))
        self.assertEqual(pool.source_asset_path(original+'/../outside/../../../../secret'),Path(original+'/../outside/../../../../secret'))

    def test_backfilled_images_show_on_existing_snapshot_without_rematching(self):
        from PIL import Image
        from io import BytesIO
        run=self.create();self.run_fake(run)
        previous=self.store.item(run['run_id'],1)
        root=pool.files_directory().parent;root.mkdir(parents=True)
        buffer=BytesIO();Image.new('RGB',(30,20),'white').save(buffer,format='PNG')
        (root/'figure.png').write_bytes(buffer.getvalue())
        with sqlite3.connect(pool.storage_path()) as conn:
            origin=conn.execute('SELECT id,raw_json FROM pool_occurrences WHERE item_id=1').fetchone()
            raw=json.loads(origin[1]);raw.update(source_root=str(root),image_refs=[{'path':'figure.png','label':'选项 A'}])
            conn.execute('UPDATE pool_occurrences SET raw_json=? WHERE id=?',(json.dumps(raw),origin[0]))
        current=self.store.item(run['run_id'],1)
        self.assertEqual(current['source_assets']['assets'][0]['label'],'选项 A')
        self.assertEqual(current['item'],previous['item'])
        self.assertEqual(current['result'],previous['result'])
        self.assertEqual(self.store.run(run['run_id'])['calls'],run['calls']+13)

    def test_invalid_source_record_has_explicit_reason_and_does_not_stop_pool(self):
        with sqlite3.connect(pool.storage_path()) as conn:
            conn.execute("UPDATE pool_items SET question='' WHERE id=1")
        run=self.create(); finished=self.run_fake(run)
        self.assertEqual(finished['processed'],13)
        self.assertEqual(finished['counts'],{'classified':12,'error':1})
        row=self.store.item(run['run_id'],1)
        self.assertEqual(row['kind'],'insufficient_content')
        self.assertTrue(row['result']['error'])

    def test_bulk_confirmation_marks_unlimited_and_source_remains_unchanged(self):
        run=self.create();self.run_fake(run)
        req=rr.DecisionRequest(action='confirm',all_filtered=True,filters={'routine_id':'SET-014'},expected_revision=0,expected_count=13)
        self.assertEqual(self.store.decide(run['run_id'],req)['updated'],13)
        req=rr.DecisionRequest(action='mark',all_filtered=True,filters={},expected_revision=1,marks=['variant','representative'])
        self.store.decide(run['run_id'],req)
        self.assertEqual(len([r for r in self.store.rows(run['run_id'])['data'] if r['marks']==['variant','representative']]),13)
        self.assertEqual(pool.get_item(1)['status'],'unreviewed')
        self.assertFalse((Path(self.tmp.name)/'study_agent.db').exists())

    def test_revision_count_and_source_conflicts_are_atomic(self):
        run=self.create();self.run_fake(run)
        for revision,count in [(1,13),(0,12)]:
            with self.assertRaises(HTTPException):
                self.store.decide(run['run_id'],rr.DecisionRequest(action='confirm',all_filtered=True,expected_revision=revision,expected_count=count))
        pool.update_item(2,{'question':'新题干'})
        with self.assertRaises(HTTPException):
            self.store.decide(run['run_id'],rr.DecisionRequest(action='confirm',item_ids=[1,2],expected_revision=0))
        self.assertEqual(self.store.run(run['run_id'])['review_counts'],{'pending':13})

    def test_human_moves_are_preserved_inflight_and_across_new_snapshots(self):
        run=self.create();self.run_fake(run)
        self.store.decide(run['run_id'],rr.DecisionRequest(action='assign',item_ids=[1],expected_revision=0,primary_id='SET-015',note='人工改组'))
        row=self.store.item(run['run_id'],1)
        self.store.save_result(run['run_id'],1,{'classification':fake('','',row['item'])},'classified')
        self.assertEqual(self.store.item(run['run_id'],1)['primary_id'],'SET-015')
        fresh=self.create_legacy_snapshot('test-second-run')
        self.assertEqual(self.store.item(fresh['run_id'],1)['primary_id'],'SET-015')
        def no_calls(*args): raise AssertionError('successful cache must be reused')
        self.run_fake(fresh,no_calls)

    def test_pause_resume_concurrency_and_cache(self):
        run=self.create();calls=[]; active=[0,0]; lock=threading.Lock()
        def provider(s,u,item):
            with lock: active[0]+=1;active[1]=max(active)
            time.sleep(.02)
            with lock:
                calls.append(item['id']);active[0]-=1
                if len(calls)==3:self.store.control(run['run_id'],'pause')
            return fake(s,u,item)
        paused=self.run_fake(run,provider,concurrency=3)
        self.assertEqual(paused['status'],'paused');self.assertLessEqual(active[1],3)
        completed=set(calls);self.store.control(run['run_id'],'resume')
        self.run_fake(run,lambda s,u,i:(calls.append(i['id']) or fake(s,u,i)))
        self.assertEqual(len(calls),13);self.assertEqual(set(calls),set(range(1,14)))

    def test_failures_retry_and_auth_failure_pauses_batch(self):
        run=self.create()
        def broken(s,u,i):
            if i['id']==1:raise TimeoutError()
            return fake(s,u,i)
        result=self.run_fake(run,broken)
        self.assertEqual(result['counts']['error'],1)
        self.store.control(run['run_id'],'retry_failed');calls=[]
        self.run_fake(run,lambda s,u,i:(calls.append(i['id']) or fake(s,u,i)))
        self.assertEqual(calls,[1])
        pool.update_item(1,{'solution':'换一个解析'})
        second=self.create_legacy_snapshot('test-auth-failure')
        def denied(*args):raise rc.ProviderRequestError(401)
        result=self.run_fake(second,denied)
        self.assertEqual(result['status'],'paused');self.assertIn('认证',result['reason'])

    def test_interrupted_pid_and_owner_access(self):
        run=self.create()
        with self.store.connection() as conn,conn:conn.execute("UPDATE review_runs SET status='running',worker_pid=99999999 WHERE run_id=?",(run['run_id'],))
        self.assertEqual(self.store.run(run['run_id'])['status'],'interrupted')
        with identity_context({'id':'2','username':'student','role':'user'}):
            for path in ['/routine-review/runs/latest','/routine-review.html']:
                self.assertEqual(self.client.get(path).status_code,403)
        with identity_context(None),background_lease(lambda:None):
            self.assertEqual(self.client.get('/routine-review/runs/latest').status_code,403)

    def test_api_pagination_filters_invalid_fields_and_bulk(self):
        run=self.create();self.run_fake(run);base='/routine-review/runs/'+run['run_id']
        response=self.client.get(base+'/items',params={'page':2,'page_size':5,'routine_id':'SET-014'})
        self.assertEqual([r['item_id'] for r in response.json()['data']],[6,7,8,9,10])
        response=self.client.post(base+'/decisions',json={'action':'assign','item_ids':[1,6,12],'expected_revision':0,'primary_id':'SET-015','secondary_ids':['SET-014']})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.store.rows(run['run_id'],{'routine_id':'SET-015'})['total'],3)
        self.assertEqual(self.client.post('/routine-review/runs',json={'request_id':'test-invalid','path':'/etc/passwd'}).status_code,422)
        self.assertEqual(self.client.get(base+'/items',params={'page_size':0}).status_code,422)

    def test_owner_web_packet_end_to_end_and_student_denied(self):
        run=self.create();base='/routine-review/runs/'+run['run_id']
        response=self.client.post(base+'/web-packet',json={'limit':5})
        self.assertEqual(response.status_code,200)
        packet=response.json()
        self.assertEqual(packet['item_ids'],[1,2,3,4,5])
        reply={'packet_id':packet['packet_id'],'results':[{'id':iid,'classification':fake('','',self.store.item(run['run_id'],iid)['item'])} for iid in packet['item_ids']]}
        endpoint='/routine-review/web-packets/'+packet['packet_id']+'/response'
        self.assertEqual(self.client.post(endpoint,json={'response':json.dumps(reply)}).json()['imported'],5)
        self.assertEqual(self.client.post(endpoint,json={'response':json.dumps(reply)}).json()['idempotent'],True)
        self.assertEqual(self.store.run(run['run_id'])['counts']['classified'],5)
        self.assertEqual(self.client.post(base+'/web-packet',json={'limit':21}).status_code,422)
        self.assertEqual(self.client.post(endpoint,json={'response':'{}','db_path':'/tmp/x'}).status_code,422)
        with identity_context({'id':'2','username':'student','role':'user'}):
            self.assertEqual(self.client.post(base+'/web-packet',json={'limit':5}).status_code,403)
            self.assertEqual(self.client.post(endpoint,json={'response':json.dumps(reply)}).status_code,403)

    def test_mark_pending_does_not_skip_matching_and_empty_confirmation_rejected(self):
        run=self.create()
        self.store.decide(run['run_id'],rr.DecisionRequest(action='mark',item_ids=[1],marks=['variant'],expected_revision=0))
        with self.assertRaises(HTTPException):self.store.decide(run['run_id'],rr.DecisionRequest(action='confirm',item_ids=[2],expected_revision=1))
        result=self.run_fake(run)
        self.assertEqual(result['processed'],13)
        self.assertEqual(self.store.item(run['run_id'],1)['marks'],['variant'])

        fresh=self.create_legacy_snapshot('test-after-pending-mark')
        self.assertEqual(self.store.item(fresh['run_id'],1)['primary_id'],'SET-014')

    def test_audit_checkpoint_retries_only_full_catalog_stage(self):
        run=self.create()
        def interrupted(s,u,item):
            reply=fake(s,u,item)
            if item['id']==1:
                if json.loads(u)['stage']=='full_catalog_audit': raise TimeoutError()
                reply['confidence']='medium'
            return reply
        self.run_fake(run,interrupted)
        self.assertTrue(self.store.item(run['run_id'],1)['result']['audit_pending'])
        self.store.control(run['run_id'],'retry_failed');stages=[]
        def resumed(s,u,item):
            stages.append(json.loads(u)['stage']);return fake(s,u,item)
        result=self.run_fake(run,resumed)
        self.assertEqual(stages,['full_catalog_audit']);self.assertEqual(result['counts'],{'classified':13})

    def test_single_item_rematch_keeps_batch_and_other_results(self):
        run=self.create();self.run_fake(run)
        base='/routine-review/runs/'+run['run_id']
        with patch.object(rr,'enqueue_run',return_value={'accepted':True}) as enqueue:
            response=self.client.post(base+'/items/1/rematch',json={'request_id':'single-rematch-0001'})
        self.assertEqual(response.status_code,202)
        self.assertEqual(enqueue.call_args.args[-1],1)
        calls=[]
        self.run_fake(run,lambda s,u,i:(calls.append(i['id']) or fake(s,u,i)),only_item_id=1)
        self.assertEqual(calls,[1]);self.assertEqual(self.store.run()['run_id'],run['run_id'])

    def test_new_routine_confirmation_requires_current_catalog_and_human_revision(self):
        run=self.create()
        def novel(s,u,item):
            reply=fake(s,u,item)
            if item['id']==1:
                reply.update(primary_routine_id=None,needs_review=True,
                    suggested_routine={'name':'审核测试新方法','category':'集合与逻辑用语','signals':['特殊结构'],'retrieval_terms':['特殊'],
                                      'key_steps':['按新结构分析'],'exclusions':['一般子集计数不用'],'confusable_ids':['SET-014'],'aliases':[]},
                    novelty_checks=[{'routine_id':'SET-014','reason':'不是独立元素选择'}])
            return reply
        self.run_fake(run,novel)
        data=self.store.item(run['run_id'],1)
        decision={'action':'create','confirmed':True,'expected_catalog_hash':data['result']['review']['catalog_hash'],'note':'人工确认边界'}
        path='/routine-review/runs/'+run['run_id']+'/items/1/create-routine'
        self.assertEqual(self.client.post(path,json={'expected_revision':1,'decision':decision}).status_code,409)
        response=self.client.post(path,json={'expected_revision':0,'decision':decision})
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['formal_pattern_created'])
        self.assertEqual(len(rr.reference_store().read()['catalog']['routines']),len(self.catalog["routines"])+1)
        self.assertEqual(self.store.item(run['run_id'],1)['review_status'],'confirmed')
        self.assertEqual(len(rc.load_catalog()['routines']),len(self.catalog["routines"]))

    def test_assets_cannot_escape_private_question_directory(self):
        root=Path(self.tmp.name);inside=root/'question-pool'/'original.pdf';inside.parent.mkdir();inside.write_bytes(b'%PDF')
        outside=root/'unrelated.pdf';outside.write_bytes(b'%PDF')
        self.assertEqual(rr.asset_paths([{'raw':{'original_file':str(inside)}}]),[inside.resolve()])
        self.assertEqual(rr.asset_paths([{'raw':{'original_file':str(outside)}}]),[])


    def test_usage_unknown_is_not_zero_and_survives_failed_classification(self):
        run=self.create();self.assertIsNone(run['usage']['completion_tokens'])
        self.store.record_usage(run['run_id'],{'id':1},'retrieved_match',{'prompt_tokens':1000,'prompt_cache_hit_tokens':800,'prompt_cache_miss_tokens':200,'completion_tokens':1024,'reasoning_tokens':None})
        self.store.save_result(run['run_id'],1,{'error':'超出输出长度'},'error',1)
        usage=self.store.run(run['run_id'])['usage']
        self.assertEqual(usage['requests'],1);self.assertEqual(usage['cache_hit_ratio'],.8)
        self.assertIsNone(usage['reasoning_tokens']);self.assertEqual(usage['observed']['reasoning_tokens'],0)
        self.assertIn('| 输出（含思考） | 1024 |',self.store.write_report(run['run_id']).read_text())

    def test_old_resume_requires_optimization(self):
        run=self.create();base='/routine-review/runs/'+run['run_id']
        response=self.client.post(base+'/control',json={'action':'resume','request_id':'old-resume-intent'})
        self.assertEqual(response.status_code,409)

    def test_api_defaults_to_deepseek_when_local_is_not_selected(self):
        with patch.object(rr,'ai_caller') as provider,patch.object(rr,'enqueue_run',return_value={'accepted':True}) as enqueue:
            response=self.client.post('/routine-review/runs',json={'request_id':'new-luna-default'})
        self.assertEqual(response.status_code,202)
        self.assertEqual(provider.call_args.args[0]['engine'],'deepseek')
        self.assertEqual(self.store.run()['model_config']['engine'],'deepseek')
        self.assertTrue(enqueue.called)

    def test_routine_review_uses_liangs_configured_model_provider(self):
        from backend import settings
        config = {"solver": {"model": "glm-4.7-flash", "reasoning_effort": "medium"}}
        with patch.object(settings, "get_teacher_config", return_value=config), \
             patch.object(settings, "get_api", return_value={"zhipu": {"base_url": "https://glm.example/v1"}}):
            model = rr.model_config()
        self.assertEqual(model["model"], "glm-4.7-flash")
        self.assertEqual(model["provider"], "zhipu")
        self.assertEqual(model["base_url"], "https://glm.example/v1")
        self.assertEqual(model["reasoning_effort"], "medium")

    def test_existing_progress_blocks_all_new_starts_and_preserves_results(self):
        run=self.create();self.run_fake(run)
        with patch.object(rr,'ai_caller') as provider,patch.object(rr,'enqueue_run') as enqueue:
            for status in ('ready','queued','running','paused','done','interrupted'):
                with self.store.connection() as conn,conn:
                    conn.execute('UPDATE review_runs SET status=?,worker_pid=?,updated_at=? WHERE run_id=?',(status,os.getpid(),time.time(),run['run_id']))
                response=self.client.post('/routine-review/runs',json={'request_id':'accidental-new-run'})
                self.assertEqual(response.status_code,409)
                self.assertEqual(self.store.run()['run_id'],run['run_id'])
                self.assertEqual(self.store.run()['counts'],{'classified':13})
            provider.assert_not_called();enqueue.assert_not_called()
        with self.assertRaises(HTTPException) as caught:
            self.create('duplicate-snapshot')
        self.assertEqual(caught.exception.status_code,409)
        with self.store.connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM review_runs').fetchone()[0],1)
        self.assertEqual(self.create()['run_id'],run['run_id'])
        repeated=self.client.post('/routine-review/runs',json={'request_id':'test-request-0001'})
        self.assertEqual(repeated.json()['run_id'],run['run_id'])

    def test_archived_legacy_task_cannot_replace_or_resume_original(self):
        run=self.create();self.run_fake(run)
        with self.store.connection() as conn,conn:
            conn.execute("INSERT INTO review_runs(run_id,request_id,catalog_json,config_json,status,created_at,updated_at) SELECT 'discarded-run','discarded-request',catalog_json,config_json,'archived',created_at+1,updated_at FROM review_runs WHERE run_id=?",(run['run_id'],))
        self.assertEqual(self.store.run()['run_id'],run['run_id'])
        self.assertEqual(self.store.run()['counts'],{'classified':13})
        self.assertEqual(self.client.get('/routine-review/runs/discarded-run').status_code,404)
        self.assertEqual(self.client.post('/routine-review/runs/discarded-run/control',json={'action':'resume','request_id':'legacy-resume'}).status_code,404)





if __name__=='__main__':unittest.main()
