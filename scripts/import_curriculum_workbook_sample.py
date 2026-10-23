"""Visually transcribed public official sample, page 9/40 (printed page 1).

The official answer booklet was not read. Answers below are editorial analyses
stored on the wiki solution, never mislabelled as the source's original answer.
"""
from pathlib import Path
import sys,json
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend import question_pool as pool
from backend.curriculum_wiki import get_store,attach_question,QuestionLink,digest,evidence_root

URL="https://book.yunzhan365.com/pqks/jrhh/mobile/index.html"
TITLE="一遍过·数学必修第一册RJA（26版官方40页试读）"
SAMPLES=[
 ("3",r"（多选）若集合 $A=\{2a,a^2-a\}$，则实数 $a$ 的取值可以是（ ）。A. $-3$；B. $0$；C. $3$；D. $5$。",
  "b1:1.1:practice",["kp:b1:1.1:l1"],["SET-004"],"AD",
  ["由集合元素互异性，2a不能等于a²-a。","整理得a(a-3)≠0，因此a≠0且a≠3。","逐项代入，-3与5满足，所以选A、D。"],"先检验元素互异性，再求参数；只需初中因式分解，不需要预学导数。"),
 ("5",r"已知集合 $A=\{-3,1,2\}$，$B=\{1,2,3\}$，若 $x\in A$ 且 $x\notin B$，则 $x=$（ ）。A. $-3$；B. $3$；C. $1$或$2$；D. $-3$或$2$。",
  "b1:1.1:practice",["kp:b1:1.1:l1"],[],"A",
  ["依次检验A中的-3、1、2。","1与2也属于B，均排除；-3属于A而不属于B。","所以x=-3，选A。"],"逐个检验元素归属即可；不必提前引入集合差。现有细套路没有完全对应的有限集合成员检验，暂不强配。"),
 ("8",r"集合 $\{x\in\mathbb N\mid x-2<2\}$ 用列举法可表示为（ ）。A. $\{1,2,3\}$；B. $\{1,2,3,4\}$；C. $\{0,1,2,3,4\}$；D. $\{0,1,2,3\}$。",
  "b1:1.1:l2",["kp:b1:1.1:l1","kp:b1:1.1:l2"],["SET-006","SET-001"],"D",
  ["先解一元一次不等式，得x<4。","自变量限制在自然数集，按本教材约定包含0。","满足条件的元素为0、1、2、3，选D。"],"先看论域再列举，自然数集包含0；不等式仅需初中知识。"),
 ("9",r"若 $A=\{-1,3\}$，则集合 $\{(x,y)\mid x\in A,\ y\in A\}$ 用列举法表示为（ ）。A. $\{-1,3\}$；B. $\{(-1,3)\}$；C. $\{(-1,3),(3,-1)\}$；D. $\{(-1,-1),(-1,3),(3,-1),(3,3)\}$。",
  "b1:1.1:l2",["kp:b1:1.1:l2"],["SET-002","SET-006"],"D",
  ["集合元素是有序数对，不是单个坐标。","分别取x=-1与x=3；对每个x分别取y=-1与y=3。","得到四个有序数对，选D。"],"按有序数对逐项列举，不需要提前学习排列组合公式。"),
 ("10",r"（多选）集合 $\{1,3,5,7,9\}$ 用描述法可表示为（ ）。A. $\{x\mid x\text{是不大于9的非负奇数}\}$；B. $\{x\mid x=2k+1,\ k\le4\text{且}k\in\mathbb N\}$；C. $\{x\mid x\le9,\ x\in\mathbb N^*\}$；D. $\{x\mid0<x\le9,\ x\in\mathbb Z\}$。",
  "b1:1.1:l2",["kp:b1:1.1:l1","kp:b1:1.1:l2"],["SET-006"],"AB",
  ["A列举出不大于9的非负奇数，恰好是目标集合。","B中k为0、1、2、3、4，得到1、3、5、7、9。","C与D都包含2、4等偶数，不能表示原集合，所以选A、B。"],"通过两种表示的元素完全一致判断，不用后续数列公式。"),
 ("11",r"选择适当的方法表示下列集合：（1）大于1且小于70的正整数的倒数组成的集合$A$；（2）小于8的质数组成的集合$B$；（3）函数$y=-2x^2+x$图象上的点组成的集合$C$；（4）平面直角坐标系中第二象限的点组成的集合$D$。",
  "b1:1.1:practice",["kp:b1:1.1:l2"],["SET-006","SET-002"],r"$A=\{1/n\mid n\in\mathbb Z,\ 2\le n\le69\}$；$B=\{2,3,5,7\}$；$C=\{(x,y)\mid x\in\mathbb R,\ y=-2x^2+x\}$；$D=\{(x,y)\mid x<0,\ y>0\}$。",
  ["有限但元素较多的A用描述法，先限制整数n再取倒数。","B用列举法；1不是质数。","C、D的元素是点，写成有序数对并保留函数或象限条件。"],"表示图象上的点不等于研究二次函数性质，初中坐标知识已经足够。"),
]


def main():
    store=get_store()
    records=[]
    for no,question,*_ in SAMPLES:
        records.append({"source_key":"sample9/printed1/Q"+no,"question_no":no,"page_start":1,"page_end":1,
            "question":question,"answer":"","solution":"","question_type":"大题" if no=="11" else "多选题" if no in ("3","10") else "选择题",
            "categories":["集合与逻辑用语"],"completeness":"complete",
            "raw":{"sample_page":9,"printed_page":1,"verification":"visually_transcribed_from_official_sample",
                   "original_url":URL,"answer_status":"not_read","source_note":"原图文字可辨；参考答案册未读取，研究解法不充当原书解析。"}})
    payload={"title":TITLE,"url":URL,"edition":"26版，2025—2026学年","sample_pages":40,
        "actually_viewed_sample_pages":[1,4,5,8,9],"records":records}
    root=evidence_root()/"evidence";root.mkdir(parents=True,exist_ok=True)
    (root/"ybg-rja-b1-visible-transcription.json").write_text(json.dumps(payload,ensure_ascii=False,indent=2))
    source=pool.import_records({"name":TITLE,"kind":"jsonl","url":URL,"revision":digest(payload),
        "license":"出版社官方公开试读；仅私人研究，公开再分发权限未核实","publication_allowed":False},records)
    # Locate the exact immutable source occurrence rather than guessing IDs.
    with pool._connection() as c:
        origins=[dict(r) for r in c.execute("""SELECT o.*,s.name FROM pool_occurrences o JOIN pool_sources s ON s.id=o.source_id
                    WHERE s.name=? ORDER BY o.id""",(TITLE,))]
    if not origins:raise RuntimeError("未能定位试读题目出处。")
    source_id=origins[0]["source_id"]
    old=store.entity("source:ybg")["entity"]
    metadata={"edition":"26版（2025—2026学年）","isbn":None,"publisher":"南京师范大学出版社",
        "url":URL,"pool_source_id":source_id,"reading_status":"partial","read_units":5,"total_units":40,
        "scope":"官方40页试读包，已目视核对封面、若干目录页及印刷第1页（试读第9页）；录入6题。分母不是全书页数。",
        "gap":"其余试读题页、答案册及全书正文尚未逐题核查，ISBN未取得。",
        "excerpts":[{"text":"第一节 集合的概念；知识点1 集合的概念与元素的特性；知识点2 元素与集合的关系；知识点3 集合的表示方法。",
            "locator":"试读第9页，印刷第1页","verification":"visually_checked"}]}
    if old["data"].get("pool_source_id")!=source_id or old["title"]!=TITLE:
        store.edit("source:ybg",{"title":TITLE,"data":metadata},store.revision(),"按出版社官方试读核实版本、实际读取范围及6道原题出处。")
    count=0
    for no,question,lesson,knowledge,routines,answer,steps,note in SAMPLES:
        origin=next(o for o in origins if o["source_key"]=="sample9/printed1/Q"+no)
        method="一遍过·集合概念·第"+no+"题：研究解法"
        snap=store.export()
        existing=next((n for n in snap["entities"] if n["kind"]=="solution" and n["data"].get("occurrence_id")==origin["id"] and n["data"].get("method")==method),None)
        if existing:
            if existing["status"]!="draft" or existing["data"].get("editorial_sample_annotation_version")=="v2":continue
            targets={"routine:"+rid for rid in routines}
            old_edges=[e for e in snap["edges"] if e["source"]==existing["id"] and e["kind"]=="routine_candidate"]
            for edge in old_edges:
                if edge["target"] not in targets and edge["status"]=="draft":
                    store.relation({**edge,"status":"rejected"},store.revision(),"对照完整套路关键步骤，排除仅凭名称相近的旧候选。")
            for target in targets-{e["target"] for e in old_edges if e["status"]!="rejected"}:
                store.relation({"source":existing["id"],"target":target,"kind":"routine_candidate",
                    "evidence":{"source_id":"source:ybg","locator":"印刷第1页第"+no+"题","reason":note,"origin":"editorial_solution_analysis"}},
                    store.revision(),"按题目步骤校正套路候选。")
            store.edit(existing["id"],{"data":{"mapping_note":note,"editorial_sample_annotation_version":"v2"}},store.revision(),"保留无法准确归组的缺口，不强配细套路。")
            continue
        result=attach_question(store,QuestionLink(expected_revision=store.revision(),reason=note,
            lesson_id=lesson,pool_item_id=origin["item_id"],occurrence_id=origin["id"],method=method,
            steps=steps,knowledge_ids=knowledge,routine_ids=routines,source_id="source:ybg"),
            origin="editorial_derived_from_visible_workbook")
        store.edit(result["result"],{"data":{"editorial_answer":answer,"mapping_note":note,
            "reference_answer_status":"not_read","requirements_status":"declared",
            "sample_page":9,"original_question_no":no,"editorial_sample_annotation_version":"v2"}},store.revision(),"保留研究推导答案，与尚未取得的原书答案分开。")
        count+=1
    print("已录入官方试读原题与独立研究解法：",count,"题；未读取内容保持缺口。")


if __name__=="__main__":main()
