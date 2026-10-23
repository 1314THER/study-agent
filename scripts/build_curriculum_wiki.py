"""Initialize the wiki and optionally reuse existing, evidence-checked pool matches.

No OCR, solver or paid model is invoked. All imported mappings remain drafts.
"""
import argparse
from collections import Counter
from contextlib import closing
import json
import hashlib
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.curriculum_wiki import WikiStore,storage_path,attach_question,QuestionLink,digest
from backend import question_pool as pool
from backend.data_paths import data_path


def link_saved_evidence(store):
    """Link preserved source fingerprints and front-matter excerpts, once."""
    from backend.curriculum_wiki import evidence_root
    root=evidence_root()/"evidence"
    if not root.is_dir():return
    for bid in ("b1","b2","s1","s2","s3"):
        source=store.entity("source:"+bid)["entity"];data=source["data"]
        path=root/data["evidence_file"]
        if not path.is_file():continue
        h=hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda:stream.read(1048576),b""):h.update(chunk)
        value=h.hexdigest()
        if data.get("linked_front_hash")==value:continue
        excerpts=list(data.get("excerpts",[]));locators={e["locator"] for e in excerpts}
        ocr=root/(path.stem+"-ocr.json")
        text=root/(path.stem+"-front.txt")
        if ocr.is_file():
            additions=[{"text":r["text"],"locator":"PDF第"+str(r["pdf_page"])+"页（本机OCR，转录待校）","verification":"ocr_needs_review"} for r in json.loads(ocr.read_text()) if len(r["text"])>50]
        elif text.is_file():
            additions=[{"text":text.read_text()[:40000],"locator":"PDF前12页文字层（前置页与首节，转录待校）","verification":"extracted_needs_review"}]
        else:additions=[]
        excerpts.extend(e for e in additions if e["locator"] not in locators)
        store.edit(source["id"],{"data":{"file_sha256":value,"file_bytes":path.stat().st_size,
            "linked_front_hash":value,"excerpts":excerpts,
            "source_hash":digest({"file_sha256":value,"excerpts":excerpts}),
            "extraction_note":"目录已经核对；正文前置页转录仅作为待校来源片段，不代表整册正文已审核。"}},
            store.revision(),"关联已保存原书的文件指纹与待校转录，保留人工片段。")


def import_existing_matches(store,limit=288):
    path=Path(data_path("routine-review.sqlite3",ROOT/".runtime/routine-review.sqlite3"))
    if not path.exists():return {"imported":0,"reason":"没有现有套路审核结果，不生成虚构匹配。"}
    snap=store.export();nodes={n["id"]:n for n in snap["entities"]}
    anchors={}
    for e in snap["edges"]:
        if e["kind"]=="routine_candidate" and nodes[e["source"]]["kind"]=="lesson" and e["status"]!="rejected":
            anchors.setdefault(e["target"].removeprefix("routine:"),[]).append(nodes[e["source"]])
    imported,skips,seen=0,Counter(),set()
    existing={(n["data"]["pool_item_id"],n["data"].get("method")) for n in nodes.values() if n["kind"]=="solution"}
    with closing(sqlite3.connect("file:"+str(path)+"?mode=ro",uri=True)) as c:
        c.row_factory=sqlite3.Row
        rows=c.execute("""SELECT item_id,item_json,result_json,primary_id,run_id FROM review_items
            WHERE status='classified' AND primary_id IS NOT NULL ORDER BY item_id DESC""")
        for row in rows:
            rid=row["primary_id"]
            if rid in seen or rid not in anchors:continue
            data=json.loads(row["result_json"] or "{}");cl=data.get("classification",{})
            if cl.get("confidence")!="high" or cl.get("needs_review"):skips["uncertain"]+=1;continue
            item=pool.get_item(row["item_id"]);old=json.loads(row["item_json"])
            if item["completeness"]!="complete" or not item["solution"].strip():skips["incomplete"]+=1;continue
            if old.get("version")!=item["version"] or old.get("question")!=item["question"]:skips["stale"]+=1;continue
            fields={"question":item["question"],"solution":item["solution"],"answer":item["answer"]}
            evidence=cl.get("evidence") or []
            if not evidence or any(not isinstance(e.get("quote"),str) or not e["quote"].strip() or e["quote"] not in fields.get(e.get("field"),"") for e in evidence):
                skips["unverified_quote"]+=1;continue
            lesson=min(anchors[rid],key=lambda n:(n["data"].get("lesson_type")!="习题",n["position"]))
            method=cl.get("method_summary") or nodes["routine:"+rid]["title"]
            if (item["id"],method) in existing:seen.add(rid);continue
            origin=item["occurrences"][0]
            req=QuestionLink(expected_revision=store.revision(),reason="复用已存套路分类的原文依据；课时归属和完整前置仍待人工审核。"+method,
                lesson_id=lesson["id"],pool_item_id=item["id"],occurrence_id=origin["id"],method=method,
                routine_ids=[rid]+cl.get("secondary_routine_ids",[]),steps=[],knowledge_ids=[])
            result=attach_question(store,req,origin="existing_model_evidence")
            # Preserve the classification's actual quotes and run, without
            # pretending its curricular prerequisite analysis is complete.
            store.edit(result["result"],{"data":{"classification_evidence":evidence,"review_run_id":row["run_id"],
                "matching_confidence":"high","requirements_status":"unknown","match_status":"pending"}},
                store.revision(),"保存原分类依据；课程匹配保持待审核。")
            imported+=1;seen.add(rid)
            if imported>=limit:break
    return {"imported":imported,"skipped":dict(skips),"scope":"既有原题池；不是教辅全量题目；未新增模型调用。"}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--import-existing-matches",action="store_true")
    parser.add_argument("--limit",type=int,default=288)
    parser.add_argument("--report",default="outputs/curriculum-wiki-report.json")
    args=parser.parse_args()
    store=WikiStore(storage_path())
    link_saved_evidence(store)
    report={"overview":store.overview()}
    if args.import_existing_matches:report["import"]=import_existing_matches(store,args.limit)
    report["overview"]=store.overview();report["checks"]=store.checks()
    path=Path(args.report);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({"counts":report["overview"]["counts"],"coverage":report["overview"]["coverage"]["textbook"],
                      "import":report.get("import"),"report":str(path)},ensure_ascii=False))


if __name__=="__main__":main()
