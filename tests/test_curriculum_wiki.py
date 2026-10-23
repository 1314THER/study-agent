"""Real graph edits, evidence provenance, task recovery and owner isolation."""
from contextlib import ExitStack
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI,HTTPException
from fastapi.testclient import TestClient
from backend.data_paths import workspace
from backend.identity import identity_context
from backend import curriculum_wiki as cw,curriculum_tasks as tasks,question_pool as pool

OWNER={"id":"owner","username":"studyadmin","role":"owner"}


class CurriculumTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.stack=ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(workspace(self.tmp.name));self.stack.enter_context(identity_context(OWNER))
        app=FastAPI();app.include_router(cw.router);app.include_router(cw.page_router)
        self.client=TestClient(app);self.store=cw.get_store()

    def request(self,**kwargs):
        return {"expected_revision":self.store.revision(),"reason":"测试：依据原材料核查",**kwargs}

    def pool_item(self):
        pool.import_records({"name":"测试原书","kind":"json","revision":"v1"},[
            {"source_key":"§1.3/Q1","question":"已知集合A={1,2}，B={2,3}，求A与B的交集。",
             "answer":"{2}","solution":"交集包含同时属于A和B的元素，所以结果为{2}。",
             "categories":["集合与逻辑用语"],"completeness":"complete","raw":{}}])
        with pool._connection() as c:id=c.execute("SELECT id FROM pool_items").fetchone()[0]
        return pool.get_item(id)

    def attach(self,item=None,lesson="b1:1.3:practice",method="按定义求交集",knowledge=None):
        item=item or self.pool_item()
        return cw.attach_question(self.store,cw.QuestionLink(**self.request(lesson_id=lesson,pool_item_id=item["id"],
            occurrence_id=item["occurrences"][0]["id"],method=method,knowledge_ids=knowledge or [],routine_ids=["SET-010"])))

    def test_all_books_content_and_verified_directory_are_accounted_for(self):
        d=self.client.get("/curriculum-wiki/overview").json()
        self.assertEqual(len(d["books"]),5);self.assertGreater(d["counts"]["lessons"],300)
        from backend.routine_classification import load_catalog
        self.assertEqual(d["counts"]["routines"],len(load_catalog()["routines"]))
        self.assertEqual(d["coverage"]["textbook"]["covered"],d["coverage"]["textbook"]["total"])
        self.assertEqual(d["coverage"]["textbook"]["verified"],d["coverage"]["textbook"]["total"])
        self.assertEqual(d["coverage"]["human"]["confirmed"],0)
        for n in self.store.entities("lesson"):
            self.assertTrue(n["data"]["body"]);self.assertTrue(n["data"]["objectives"])
            self.assertEqual(n["data"]["allocation"],"system_proposed")
        self.assertEqual(self.store.checks()["warnings"],[])
        self.assertTrue(self.store.entity("s1:1.4")["entity"])

    def test_sources_do_not_claim_unread_workbooks(self):
        workbooks=self.store.overview()["coverage"]["workbooks"]
        self.assertEqual(len(workbooks),4)
        self.assertTrue(all(s["reading_status"]=="entry_only" and s["isbn"] is None for s in workbooks))

    def test_search_by_knowledge_and_routine_and_book(self):
        r=self.client.get("/curriculum-wiki/lessons",params={"query":"导数","book":"s2","page_size":500}).json()
        self.assertGreater(r["total"],0);self.assertTrue(all(n["book_id"]=="s2" for n in r["items"]))
        self.assertGreater(self.client.get("/curriculum-wiki/lessons?routine=SET-010").json()["total"],0)

    def test_owner_permissions_protect_every_entry_and_generic_jobs(self):
        from backend.jobs import validate_args
        with identity_context({"id":"student","username":"student","role":"user"}):
            for url in ["/curriculum-wiki/overview","/curriculum-wiki/lessons","/curriculum-wiki/export","/curriculum-wiki.html","/curriculum-wiki/runs"]:
                self.assertEqual(self.client.get(url).status_code,403,url)
            self.assertEqual(self.client.post("/curriculum-wiki/relations",json=self.request(relation={})).status_code,403)
            with self.assertRaises(HTTPException):validate_args("curriculum_research",{"run_id":"a"*32})

    def test_manual_edit_conflict_and_restore_preserve_data(self):
        id="b1:1.1:l1";old=self.store.entity(id)["entity"]
        r=self.client.patch("/curriculum-wiki/entities/"+id,json=self.request(changes={"data":{"body":"人工修正说明"},"status":"confirmed"}))
        self.assertEqual(r.status_code,200,r.text)
        r=self.client.patch("/curriculum-wiki/entities/"+id,json={"expected_revision":0,"reason":"另一个窗口","changes":{"title":"不应保存"}})
        self.assertEqual(r.status_code,409)
        self.assertEqual(self.store.entity(id)["entity"]["status"],"confirmed")
        r=self.client.post("/curriculum-wiki/history/1/restore",json=self.request())
        self.assertEqual(r.status_code,200,r.text);self.assertEqual(self.store.entity(id)["entity"]["data"],old["data"])

    def test_cycle_and_incompatible_edges_roll_back(self):
        before=self.store.revision()
        r=self.client.post("/curriculum-wiki/relations",json=self.request(relation={"source":"b1:1.1:l1","target":"b1:1.2:l1","kind":"prerequisite","evidence":{"reason":"反向依赖"}}))
        self.assertEqual(r.status_code,422,r.text);self.assertEqual(self.store.revision(),before)
        r=self.client.post("/curriculum-wiki/relations",json=self.request(relation={"source":"b1:1.1:l1","target":"routine:SET-010","kind":"requires","evidence":{"reason":"错误类型"}}))
        self.assertEqual(r.status_code,422)

    def test_reorder_warns_without_losing_ids(self):
        ids=[n["id"] for n in sorted(self.store.entities("lesson"),key=lambda n:n["position"])]
        ids.remove("b1:1.2:l1");ids.insert(0,"b1:1.2:l1")
        r=self.store.reorder(ids,0,"提前课时测试")
        self.assertTrue(any(w["type"]=="lesson_order" for w in r["warnings"]))
        self.assertEqual(set(ids),{n["id"] for n in self.store.entities("lesson")})

    def test_split_merge_and_restore_keep_knowledge_and_prerequisites(self):
        id="b1:1.1:l1"
        parts=[{"title":"概念辨析","body":"明确集合元素的类型","objectives":["辨认元素"]},
               {"title":"归属表达","body":"用归属符号表示关系","objectives":["表示关系"]}]
        r=self.store.split(id,parts,0,"拆为两次活动");ids=r["result"]
        self.assertFalse(self.store.entity(id)["entity"]["active"])
        self.assertEqual(len(self.store.entities("lesson")),330)
        self.assertFalse(self.store.checks()["warnings"])
        merged=self.store.merge(ids,"集合概念与表达",self.store.revision(),"合并教学活动")
        self.assertEqual(len(self.store.entities("lesson")),329)
        self.store.restore(merged["revision"],self.store.revision(),"恢复拆分课")
        self.assertEqual(len(self.store.entities("lesson")),330)

    def test_restore_rejects_later_changes(self):
        self.store.edit("b1:1.1:l1",{"title":"第一次"},0,"修订")
        self.store.edit("b1:1.1:l1",{"title":"第二次"},1,"后续修订")
        with self.assertRaises(HTTPException) as exc:self.store.restore(1,2,"恢复旧修改")
        self.assertEqual(exc.exception.status_code,409)

    def test_real_question_multi_origin_multi_solution_and_no_forged_workbook(self):
        item=self.pool_item();a=self.attach(item)
        b=self.attach(item,method="数轴或逐元素核对")
        self.assertNotEqual(a["result"],b["result"])
        d=self.store.detail("b1:1.3:practice")
        self.assertEqual(len(d["solutions"]),2)
        self.assertTrue(all(not s["freshness"]["stale"] for s in d["solutions"]))
        req=cw.QuestionLink(**self.request(lesson_id="b1:1.3:practice",pool_item_id=item["id"],
            occurrence_id=item["occurrences"][0]["id"],method="不能伪装为教辅",source_id="source:jcb"))
        with self.assertRaises(HTTPException):cw.attach_question(self.store,req)
        self.assertTrue(any(w["type"]=="unknown_requirements" for w in self.store.checks()["warnings"]))
        pool.import_records({"name":"第二个独立出处","kind":"json","revision":"v1"},[
            {"source_key":"p.9/Q2","question":item["question"],"answer":item["answer"],"solution":item["solution"],
             "categories":item["categories"],"completeness":"complete","raw":{}}])
        latest=pool.get_item(item["id"])
        self.assertEqual(len(latest["occurrences"]),2)
        req=cw.QuestionLink(**self.request(lesson_id="b1:1.3:practice",pool_item_id=item["id"],
            occurrence_id=latest["occurrences"][1]["id"],method="第二出处的同题解法"))
        linked=cw.attach_question(self.store,req)
        self.assertNotEqual(linked["result"],a["result"])

    def test_later_method_is_advanced_and_source_change_is_stale(self):
        item=self.pool_item()
        result=self.attach(item,knowledge=["kp:s2:5.3:l1"])
        self.assertTrue(any(w["type"]=="advanced_solution" for w in self.store.checks()["warnings"]))
        stage=self.store.checks()["solution_stages"][result["result"]]
        self.assertEqual(stage["earliest_lesson_id"],"s2:5.3:l1")
        with pool._connection() as c:
            c.execute("UPDATE pool_items SET question=question||' 新增条件',version=version+1 WHERE id=?",(item["id"],));c.commit()
        sol=self.store.entity(result["result"])["entity"]
        self.assertTrue(self.store.solution_freshness(sol)["stale"])
        self.assertNotIn("新增条件",sol["data"]["question_snapshot"])

    def test_source_import_and_wiki_export(self):
        req=cw.SourceImport(**self.request(source={"title":"教辅公开样页","source_type":"workbook","reading_status":"partial"},
            excerpts=[{"text":"集合中的元素具有确定性。","locator":"p.2"}]))
        r=cw.import_source(self.store,req)
        self.assertEqual(self.store.entity(r["result"])["entity"]["data"]["excerpts"][0]["locator"],"p.2")
        self.assertEqual(self.client.get("/curriculum-wiki/export").json()["authority"],"sqlite")
        self.assertIn("[[",self.client.get("/curriculum-wiki/export?format=markdown").text)
        self.assertEqual(self.client.get("/curriculum-wiki/sources/source:jcb/file").status_code,404)

    def test_evidence_validation_rejects_fabricated_quotes(self):
        excerpts=[{"source_id":"source:b1","text":"集合中的元素具有确定性。","locator":"p.2"}]
        raw={"changes":{"body":"学习集合"},"evidence":[{"source_id":"source:b1","locator":"p.2","quote":"确定性"}]}
        self.assertEqual(tasks.validate_draft(raw,excerpts)["kind"],"lesson_draft")
        raw["evidence"][0]["quote"]="不存在的引文"
        with self.assertRaises(ValueError):tasks.validate_draft(raw,excerpts)

    def test_resumable_task_caches_and_never_overwrites_confirmed_lesson(self):
        self.store.edit("source:b1",{"data":{"excerpts":[{"text":"集合中的元素具有确定性。","locator":"p.2"}]}},0,"添加原文")
        self.store.edit("b1:1.1:l1",{"status":"confirmed"},self.store.revision(),"教师确认")
        req=tasks.Start(**self.request(kind="lesson_draft",entity_ids=["b1:1.1:l1"],request_id="curriculum-test-run"))
        run=tasks.create_run(self.store,req);self.assertEqual(tasks.create_run(self.store,req)["id"],run["id"])
        tasks._save_run(self.store,run["id"],status="queued")
        calls=[]
        def fake(system,user,item):
            calls.append(item)
            return {"changes":{"body":"模型建议内容","objectives":["解释元素确定性"]},
                    "evidence":[{"source_id":"source:b1","locator":"p.2","quote":"确定性"}]}
        tasks.run_job({"run_id":run["id"]},caller=fake)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.store.entity("b1:1.1:l1")["entity"]["status"],"confirmed")
        self.assertNotEqual(self.store.entity("b1:1.1:l1")["entity"]["data"]["body"],"模型建议内容")
        tasks._save_run(self.store,run["id"],status="queued")
        tasks.run_job({"run_id":run["id"]},caller=fake)
        self.assertEqual(len(calls),1)
        suggestions=self.client.get("/curriculum-wiki/suggestions").json()["items"];self.assertEqual(len(suggestions),1)
        self.store.edit("b1:1.1:l1",{"title":"人工随后修改"},self.store.revision(),"保护后续修改")
        response=self.client.post("/curriculum-wiki/suggestions/"+suggestions[0]["id"]+"/apply",json=self.request())
        self.assertEqual(response.status_code,409)

    def test_empty_source_draft_is_not_a_fake_read(self):
        req=tasks.Start(**self.request(kind="lesson_draft",entity_ids=["b1:1.1:l1"],request_id="empty-source-task"))
        with self.assertRaises(HTTPException) as exc:tasks.create_run(self.store,req)
        self.assertEqual(exc.exception.status_code,422)

    def test_new_knowledge_has_an_explicit_introducing_lesson(self):
        response=self.client.post("/curriculum-wiki/knowledge",json=self.request(
            title="人工补充的边界条件",body="明确记录补充条件的适用范围。",
            introducing_lesson_id="b1:1.1:l1"))
        self.assertEqual(response.status_code,201,response.text)
        kid=response.json()["result"]
        self.assertEqual(self.store.checks()["teaching_locations"][kid],["b1:1.1:l1"])

    def test_missing_answer_in_one_source_does_not_borrow_another_sources_answer(self):
        item=self.pool_item()
        pool.import_records({"name":"没有答案的独立试读页","kind":"json","revision":"v1"},[
            {"source_key":"sample/Q1","question":item["question"],"answer":"","solution":"",
             "categories":item["categories"],"completeness":"complete","raw":{}}])
        current=pool.get_item(item["id"]);origin=current["occurrences"][-1]
        req=cw.QuestionLink(**self.request(lesson_id="b1:1.3:practice",pool_item_id=item["id"],
            occurrence_id=origin["id"],method="无原答案的研究解法"))
        result=cw.attach_question(self.store,req)
        sol=self.store.entity(result["result"])["entity"]
        self.assertEqual(sol["data"]["answer_snapshot"],"")
        self.assertEqual(sol["data"]["solution_snapshot"],"")
        self.assertTrue(current["answer"])

    def test_workspace_isolation(self):
        self.store.edit("b1:1.1:l1",{"title":"私有修订"},0,"校正")
        with tempfile.TemporaryDirectory() as other,workspace(other):
            self.assertNotEqual(cw.get_store().entity("b1:1.1:l1")["entity"]["title"],"私有修订")
            self.assertEqual(cw.get_store().revision(),0)

    def test_runtime_snapshot_includes_curriculum_database_and_evidence(self):
        import importlib.util
        import sqlite3
        spec=importlib.util.spec_from_file_location("cw_runtime_snapshot",cw.ROOT/"deploy/runtime_snapshot.py")
        snapshot=importlib.util.module_from_spec(spec);spec.loader.exec_module(snapshot)
        root=Path(self.tmp.name)/"source";runtime=root/".runtime";runtime.mkdir(parents=True)
        for filename in ("study_agent.db","mastery.db"):
            with sqlite3.connect(root/filename) as conn:conn.execute("CREATE TABLE fixture(id INTEGER)")
        db=runtime/"curriculum-wiki.sqlite3"
        with sqlite3.connect(self.store.path) as source,sqlite3.connect(db) as target:source.backup(target)
        evidence=runtime/"curriculum-wiki/evidence";evidence.mkdir(parents=True)
        (evidence/"manifest.json").write_text('{"verified":"directory only"}')
        destination=Path(self.tmp.name)/"snapshot"
        manifest=snapshot.backup(root,destination)
        self.assertIn(".runtime/curriculum-wiki.sqlite3",manifest["files"])
        self.assertIn(".runtime/curriculum-wiki/evidence/manifest.json",manifest["files"])
        restored=Path(self.tmp.name)/"restored";restored.mkdir()
        snapshot.restore(destination,restored)
        restored_store=cw.WikiStore(restored/".runtime/curriculum-wiki.sqlite3")
        self.assertEqual(restored_store.overview()["counts"],self.store.overview()["counts"])


if __name__=="__main__":unittest.main()
