"""Owner curriculum research ledger. SQLite is authoritative; no implicit AI calls."""
from __future__ import annotations
from contextlib import contextmanager
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, StrictInt, StrictStr

from backend.data_paths import data_path
from backend.routine_review import require_owner
from backend import curriculum_seed

ROOT = Path(__file__).resolve().parent.parent
KINDS = {"book","chapter","section","outline","lesson","knowledge","routine","source","solution"}
EDGE_KINDS = {"prerequisite","requires","teaches","practices","routine_candidate","related","covers"}
STATES = {"draft","confirmed","deferred","rejected"}
READING = {"entry_only","directory_pending","directory_read","partial","read","authored","failed"}
ALLOCATION = {"system_proposed","textbook_explicit","workbook_explicit","human"}
SCHEMA_VERSION = 1
PROMPT_VERSION = "curriculum-evidence-v1"
router = APIRouter(prefix="/curriculum-wiki",tags=["数学课时库"],dependencies=[Depends(require_owner)])
page_router = APIRouter(dependencies=[Depends(require_owner)])


def dumps(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))


def digest(value):
    return sha256(dumps(value).encode()).hexdigest()


def storage_path():
    return Path(data_path("curriculum-wiki.sqlite3",ROOT/".runtime/curriculum-wiki.sqlite3"))


def evidence_root():
    return Path(data_path("curriculum-wiki",ROOT/".runtime/curriculum-wiki"))


def actor():
    from backend.identity import current_user_id
    return current_user_id()


def get_store():
    return WikiStore(storage_path())


class WikiStore:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if self.path.is_symlink():raise HTTPException(400,"课时数据库路径不可用。")
        with self.connection() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS cw_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS cw_entities(
                    id TEXT PRIMARY KEY,kind TEXT NOT NULL,title TEXT NOT NULL,book_id TEXT NOT NULL DEFAULT '',
                    section_id TEXT NOT NULL DEFAULT '',category TEXT NOT NULL DEFAULT '',position REAL NOT NULL DEFAULT 0,
                    status TEXT NOT NULL DEFAULT 'draft',active INTEGER NOT NULL DEFAULT 1,
                    revision INTEGER NOT NULL DEFAULT 0,data_json TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS cw_entity_kind ON cw_entities(kind,book_id,position);
                CREATE TABLE IF NOT EXISTS cw_edges(
                    id TEXT PRIMARY KEY,source TEXT NOT NULL REFERENCES cw_entities(id),
                    target TEXT NOT NULL REFERENCES cw_entities(id),kind TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'draft',
                    evidence_json TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 0,UNIQUE(source,target,kind));
                CREATE INDEX IF NOT EXISTS cw_edge_source ON cw_edges(source,kind);
                CREATE INDEX IF NOT EXISTS cw_edge_target ON cw_edges(target,kind);
                CREATE TABLE IF NOT EXISTS cw_history(
                    revision INTEGER PRIMARY KEY,action TEXT NOT NULL,actor TEXT NOT NULL,reason TEXT NOT NULL,
                    before_json TEXT NOT NULL,after_json TEXT NOT NULL,created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cw_suggestions(
                    id TEXT PRIMARY KEY,run_id TEXT NOT NULL,entity_id TEXT NOT NULL,base_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created_at REAL NOT NULL,
                    UNIQUE(run_id,entity_id));
                CREATE TABLE IF NOT EXISTS cw_runs(
                    id TEXT PRIMARY KEY,request_id TEXT UNIQUE NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,
                    config_json TEXT NOT NULL,item_ids_json TEXT NOT NULL,completed_json TEXT NOT NULL DEFAULT '[]',
                    error TEXT NOT NULL DEFAULT '',job_id TEXT,revision INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cw_cache(key TEXT PRIMARY KEY,payload_json TEXT NOT NULL);
            """)
            c.execute("BEGIN IMMEDIATE")
            if not c.execute("SELECT 1 FROM cw_meta WHERE key='schema_version'").fetchone():
                from backend.routine_classification import load_catalog
                nodes,edges=curriculum_seed.build_seed(load_catalog())
                for n in nodes:self._put(c,n,0)
                for e in edges:self._put_edge(c,e,0)
                c.executemany("INSERT INTO cw_meta VALUES (?,?)",[("schema_version",str(SCHEMA_VERSION)),
                    ("revision","0"),("seed_version",curriculum_seed.VERSION)])
                self._validate(c)
        self.path.chmod(0o600)

    @contextmanager
    def connection(self):
        c=sqlite3.connect(self.path,timeout=15)
        c.row_factory=sqlite3.Row
        c.execute("PRAGMA foreign_keys=ON")
        c.execute("PRAGMA journal_mode=WAL")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback();raise
        finally:c.close()

    @staticmethod
    def _node(row):
        if row is None:raise HTTPException(404,"课时或知识记录不存在。")
        d=dict(row);d["data"]=json.loads(d.pop("data_json"));d["active"]=bool(d["active"])
        return d

    @staticmethod
    def _edge(row):
        d=dict(row);d["evidence"]=json.loads(d.pop("evidence_json"));return d

    def _get(self,c,id):
        return self._node(c.execute("SELECT * FROM cw_entities WHERE id=?",(id,)).fetchone())

    @staticmethod
    def _revision(c):
        return int(c.execute("SELECT value FROM cw_meta WHERE key='revision'").fetchone()[0])

    def revision(self):
        with self.connection() as c:return self._revision(c)

    def _put(self,c,n,revision):
        if n["kind"] not in KINDS or n.get("status","draft") not in STATES:
            raise HTTPException(422,"记录类型或审核状态无效。")
        if not isinstance(n.get("title"),str) or not n["title"].strip() or len(n["title"])>300:
            raise HTTPException(422,"标题须为1至300个字符。")
        if len(dumps(n.get("data",{})))>250000:raise HTTPException(422,"单条正文过长。")
        c.execute("""INSERT INTO cw_entities VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET title=excluded.title,book_id=excluded.book_id,
            section_id=excluded.section_id,category=excluded.category,position=excluded.position,
            status=excluded.status,active=excluded.active,revision=excluded.revision,data_json=excluded.data_json""",
            (n["id"],n["kind"],n["title"],n.get("book_id",""),n.get("section_id",""),n.get("category",""),
             n.get("position",0),n.get("status","draft"),int(n.get("active",True)),revision,dumps(n.get("data",{}))))

    def _put_edge(self,c,e,revision):
        if e["kind"] not in EDGE_KINDS or e.get("status","draft") not in STATES:
            raise HTTPException(422,"关系类型或审核状态无效。")
        evidence=e.get("evidence",{})
        if not isinstance(evidence,dict) or not evidence.get("reason"):
            raise HTTPException(422,"关系必须说明依据和理由。")
        sid=evidence.get("source_id")
        if sid and self._get(c,sid)["kind"]!="source":raise HTTPException(422,"证据来源无效。")
        c.execute("""INSERT INTO cw_edges VALUES (?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
            source=excluded.source,target=excluded.target,kind=excluded.kind,status=excluded.status,
            evidence_json=excluded.evidence_json,revision=excluded.revision""",
            (e["id"],e["source"],e["target"],e["kind"],e.get("status","draft"),dumps(evidence),revision))

    def _snapshot(self,c):
        return {"entities":[self._node(r) for r in c.execute("SELECT * FROM cw_entities ORDER BY id")],
                "edges":[self._edge(r) for r in c.execute("SELECT * FROM cw_edges ORDER BY id")]}

    def _validate(self,c):
        nodes={r["id"]:r for r in c.execute("SELECT * FROM cw_entities")}
        adjacency={}
        for e in c.execute("SELECT * FROM cw_edges WHERE status!='rejected'"):
            a,b=nodes.get(e["source"]),nodes.get(e["target"])
            if not a or not b:raise HTTPException(422,"关系引用不存在的记录。")
            if e["kind"]=="prerequisite":
                if a["kind"]!="lesson" or b["kind"]!="lesson":raise HTTPException(422,"前置关系只能连接课时。")
                adjacency.setdefault(e["source"],[]).append(e["target"])
            if e["kind"] in ("requires","teaches") and (a["kind"] not in ("lesson","solution","knowledge") or b["kind"]!="knowledge"):
                raise HTTPException(422,"知识关系的目标必须是知识点。")
            if e["kind"]=="practices" and (a["kind"]!="lesson" or b["kind"]!="solution"):
                raise HTTPException(422,"练习关系必须从课时指向解法。")
            if e["kind"]=="routine_candidate" and (a["kind"] not in ("lesson","solution") or b["kind"]!="routine"):
                raise HTTPException(422,"套路候选必须引用独立套路目录。")
        seen,visiting=set(),set()
        def visit(id):
            if id in visiting:raise HTTPException(422,"前置课时形成循环，请先修改依赖关系。")
            if id in seen:return
            visiting.add(id)
            for other in adjacency.get(id,[]):visit(other)
            visiting.remove(id);seen.add(id)
        for id in adjacency:visit(id)
        for n in nodes.values():
            if n["kind"]=="lesson" and n["active"]:
                d=json.loads(n["data_json"])
                if not isinstance(d.get("body"),str) or not d["body"].strip() or not isinstance(d.get("objectives"),list) or not d["objectives"] or any(not isinstance(x,str) or not x.strip() for x in d["objectives"]):
                    raise HTTPException(422,"课时必须保留具体内容和学习目标。")
                if d.get("allocation","system_proposed") not in ALLOCATION:raise HTTPException(422,"课时拆分依据无效。")
            if n["kind"]=="source":
                d=json.loads(n["data_json"])
                if d.get("reading_status") not in READING:raise HTTPException(422,"来源读取状态无效。")

    def mutate(self,expected,action,reason,fn):
        if type(expected) is not int or expected<0:raise HTTPException(422,"须提供当前版本。")
        if not isinstance(reason,str) or not reason.strip():raise HTTPException(422,"请填写修改或审核理由。")
        with self.connection() as c:
            c.execute("BEGIN IMMEDIATE");rev=self._revision(c)
            if rev!=expected:raise HTTPException(409,"资料已被另一页面修改，请刷新后对照合并；当前输入尚未保存。")
            before=self._snapshot(c);value=fn(c,rev+1);self._validate(c);after=self._snapshot(c)
            # Store only changed records; revisions remain compact and restorable.
            diff={}
            for key in ("entities","edges"):
                a={r["id"]:r for r in before[key]};b={r["id"]:r for r in after[key]}
                ids={id for id in set(a)|set(b) if a.get(id)!=b.get(id)}
                diff[key]={"before":{id:a.get(id) for id in ids},"after":{id:b.get(id) for id in ids}}
            c.execute("INSERT INTO cw_history VALUES (?,?,?,?,?,?,?)",
                      (rev+1,action,actor(),reason,dumps({k:v["before"] for k,v in diff.items()}),
                       dumps({k:v["after"] for k,v in diff.items()}),time.time()))
            c.execute("UPDATE cw_meta SET value=? WHERE key='revision'",(str(rev+1),))
            return {"revision":rev+1,"result":value}

    def entity(self,id):
        with self.connection() as c:
            return {"revision":self._revision(c),"entity":self._get(c,id)}

    def entities(self,kind=None):
        with self.connection() as c:
            rows=c.execute("SELECT * FROM cw_entities WHERE (? IS NULL OR kind=?) AND active=1 ORDER BY position,id",(kind,kind))
            return [self._node(r) for r in rows]

    def edit(self,id,changes,expected,reason):
        if set(changes)-{"title","category","status","data"}:raise HTTPException(422,"不可修改编号、类型或直接修改排序。")
        def apply(c,rev):
            n=self._get(c,id)
            if "data" in changes:
                if not isinstance(changes["data"],dict):raise HTTPException(422,"data必须是对象。")
                # Original question text is maintained in the original pool.
                if n["kind"]=="solution" and set(changes["data"])&{"pool_item_id","occurrence_id","item_version","question_hash",
                    "source_id","source_locator","question_snapshot","answer_snapshot","solution_snapshot","source_snapshot_hash"}:
                    raise HTTPException(422,"题目身份和来源快照不可直接改写，请重新关联。")
                n["data"].update(changes["data"])
            n.update({k:v for k,v in changes.items() if k!="data"})
            self._put(c,n,rev);return id
        return self.mutate(expected,"edit:"+id,reason,apply)

    def relation(self,e,expected,reason):
        def apply(c,rev):
            current=c.execute("SELECT * FROM cw_edges WHERE id=?",(e.get("id",""),)).fetchone()
            value={**(self._edge(current) if current else {}),**e}
            value.setdefault("id",uuid.uuid4().hex)
            for key in ("source","target","kind"):
                if not isinstance(value.get(key),str):raise HTTPException(422,"关系缺少"+key)
            value.setdefault("evidence",{"source_id":"source:editorial","reason":reason,"origin":"human"})
            try:self._put_edge(c,value,rev)
            except sqlite3.IntegrityError as exc:raise HTTPException(422,"关系重复或引用记录不存在。") from exc
            return value["id"]
        return self.mutate(expected,"relation",reason,apply)

    def reorder(self,ids,expected,reason):
        def apply(c,rev):
            active={r[0] for r in c.execute("SELECT id FROM cw_entities WHERE kind='lesson' AND active=1")}
            if len(ids)!=len(set(ids)) or set(ids)!=active:raise HTTPException(422,"重排须恰好包含每个有效课时一次。")
            for i,id in enumerate(ids,1):c.execute("UPDATE cw_entities SET position=?,revision=? WHERE id=?",(i*10,rev,id))
            return {"lessons":len(ids)}
        result=self.mutate(expected,"reorder",reason,apply);result["warnings"]=self.checks()["warnings"];return result

    def split(self,id,parts,expected,reason):
        if not 2<=len(parts)<=8:raise HTTPException(422,"一次可拆分为2至8课。")
        def apply(c,rev):
            old=self._get(c,id)
            if old["kind"]!="lesson" or not old["active"]:raise HTTPException(422,"只能拆分有效课时。")
            self._archive(c,old,rev)
            ids=[]
            for i,part in enumerate(parts):
                if set(part)-{"title","body","objectives","knowledge_ids"}:raise HTTPException(422,"拆分字段无效。")
                n=deepcopy(old);n.update(id="lesson:"+uuid.uuid4().hex,title=part["title"],active=True,status="draft",position=old["position"]+i/10)
                n["data"].update(body=part["body"],objectives=part["objectives"],allocation="human",split_from=id,new_knowledge=[])
                self._put(c,n,rev);ids.append(n["id"])
            incoming=[self._edge(e) for e in c.execute("SELECT * FROM cw_edges WHERE source=? OR target=?",(id,id))]
            for e in incoming:
                if e["kind"]=="teaches":
                    source=next((ids[i] for i,p in enumerate(parts) if e["target"] in p.get("knowledge_ids",[])),ids[0])
                    self._clone_edge(c,e,source,e["target"],rev)
                elif e["source"]==id:
                    for new in ids:self._clone_edge(c,e,new,e["target"],rev)
                elif e["target"]==id:self._clone_edge(c,e,e["source"],ids[-1],rev)
                c.execute("DELETE FROM cw_edges WHERE id=?",(e["id"],))
            for a,b in zip(ids[1:],ids):
                self._put_edge(c,{"id":uuid.uuid4().hex,"source":a,"target":b,"kind":"prerequisite",
                    "evidence":{"source_id":"source:editorial","reason":reason,"origin":"human"}},rev)
            return ids
        return self.mutate(expected,"split:"+id,reason,apply)

    def _archive(self,c,n,rev):
        n["active"]=False;self._put(c,n,rev)

    def _clone_edge(self,c,e,source,target,rev):
        if source==target:return
        existing=c.execute("SELECT id FROM cw_edges WHERE source=? AND target=? AND kind=?",(source,target,e["kind"])).fetchone()
        if existing:return
        self._put_edge(c,{**e,"id":uuid.uuid4().hex,"source":source,"target":target},rev)

    def merge(self,ids,title,expected,reason):
        if len(set(ids))!=len(ids) or not 2<=len(ids)<=8:raise HTTPException(422,"请选择2至8个不同课时。")
        def apply(c,rev):
            old=[self._get(c,id) for id in ids]
            if any(n["kind"]!="lesson" or not n["active"] for n in old):raise HTTPException(422,"只能合并有效课时。")
            if len({n["book_id"] for n in old})!=1:raise HTTPException(422,"不同册次请保留独立课时并建立联系。")
            n=deepcopy(min(old,key=lambda x:x["position"]));n.update(id="lesson:"+uuid.uuid4().hex,title=title,status="draft")
            n["data"].update(body="\n\n".join(x["data"]["body"] for x in old),
                objectives=[o for x in old for o in x["data"]["objectives"]],
                duration_minutes=sum(x["data"].get("duration_minutes",45) for x in old),
                new_knowledge=[],allocation="human",merged_from=ids)
            self._put(c,n,rev)
            for x in old:self._archive(c,x,rev)
            for row in list(c.execute("SELECT * FROM cw_edges")):
                e=self._edge(row)
                if e["source"] in ids or e["target"] in ids:
                    self._clone_edge(c,e,n["id"] if e["source"] in ids else e["source"],n["id"] if e["target"] in ids else e["target"],rev)
                    c.execute("DELETE FROM cw_edges WHERE id=?",(e["id"],))
            return n["id"]
        return self.mutate(expected,"merge",reason,apply)

    def history(self):
        with self.connection() as c:
            return [dict(r) for r in c.execute("SELECT revision,action,actor,reason,created_at FROM cw_history ORDER BY revision DESC LIMIT 100")]

    def history_detail(self,revision):
        with self.connection() as c:
            r=c.execute("SELECT * FROM cw_history WHERE revision=?",(revision,)).fetchone()
            if not r:raise HTTPException(404,"修订记录不存在。")
            d=dict(r);d["before"]=json.loads(d.pop("before_json"));d["after"]=json.loads(d.pop("after_json"));return d

    def restore(self,target,expected,reason):
        event=self.history_detail(target)
        def apply(c,rev):
            # Refuse to silently undo later edits to any affected entity/edge.
            current=self._snapshot(c)
            for key in ("entities","edges"):
                now={x["id"]:x for x in current[key]}
                for id,value in event["after"][key].items():
                    if now.get(id)!=value:raise HTTPException(409,"该内容已有后续修改，请通过差异面板手动合并。")
            for id in event["after"]["edges"]:c.execute("DELETE FROM cw_edges WHERE id=?",(id,))
            for id,n in event["before"]["entities"].items():
                if n:self._put(c,n,rev)
                else:c.execute("DELETE FROM cw_entities WHERE id=?",(id,))
            for e in event["before"]["edges"].values():
                if e:self._put_edge(c,e,rev)
            return target
        return self.mutate(expected,"restore:"+str(target),reason,apply)

    def export(self):
        with self.connection() as c:
            result=self._snapshot(c)
            return {"schema_version":SCHEMA_VERSION,"seed_version":curriculum_seed.VERSION,
                "revision":self._revision(c),"authority":"sqlite","wiki_adapter":"stable-id-links-v1",
                **result,"links":{n["id"]:"/curriculum-wiki.html?entity="+n["id"] for n in result["entities"]}}

    def checks(self):
        snapshot=self.export();nodes={n["id"]:n for n in snapshot["entities"]};edges=[e for e in snapshot["edges"] if e["status"]!="rejected"]
        lessons={id:n for id,n in nodes.items() if n["kind"]=="lesson" and n["active"] and n["status"]!="rejected"}
        taught={}
        for e in edges:
            if e["kind"]=="teaches" and e["source"] in lessons:taught.setdefault(e["target"],[]).append(e["source"])
        warnings=[]
        solution_stages={}
        for sol in nodes.values():
            if sol["kind"]!="solution" or not sol["active"]:continue
            required=[e["target"] for e in edges if e["source"]==sol["id"] and e["kind"]=="requires"]
            locations=[]
            missing=[]
            for kid in required:
                options=taught.get(kid,[])
                if options:locations.append(min(options,key=lambda id:lessons[id]["position"]))
                else:missing.append(kid)
            earliest=max(locations,key=lambda id:lessons[id]["position"]) if locations and not missing else None
            solution_stages[sol["id"]]={"earliest_lesson_id":earliest,"requirements":required,
                "unintroduced":missing,"scope":"仅按已声明前置计算，完整性仍需人工核查",
                "requirements_status":sol["data"].get("requirements_status","unknown")}
        for e in edges:
            if e["kind"]=="requires" and e["source"] in lessons:
                if not any(lessons[l]["position"]<=lessons[e["source"]]["position"] for l in taught.get(e["target"],[])):
                    warnings.append({"type":"knowledge_order","lesson_id":e["source"],"required_id":e["target"],"message":"所需知识点尚未引入或安排在当前课之后。"})
            if e["kind"]=="prerequisite" and e["source"] in lessons and e["target"] in lessons:
                if lessons[e["target"]]["position"]>=lessons[e["source"]]["position"]:
                    warnings.append({"type":"lesson_order","lesson_id":e["source"],"required_id":e["target"],"message":"前置课时安排在当前课之后。"})
        for e in edges:
            if e["kind"]!="practices" or e["source"] not in lessons:continue
            lesson=lessons[e["source"]];sol=nodes[e["target"]]
            reqs=[r["target"] for r in edges if r["source"]==sol["id"] and r["kind"]=="requires"]
            missing=[k for k in reqs if not any(lessons[l]["position"]<=lesson["position"] for l in taught.get(k,[]))]
            if missing:warnings.append({"type":"advanced_solution","lesson_id":lesson["id"],"solution_id":sol["id"],"missing_knowledge":missing,"message":"此解法需要尚未学到或尚无引入课时的知识。"})
            if not reqs:warnings.append({"type":"unknown_requirements","lesson_id":lesson["id"],"solution_id":sol["id"],"message":"解法前置知识尚未核实，不能判为适合本课。"})
        return {"revision":snapshot["revision"],"dag_valid":True,"warnings":warnings,"teaching_locations":taught,
                "solution_stages":solution_stages}

    def solution_freshness(self,solution):
        from backend import question_pool as pool
        data=solution["data"]
        try:
            item=pool.get_item(data["pool_item_id"])
            stale=item["version"]!=data["item_version"] or digest({"question":item["question"],"answer":item["answer"],"solution":item["solution"]})!=data["question_hash"]
            origin=next((o for o in item["occurrences"] if o["id"]==data["occurrence_id"]),None)
            if origin is None:stale=True
            if data.get("source_snapshot_hash"):
                source=self.entity(data["source_id"])["entity"]
                if digest(source["data"])!=data["source_snapshot_hash"]:stale=True
            return {"stale":stale,"reason":"原题版本或出处已变化，保留原匹配并需重新核对。" if stale else "",
                    "item":item}
        except HTTPException as exc:
            if exc.status_code!=404:raise
            return {"stale":True,"reason":"原题记录已不可用。","item":None}

    def detail(self,id):
        snapshot=self.export();lookup={n["id"]:n for n in snapshot["entities"]}
        if id not in lookup:raise HTTPException(404,"课时记录不存在。")
        n=lookup[id];edges=[e for e in snapshot["edges"] if e["source"]==id or e["target"]==id]
        nearby={e["target"] if e["source"]==id else e["source"] for e in edges}
        solution_ids={e["target"] for e in edges if e["source"]==id and e["kind"]=="practices" and e["status"]!="rejected"}
        solutions=[lookup[x] for x in solution_ids]
        checks=self.checks()
        for sol in solutions:
            sol["freshness"]=self.solution_freshness(sol)
            sol["relations"]=[e for e in snapshot["edges"] if e["source"]==sol["id"]]
            sol["stage"]=checks["solution_stages"].get(sol["id"])
        lessons=sorted([x for x in snapshot["entities"] if x["kind"]=="lesson" and x["active"]],key=lambda x:x["position"])
        index=next((i for i,x in enumerate(lessons) if x["id"]==id),None)
        return {"revision":snapshot["revision"],"entity":n,"relations":edges,
            "related":[lookup[x] for x in nearby],"solutions":solutions,
            "warnings":[w for w in checks["warnings"] if w["lesson_id"]==id],
            "previous":lessons[index-1]["id"] if index is not None and index>0 else None,
            "next":lessons[index+1]["id"] if index is not None and index+1<len(lessons) else None}

    def overview(self):
        snap=self.export();nodes=snap["entities"];edges=snap["edges"]
        active=[n for n in nodes if n["active"]];lessons=[n for n in active if n["kind"]=="lesson"]
        outlines=[n for n in active if n["kind"] in ("section","outline")]
        covered={e["source"] for e in edges if e["kind"]=="covers" and e["status"]!="rejected"}
        workbook=[n for n in active if n["kind"]=="source" and n["data"].get("source_type")=="workbook"]
        solutions=[n for n in active if n["kind"]=="solution"]
        routines=[n for n in active if n["kind"]=="routine"]
        mapped={e["target"] for e in edges if e["kind"]=="routine_candidate" and e["status"]!="rejected"}
        return {"revision":snap["revision"],"seed_version":snap["seed_version"],
            "books":[n for n in active if n["kind"]=="book"],
            "chapters":[n for n in active if n["kind"]=="chapter"],
            "counts":{"lessons":len(lessons),"knowledge":sum(n["kind"]=="knowledge" for n in active),
                      "solutions":len(solutions),"routines":len(routines)},
            "coverage":{"textbook":{"covered":len(covered & {n["id"] for n in outlines}),"total":len(outlines),
                "label":"目录节点已安排课时；不代表已人工审核","verified":sum(n["data"].get("directory_status")=="verified" for n in outlines)},
                "workbooks":[{"id":n["id"],"title":n["title"],**n["data"]} for n in workbook],
                "matching":{"mapped":sum(any(e["source"]==s["id"] and e["kind"]=="routine_candidate" and e["status"]!="rejected" for e in edges) for s in solutions),
                            "total":len(solutions),"label":"仅统计已关联题目解法，不代表原题池或教辅全量"},
                "human":{"confirmed":sum(n["status"]=="confirmed" for n in lessons+solutions),"total":len(lessons+solutions)}},
            "routine_gaps":[{"id":n["id"],"title":n["title"],"reason":"尚无足够课程关联证据，等待人工指定。"} for n in routines if n["id"] not in mapped]}


class Change(BaseModel):
    expected_revision: StrictInt = Field(...,ge=0)
    reason: StrictStr = Field(...,min_length=1,max_length=5000)
    class Config:extra="forbid"

class Edit(Change):
    changes: dict

class Relation(Change):
    relation: dict

class Order(Change):
    lesson_ids: list[str]

class Split(Change):
    parts: list[dict]

class Merge(Change):
    lesson_ids: list[str]
    title: str = Field(...,min_length=1,max_length=300)


class QuestionLink(Change):
    lesson_id: str
    pool_item_id: StrictInt = Field(...,ge=1)
    occurrence_id: StrictInt = Field(...,ge=1)
    subquestion: str = Field("整题",max_length=200)
    method: str = Field(...,min_length=1,max_length=1000)
    steps: list[str] = Field(default_factory=list,max_items=30)
    knowledge_ids: list[str] = Field(default_factory=list,max_items=50)
    routine_ids: list[str] = Field(default_factory=list,max_items=8)
    stage: str = Field("巩固",max_length=100)
    source_id: str = ""


def attach_question(store,req,*,origin="human",status="draft"):
    from backend import question_pool as pool
    item=pool.get_item(req.pool_item_id)
    occurrence=next((o for o in item["occurrences"] if o.get("id")==req.occurrence_id),None)
    if not occurrence:raise HTTPException(422,"出处不属于所选原题。")
    def apply(c,rev):
        lesson=store._get(c,req.lesson_id)
        if lesson["kind"]!="lesson" or not lesson["active"]:raise HTTPException(422,"请选择有效课时。")
        for id in req.knowledge_ids:
            if store._get(c,id)["kind"]!="knowledge":raise HTTPException(422,"请选择有效知识点。")
        routines=[x if x.startswith("routine:") else "routine:"+x for x in req.routine_ids]
        for id in routines:
            if store._get(c,id)["kind"]!="routine":raise HTTPException(422,"请选择目录套路编号。")
        sid=req.source_id
        if not sid:
            bound=[store._node(r) for r in c.execute("SELECT * FROM cw_entities WHERE kind='source'") if
                   json.loads(r["data_json"]).get("source_type")=="workbook" and
                   json.loads(r["data_json"]).get("pool_source_id")==occurrence["source_id"]]
            sid=bound[0]["id"] if len(bound)==1 else "source:pool:"+str(occurrence["source_id"])
        existing=c.execute("SELECT * FROM cw_entities WHERE id=?",(sid,)).fetchone()
        if not existing:
            store._put(c,dict(id=sid,kind="source",title=occurrence["source_name"],data={
                "source_type":"question_pool","reading_status":"partial","url":occurrence.get("url",""),
                "edition":occurrence.get("revision"),"pool_source_id":occurrence["source_id"],
                "scope":"引用已读取的原题池具体题目，不代表完整读取原书","read_units":1,"total_units":None}),rev)
        else:
            source=store._node(existing)
            if source["kind"]!="source":raise HTTPException(422,"来源类型无效。")
            if source["data"].get("source_type")=="workbook" and source["data"].get("pool_source_id")!=occurrence["source_id"]:
                raise HTTPException(422,"教辅来源必须先绑定真实原书题源，不能将其他题目伪标为教辅习题。")
        identity=digest({"item":req.pool_item_id,"occurrence":req.occurrence_id,"subquestion":req.subquestion,"method":req.method})
        id="solution:"+identity[:24]
        previous=c.execute("SELECT * FROM cw_entities WHERE id=?",(id,)).fetchone()
        if previous:
            n=store._node(previous)
            if n["data"]["item_version"]!=item["version"]:raise HTTPException(409,"已有解法引用旧版题目，请先核对更新。")
        else:
            n=dict(id=id,kind="solution",title=req.method,status=status,category=lesson["category"],
                data={"pool_item_id":item["id"],"occurrence_id":req.occurrence_id,"item_version":item["version"],
                    "question_hash":digest({"question":item["question"],"answer":item["answer"],"solution":item["solution"]}),
                    "question_snapshot":item["question"],"original_question_snapshot":occurrence.get("original_question",""),
                    "answer_snapshot":occurrence.get("original_answer",""),"solution_snapshot":occurrence.get("original_solution",""),
                    "completeness":item["completeness"],"source_id":sid,"subquestion":req.subquestion,
                    "method":req.method,"steps":req.steps,"stage":req.stage,"origin":origin,
                    "source_locator":{k:occurrence.get(k) for k in ("source_key","page_start","page_end","question_no","source_name","url")},
                    "match_status":"pending","requirements_status":"declared" if req.knowledge_ids else "unknown",
                    "source_snapshot_hash":digest(store._get(c,sid)["data"]),
                    "note":req.reason})
            store._put(c,n,rev)
        evidence={"source_id":sid,"locator":occurrence.get("source_key",""),"reason":req.reason,"origin":origin}
        relations=[(req.lesson_id,id,"practices")]+[(id,k,"requires") for k in req.knowledge_ids]+[(id,r,"routine_candidate") for r in routines]
        for a,b,kind in relations:
            found=c.execute("SELECT 1 FROM cw_edges WHERE source=? AND target=? AND kind=?",(a,b,kind)).fetchone()
            if not found:store._put_edge(c,{"id":uuid.uuid4().hex,"source":a,"target":b,"kind":kind,"status":status,"evidence":evidence},rev)
        return id
    return store.mutate(req.expected_revision,"attach_question",req.reason,apply)


class SourceImport(Change):
    source: dict
    excerpts: list[dict] = Field(default_factory=list,max_items=300)


class KnowledgeCreate(Change):
    title: StrictStr = Field(...,min_length=1,max_length=300)
    body: StrictStr = Field(...,min_length=1,max_length=30000)
    formula: StrictStr = Field("",max_length=10000)
    conditions: StrictStr = Field("",max_length=10000)
    introducing_lesson_id: StrictStr


@router.post("/knowledge",status_code=201)
def create_knowledge(req:KnowledgeCreate,store=Depends(get_store)):
    def apply(c,rev):
        lesson=store._get(c,req.introducing_lesson_id)
        if lesson["kind"]!="lesson" or not lesson["active"]:raise HTTPException(422,"请选择有效引入课时。")
        id="kp:"+uuid.uuid4().hex
        store._put(c,{"id":id,"kind":"knowledge","title":req.title,"book_id":lesson["book_id"],
            "section_id":lesson["section_id"],"category":lesson["category"],"data":{"body":req.body,
                "formula":req.formula,"conditions":req.conditions,"source_id":lesson["data"].get("source_id","source:editorial")}},rev)
        store._put_edge(c,{"id":uuid.uuid4().hex,"source":lesson["id"],"target":id,"kind":"teaches",
            "evidence":{"source_id":lesson["data"].get("source_id","source:editorial"),"reason":req.reason,"origin":"human"}},rev)
        return id
    return store.mutate(req.expected_revision,"create_knowledge",req.reason,apply)


def import_source(store,req):
    source=req.source
    if not isinstance(source.get("title"),str) or not source["title"].strip():raise HTTPException(422,"请填写资料名称。")
    if set(source)-{"id","title","source_type","edition","isbn","url","scope","reading_status","pool_source_id","total_units","read_units","gap"}:
        raise HTTPException(422,"含未知来源字段。")
    if source.get("source_type") not in ("textbook","workbook","question_pool","editorial"):raise HTTPException(422,"来源类型无效。")
    for x in req.excerpts:
        if set(x)-{"text","locator","verification"} or not isinstance(x.get("text"),str) or not x["text"].strip() or not x.get("locator"):
            raise HTTPException(422,"来源片段须包含原文text和具体定位locator。")
        if len(x["text"])>50000:raise HTTPException(422,"单个来源片段过长。")
    def apply(c,rev):
        id=source.get("id") or "source:"+uuid.uuid4().hex
        found=c.execute("SELECT * FROM cw_entities WHERE id=?",(id,)).fetchone()
        if found:
            n=store._node(found)
            if n["kind"]!="source":raise HTTPException(422,"该编号不是来源。")
        else:n={"id":id,"kind":"source","title":source["title"],"data":{}}
        n["title"]=source["title"]
        n["data"].update({k:v for k,v in source.items() if k not in ("id","title")})
        n["data"].setdefault("reading_status","partial" if req.excerpts else "entry_only")
        if n["data"].get("pool_source_id") is not None:
            from backend import question_pool as pool
            source_id=n["data"]["pool_source_id"]
            with pool._connection() as pool_conn:
                valid=type(source_id) is int and pool_conn.execute("SELECT 1 FROM pool_sources WHERE id=?",(source_id,)).fetchone()
            if not valid:raise HTTPException(422,"关联原题池题源编号不存在。")
        n["data"]["excerpts"]=req.excerpts or n["data"].get("excerpts",[])
        n["data"]["source_hash"]=digest({"metadata":source,"excerpts":n["data"]["excerpts"]})
        store._put(c,n,rev);return id
    return store.mutate(req.expected_revision,"import_source",req.reason,apply)


@page_router.get("/curriculum-wiki.html",include_in_schema=False)
def page():
    return FileResponse(ROOT/"frontend/curriculum-wiki.html")


@router.get("/overview")
def overview(store=Depends(get_store)):
    return store.overview()


@router.get("/lessons")
def lessons(query:str="",book:str="",status:str="",routine:str="",source:str="",only_gaps:bool=False,
            page:int=Query(1,ge=1),page_size:int=Query(80,ge=1,le=500),store=Depends(get_store)):
    snap=store.export();links=[e for e in snap["edges"] if e["status"]!="rejected"]
    rows=[n for n in snap["entities"] if n["kind"]=="lesson" and n["active"]]
    if book:rows=[n for n in rows if n["book_id"]==book]
    if status:rows=[n for n in rows if n["status"]==status]
    if routine:rows=[n for n in rows if any(e["source"]==n["id"] and e["target"] in (routine,"routine:"+routine) for e in links)]
    if source:
        byid={n["id"]:n for n in snap["entities"]}
        rows=[n for n in rows if n["data"].get("source_id")==source or any(
            e["source"]==n["id"] and e["kind"]=="practices" and byid[e["target"]]["data"].get("source_id")==source for e in links)]
    if query:
        terms=query.casefold().split()
        lookup={n["id"]:n for n in snap["entities"]}
        def matches(n):
            texts=[dumps(n)]+[dumps(lookup[e["target"]]) for e in links if e["source"]==n["id"]]
            hay=" ".join(texts).casefold();return all(t in hay for t in terms)
        rows=[n for n in rows if matches(n)]
    if only_gaps:rows=[n for n in rows if not any(e["source"]==n["id"] and e["kind"]=="practices" and e["status"]!="rejected" for e in links)]
    rows.sort(key=lambda n:n["position"]);total=len(rows);rows=rows[(page-1)*page_size:page*page_size]
    return {"revision":snap["revision"],"total":total,"items":rows}


@router.get("/entities")
def entities(kind:str="",store=Depends(get_store)):
    if kind and kind not in KINDS:raise HTTPException(422,"记录类型无效。")
    return {"revision":store.revision(),"items":store.entities(kind or None)}


@router.get("/lessons/{id}")
def detail(id:str,store=Depends(get_store)):
    return store.detail(id)


@router.patch("/entities/{id}")
def edit(id:str,req:Edit,store=Depends(get_store)):
    return store.edit(id,req.changes,req.expected_revision,req.reason)


@router.post("/relations")
def relation(req:Relation,store=Depends(get_store)):
    return store.relation(req.relation,req.expected_revision,req.reason)


@router.get("/relations")
def relations(store=Depends(get_store)):
    return {"revision":store.revision(),"items":store.export()["edges"]}


@router.put("/order")
def order(req:Order,store=Depends(get_store)):
    return store.reorder(req.lesson_ids,req.expected_revision,req.reason)


@router.post("/lessons/{id}/split")
def split(id:str,req:Split,store=Depends(get_store)):
    try:return store.split(id,req.parts,req.expected_revision,req.reason)
    except (KeyError,TypeError):raise HTTPException(422,"各分课须包含标题、正文与学习目标。") from None


@router.post("/merge")
def merge(req:Merge,store=Depends(get_store)):
    return store.merge(req.lesson_ids,req.title,req.expected_revision,req.reason)


@router.get("/checks")
def checks(store=Depends(get_store)):
    return store.checks()


@router.post("/questions")
def questions(req:QuestionLink,store=Depends(get_store)):
    return attach_question(store,req)


@router.post("/sources/import")
def sources_import(req:SourceImport,store=Depends(get_store)):
    return import_source(store,req)


@router.get("/sources/{id}/file")
def source_file(id:str,store=Depends(get_store)):
    n=store.entity(id)["entity"]
    filename=n["data"].get("evidence_file","")
    root=(evidence_root()/"evidence").resolve()
    path=(root/filename).resolve()
    if n["kind"]!="source" or not filename or path.parent!=root or not path.is_file() or path.suffix.lower()!=".pdf":
        raise HTTPException(404,"该资料原件尚未保存，可从资料来源链接核对。")
    return FileResponse(path,media_type="application/pdf",content_disposition_type="inline",
                        headers={"Cache-Control":"private, no-store"})


@router.get("/questions/{id}/freshness")
def question_freshness(id:str,store=Depends(get_store)):
    entity=store.entity(id)["entity"]
    if entity["kind"]!="solution":raise HTTPException(422,"记录不是题目解法。")
    return store.solution_freshness(entity)


@router.get("/history")
def history(store=Depends(get_store)):
    return {"revision":store.revision(),"items":store.history()}


@router.get("/history/{revision}")
def history_detail(revision:int,store=Depends(get_store)):
    return store.history_detail(revision)


@router.post("/history/{revision}/restore")
def restore(revision:int,req:Change,store=Depends(get_store)):
    return store.restore(revision,req.expected_revision,req.reason)


@router.get("/export")
def export(format:str="json",store=Depends(get_store)):
    if format=="json":
        return Response(dumps(store.export()),media_type="application/json",
            headers={"Content-Disposition":'attachment; filename="curriculum-wiki.json"'})
    if format!="markdown":raise HTTPException(422,"支持json或markdown导出。")
    # Projection only. Editing this export cannot write back to the database.
    snap=store.export();parts=["# 数学课时库\n\nSQLite只读导出，版本 "+str(snap["revision"])]
    for n in sorted(snap["entities"],key=lambda n:n["position"]):
        if n["kind"] in ("lesson","knowledge") and n["active"]:
            parts.append(f'## {n["title"]}\n\n编号：{n["id"]}\n\n{n["data"].get("body","")}')
            parts.extend(f'- [[{e["target"]}]]（{e["kind"]}）' for e in snap["edges"] if e["source"]==n["id"] and e["status"]!="rejected")
    return Response("\n\n".join(parts),media_type="text/markdown",
        headers={"Content-Disposition":'attachment; filename="curriculum-wiki.md"'})
