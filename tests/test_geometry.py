"""Geometry, teaching progress and image isolation; no network/production writes."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from backend import geometry, question_assets, teach, database
from backend.data_paths import workspace
from tests.geometry_cases import corpus_ellipse, corpus_pyramid, construction_case, prepared


class GeometryTest(unittest.TestCase):
    def test_corpus_and_parametric_models(self):
        for factory in (corpus_ellipse,corpus_pyramid,lambda:construction_case("section"),lambda:construction_case("fold"),lambda:construction_case("locus")):
            q,a,raw=factory()
            with self.subTest(question=q):
                compiled=geometry.compile_geometry(raw,q,a)
                self.assertEqual(compiled["status"],"ready",compiled["reason"])
                self.assertTrue(compiled["steps"])
                if compiled["scenes"][0].get("parameter"):
                    self.assertGreaterEqual(len(compiled["scenes"][0]["frames"]),61)
                    self.assertTrue(all(type(v) in (int,float) for f in compiled["scenes"][0]["frames"] for o in f["objects"] if o["kind"]=="point" for v in o["coords"]))

    def test_relation_and_dependency_failures_degrade(self):
        q,a,raw=corpus_pyramid()
        raw["scenes"][0]["objects"][3]["coords"]=[0,0,1]
        out=geometry.compile_geometry(raw,q,a)
        self.assertEqual(out["status"],"unavailable")
        self.assertIn("不满足",out["reason"])
        q,a,raw=corpus_pyramid()
        raw["scenes"][0]["objects"][-1]["b"]="missing"
        self.assertEqual(geometry.compile_geometry(raw,q,a)["status"],"unavailable")

    def test_nonfinite_unsafe_expressions_and_degenerate_conics(self):
        for value in ('__import__("os").system("echo hi")',"t.__class__","1/0","sqrt(-1)","10**100","1e100",float("nan")):
            with self.subTest(value=value),self.assertRaises((ValueError,ArithmeticError)):
                geometry.number(value,{"t":1})
        q,a,raw=corpus_ellipse()
        raw["scenes"][0]["objects"][3]["coefficients"]=[1,0,-1,0,0,0]
        self.assertIn("退化",geometry.compile_geometry(raw,q,a)["reason"])

    def test_partial_scene_survives_bad_scene(self):
        q,a,raw=corpus_pyramid()
        bad=deepcopy(raw["scenes"][0]);bad["id"]="bad";bad["objects"][0]["coords"]=["oops",0,0]
        raw["scenes"].append(bad)
        out=geometry.compile_geometry(raw,q,a)
        self.assertEqual(out["status"],"partial");self.assertEqual(len(out["scenes"]),1)

    def test_one_repair_and_cached_score_changes(self):
        q,a,raw=corpus_ellipse()
        with patch("backend.solver.call_deepseek",side_effect=[("{}",{}),(json.dumps(raw),{"total_tokens":20})]) as call:
            geometry.prepare_geometry(q,a)
            self.assertEqual(call.call_count,2);self.assertEqual(a["geometry"]["status"],"ready")
            a["chunk_results"][0]["steps"][0]["step_difficulty"]={"level":"容易","score":1}
            geometry.prepare_geometry(q,a);self.assertEqual(call.call_count,2)
            a["chunk_results"][0]["steps"][0]["standard_writing"]+=" 新构造"
            call.side_effect=[(json.dumps(raw),{})]
            geometry.prepare_geometry(q,a);self.assertEqual(call.call_count,3)

    def test_timeout_and_missing_conditions_keep_text(self):
        q,a,raw=corpus_pyramid();original=deepcopy(a["chunk_results"])
        with patch("backend.solver.call_deepseek",side_effect=TimeoutError):
            geometry.prepare_geometry(q,a)
        self.assertEqual(a["geometry"]["status"],"unavailable");self.assertEqual(a["chunk_results"],original)
        q,a,raw=corpus_pyramid()
        with patch("backend.solver.call_deepseek",return_value=(json.dumps({"status":"unavailable","reason":"缺少原题图中中点位置"}),{})) as call:
            geometry.prepare_geometry("如图，证明棱锥中的平行关系",a)
        self.assertEqual(call.call_count,1);self.assertIn("缺少",a["geometry"]["reason"])

    def test_multi_chunk_keys_and_hint_scopes(self):
        q,a,raw=corpus_pyramid()
        c=deepcopy(a["chunk_results"][0]);c["chunk_id"]=2;a["chunk_results"].append(c)
        raw["steps"].extend([{**s,"step_key":s["step_key"].replace("1-","2-")} for s in deepcopy(raw["steps"])])
        out=geometry.compile_geometry(raw,q,a)
        self.assertEqual(out["status"],"ready")
        sess={"geometry":out}
        geometry.release_hint(sess,{"chunk_id":1,"step_number":1})
        self.assertEqual(sess["geometry_state"]["released"],{"1-1":1})
        raw["steps"][0]["hint_groups"][0]["visible"].append("future")
        self.assertEqual(geometry.compile_geometry(raw,q,a)["status"],"partial")

    def test_explicit_future_construction_is_not_released(self):
        q,a,raw=corpus_pyramid();raw["scenes"][0]["objects"][-1]["introduced_at"]="1-2"
        out=geometry.compile_geometry(raw,q,a)
        self.assertEqual(out["status"],"partial")
        self.assertNotIn("1-1",[s["step_key"] for s in out["steps"]])
        sess={"geometry":out}
        self.assertIsNone(geometry.release_hint(sess,{"chunk_id":1,"step_number":1}))

    def test_non_geometry_never_calls_model(self):
        a={"chunk_results":[]}
        with patch("backend.solver.call_deepseek") as call:
            geometry.prepare_geometry("求等差数列通项",a)
        call.assert_not_called();self.assertNotIn("geometry",a)

    def test_final_pipeline_prepares_after_formatter(self):
        from backend.solver import step_final_check
        q,a,raw=corpus_pyramid()
        with patch("backend.solver._call_formatter",return_value=(deepcopy(a),None)),patch("backend.solver.call_deepseek",return_value=(json.dumps(raw),{})):
            result=step_final_check(q,a["chunk_results"],[],{})
        self.assertEqual(result["geometry"]["status"],"ready")

    def test_valid_partial_is_kept_when_repair_fails(self):
        q,a,raw=corpus_pyramid()
        raw["steps"]=raw["steps"][:1]
        with patch("backend.solver.call_deepseek",side_effect=[(json.dumps(raw),{}),("{}",{})]):
            geometry.prepare_geometry(q,a)
        self.assertEqual(a["geometry"]["status"],"partial")
        self.assertEqual(len(a["geometry"]["steps"]),1)

    def test_tangent_fixed_point_and_constant_length(self):
        q,a,raw=corpus_ellipse()
        scene=raw["scenes"][0]
        scene["objects"]=[o for o in scene["objects"] if o["id"]!="P"][:2]+[
            {"id":"P","kind":"point","coords":["sqrt(5)*cos(t)","sin(t)"],"base":True},
            {"id":"T","kind":"point","coords":["sqrt(5)*cos(t)-sqrt(5)*sin(t)","sin(t)+cos(t)"]},
            {"id":"ellipse","kind":"conic","coefficients":[.2,0,1,0,0,-1],"base":True},
            {"id":"tangent","kind":"line","a":"P","b":"T"}]
        scene["parameter"]={"name":"t","min":0,"max":6.28,"value":1}
        text="作椭圆切线，焦半径和为2√5，F1为定点。"
        a["chunk_results"][0]["steps"][0]["standard_writing"]=text
        scene["constraints"]=[{"kind":"tangent","a":"P","b":"T","point":"P","conic":"ellipse","source":"作椭圆切线"},
                              {"kind":"length_sum","pairs":[["F1","P"],["F2","P"]],"value":"2*sqrt(5)","source":"焦半径和为2√5"},
                              {"kind":"point_fixed","point":"F1","coords":[-2,0],"source":"F1为定点"}]
        raw["steps"][0]["full_visible"]=["T","tangent"];raw["steps"][0]["hint_groups"]=[{"text":"作P处的切线。","visible":["T","tangent"]}]
        raw["steps"][1]["full_visible"]=["T","tangent"]
        self.assertEqual(geometry.compile_geometry(raw,q,a)["status"],"ready")


class GeometryTeachingTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.ws=workspace(self.tmp.name);self.ws.__enter__();self.addCleanup(self.ws.__exit__,None,None,None)
        self.patcher=patch.object(teach,"_session_manager",teach.TeachSessionManager());self.patcher.start();self.addCleanup(self.patcher.stop)
        database.init_db();self.question,self.answer=prepared();database.save_question(self.question,self.answer)
        self.session=teach.teach_session_start(self.question);self.sid=self.session["session_id"]

    def test_hint_groups_answer_and_cold_restore(self):
        with patch.object(teach,"call_deepseek") as ai:
            first=teach.teach_session_chat(self.sid,"提示",expected_revision=0)
            self.assertEqual(first["geometry_state"]["released"]["1-1"],1)
            with self.assertRaises(teach.TeachingConflict):teach.teach_session_chat(self.sid,"提示",expected_revision=0)
            second=teach.teach_session_chat(self.sid,"提示",expected_revision=1)
            self.assertEqual(second["geometry_state"]["released"]["1-1"],2)
            third=teach.teach_session_chat(self.sid,"提示",expected_revision=2)
            self.assertEqual(third["geometry_state"]["released"]["1-1"],2)
            teach.teach_session_chat(self.sid,"查看答案",expected_revision=3)
            ai.assert_not_called()
        restored=teach.TeachSessionManager().get(self.sid)
        self.assertEqual(restored["geometry_state"]["completed"],["1-1"])
        self.assertEqual(restored["steps"][0]["step_difficulty"]["level"],"困难")
        self.assertEqual(restored["steps"][0]["geometry_key"],"1-1")
        teach.teach_session_chat(self.sid,"跳过",expected_revision=4)
        state=teach.teach_get_session(self.sid)
        self.assertEqual(state["current_step"],1);self.assertNotIn("1-2",state["geometry_state"]["completed"])

    def test_correct_skip_completion_preserves_geometry(self):
        with patch.object(teach,"call_deepseek",return_value=('{"is_correct":true,"feedback":"正确"}',{})):
            teach.teach_session_chat(self.sid,"连接PE",expected_revision=0)
        state=teach.teach_get_session(self.sid)
        self.assertEqual(state["geometry_state"]["completed"],["1-1"])
        result=teach.teach_session_chat(self.sid,"跳过",expected_revision=1)
        self.assertEqual(result["action"],"complete")
        self.assertEqual(result["geometry_state"]["completed"],["1-1","1-2"])
        self.assertEqual(database.find_question(self.question)["geometry"],self.answer["geometry"])

    def test_concurrent_hints_release_once(self):
        def hint():
            with workspace(self.tmp.name):
                try:return teach.teach_session_chat(self.sid,"提示",expected_revision=0)
                except teach.TeachingConflict:return None
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:hint(),range(2)))
        self.assertEqual(sum(x is not None for x in results),1)
        self.assertEqual(teach.teach_get_session(self.sid)["geometry_state"]["released"],{"1-1":1})

    def test_old_question_prepared_once_without_resolving(self):
        q,a,raw=corpus_ellipse();database.save_question(q,a)
        with patch("backend.solver.call_deepseek",return_value=(json.dumps(raw),{})) as ai,patch.object(teach,"step_solver_only") as solve:
            teach.teach_session_start(q);teach.teach_session_start(q)
        solve.assert_not_called();self.assertEqual(ai.call_count,1)
        self.assertEqual(database.find_question(q)["chunk_results"],a["chunk_results"])


class QuestionAssetTest(unittest.TestCase):
    def png(self):
        out=BytesIO();Image.new("RGB",(50,30),"white").save(out,format="PNG");return out.getvalue()

    def test_workspace_access_and_survives_upload_deletion(self):
        app=FastAPI();app.include_router(question_assets.router)
        with tempfile.TemporaryDirectory() as a,tempfile.TemporaryDirectory() as b,TestClient(app) as client:
            with workspace(a):
                ref=question_assets.store_image(self.png())
                self.assertEqual(client.get("/question-assets/"+ref).status_code,200)
                self.assertIn("private",client.get("/question-assets/"+ref).headers["cache-control"])
                self.assertTrue(question_assets.image_messages([ref])[0]["image_url"]["url"].startswith("data:image/png;base64,"))
            with workspace(b):
                self.assertEqual(client.get("/question-assets/"+ref).status_code,404)
                with self.assertRaises(ValueError):question_assets.validate_refs([ref])
            with workspace(a):
                for value in ("../settings.json","/etc/passwd","https://example.com/img.png"):
                    with self.assertRaises(ValueError):question_assets.resolve_asset(value)

    def test_multimodal_retains_page_refs(self):
        from backend.multimodal import parse_file
        with tempfile.TemporaryDirectory() as directory,workspace(directory):
            path=Path(directory)/"upload.png";path.write_bytes(self.png())
            with patch("backend.multimodal._call_multimodal_model",return_value='[{"latex":"题目"}]'):
                result=parse_file(str(path))
            path.unlink()
            self.assertTrue(question_assets.resolve_asset(result[0]["asset_refs"][0]).is_file())

    def test_solver_receives_private_images(self):
        from backend.solver import step_solver_only
        with tempfile.TemporaryDirectory() as directory,workspace(directory):
            ref=question_assets.store_image(self.png())
            with patch("backend.solver.call_deepseek",return_value=("是否数学题：[是]\n是否能做出来：[是]\n板块：立体几何\n解：略",{})) as ai:
                step_solver_only("立体几何题",teacher="xuefeng",asset_refs=[ref])
            self.assertEqual(ai.call_args.kwargs["model"],"glm-5.3-flash")
            self.assertEqual(ai.call_args.kwargs["reasoning_effort"],"medium")
            image=ai.call_args.kwargs["image_content"][0]
            self.assertTrue(image["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_pool_assets_do_not_accept_external_local_paths(self):
        from backend.question_pool import files_directory
        with tempfile.TemporaryDirectory() as directory,workspace(directory):
            root=files_directory().parent;root.mkdir(parents=True)
            safe=root/"figure.png";safe.write_bytes(self.png())
            outside=Path(directory)/"outside.png";outside.write_bytes(self.png())
            refs=question_assets.pool_asset_refs({"occurrences":[{"raw":{"original_file":str(safe)}}]})
            self.assertEqual(len(refs),1)
            self.assertEqual(question_assets.pool_asset_refs({"occurrences":[{"raw":{"original_file":str(outside)}}]}),[])

    def test_diagram_options_keep_labels_and_partial_images_cannot_be_solved(self):
        from backend.question_pool import files_directory
        with tempfile.TemporaryDirectory() as directory, workspace(directory):
            root = files_directory().parent
            root.mkdir(parents=True)
            (root / "a.png").write_bytes(self.png())
            item = {"question": "选择正确的图象", "completeness": "deferred_graphic", "occurrences": [{"raw": {
                "source_root": str(root), "image_refs": [{"path": "a.png", "label": "选项 A"}, {"path": "b.png", "label": "选项 B"}]}}]}
            data = question_assets.pool_asset_data(item)
            self.assertEqual(data["assets"][0]["label"], "选项 A")
            self.assertEqual(data["missing"][0]["label"], "选项 B")
            with self.assertRaisesRegex(ValueError, "题图缺失"):
                question_assets.pool_asset_refs(item, require_complete=True)
            (root / "b.png").write_bytes(self.png())
            self.assertEqual(len(question_assets.pool_asset_data(item)["assets"]), 2)
            self.assertEqual(len(question_assets.pool_asset_refs(item, require_complete=True)), 1)

    def test_pdf_page_rendering_is_cached_across_questions(self):
        from backend.question_pool import files_directory
        import fitz
        with tempfile.TemporaryDirectory() as directory, workspace(directory):
            root = files_directory().parent
            root.mkdir(parents=True)
            pdf = root / "paper.pdf"
            with fitz.open() as doc:
                doc.new_page()
                doc.save(pdf)
            item = {"question": "如图求面积", "occurrences": [{"page_start": 1, "page_end": 1, "raw": {"original_file": str(pdf)}}]}
            question_assets._retain_source.cache_clear()
            with patch("fitz.open", wraps=fitz.open) as opener:
                first = question_assets.pool_asset_refs(item)
                second = question_assets.pool_asset_refs(item)
            self.assertEqual(first, second)
            self.assertEqual(opener.call_count, 1)

    def test_hash_mismatch_and_path_traversal_remain_missing(self):
        from backend.question_pool import files_directory
        with tempfile.TemporaryDirectory() as directory, workspace(directory):
            root = files_directory().parent
            root.mkdir(parents=True)
            (root / "figure.png").write_bytes(self.png())
            outside = Path(directory) / "outside.png"
            outside.write_bytes(self.png())
            item = {"occurrences": [{"raw": {"source_root": str(root), "image_refs": [
                {"path": "figure.png"}, {"path": "../outside.png"}], "image_assets": [{"path": "figure.png", "sha256": "bad-hash"}]}}]}
            data = question_assets.pool_asset_data(item)
            self.assertEqual(data["asset_refs"], [])
            self.assertEqual(len(data["missing"]), 2)

    def test_transparent_diagrams_get_white_background(self):
        with tempfile.TemporaryDirectory() as directory, workspace(directory):
            out = BytesIO()
            Image.new("RGBA", (5, 5), (0, 0, 0, 0)).save(out, format="PNG")
            ref = question_assets.store_image(out.getvalue())
            with Image.open(question_assets.resolve_asset(ref)) as image:
                self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))

    def test_solver_preserves_image_option_mapping_in_input(self):
        from backend.solver import step_solver_only
        with tempfile.TemporaryDirectory() as directory, workspace(directory):
            ref=question_assets.store_image(self.png())
            with patch('backend.solver.call_deepseek', return_value=('答案 A', {})) as ai:
                step_solver_only('选择图象', asset_refs=[ref], asset_labels=['选项 A、选项 B'])
            self.assertIn('第 1 张附图：选项 A、选项 B', ai.call_args.args[1])
