"""Demonstrate solution-specific sequencing with inspected, real pool problems.

IDs are local pool references and guarded by source-text fragments. All changes
remain drafts for the owner's review. No paid model calls or formal-bank writes.
"""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.curriculum_wiki import get_store,attach_question,QuestionLink

CASES=[
 (17563,"B \\subseteq A",["kp:b1:1.1:l1","kp:b1:1.2:l1"],
  ["先解方程确定B={0,1}。","由包含关系得A必须含1，求出a的候选值。","代回A排除重复元素，得到a=-1。"],
  "同时用到集合互异性和子集关系，不应在尚未学习包含关系时作为普通巩固题。"),
 (17226,"(x-1)",["kp:b1:1.1:l2","kp:b1:1.3:l1","kp:s1:2.3:l2","kp:s1:2.5:l1"],
  ["把A、B分别解释为直线与圆上的点集。","用点到直线距离与半径比较判断有两个交点。","交集元素是两个有序数对，因此个数为2。"],
  "原解析采用直线与圆位置关系，依赖选必一知识；早期可以另外给出代入消元解法。"),
 (15104,"16y=8",["kp:s1:2.2:l2"],
  ["由无穷解解释为两条直线重合。","比较x、y与常数项的比例，联立得到m=4。"],
  "本记录按原解析的直线重合方法标注；它不能仅因套路属于集合逻辑就算作集合课基础题。"),
 (17403,"x^{y}",["kp:b1:1.1:l1","kp:b1:1.1:l2"],
  ["分别枚举x=1与x=2时的所有y值。","得到1、4、16，并去掉重复的1。","按元素互异性计数，结果为3。"],
  "只需要集合表示、互异性和初中整数指数运算；不要求先学指数函数。"),
 (15735,"4b",["kp:b1:2.1:l1","kp:b1:2.2:l1","kp:b1:2.2:l2"],
  ["利用(a-2b)²≥0得到a²+4b²≥4ab。","代入约束得到ab≤1/4。","令a=2b并与原约束联立，确认等号可实现。"],
  "平方非负给出上界后还要检验等号点；不能因a、b可能为负就直接套正数版基本不等式。"),
 (16243,"f(x+1)",["kp:b1:3.1:l2","kp:b1:3.2:l3"],
  ["定义g(x)=f(x+1)+1并使用g(-x)=-g(x)。","整理得f(1-x)+f(1+x)=-2。","把七项关于x=1配对，并用f(1)=-1求和。"],
  "复合对应、奇函数定义和对称配对足够，不需要导数。"),
 (19501,"a^{2}<b^{2}",["kp:b1:1.4:l2","kp:b1:3.2:l1","kp:b1:3.2:l3"],
  ["由f(-x)=f(x)把自变量转为绝对值。","在非负半轴利用严格递减建立函数值与绝对值的反向关系。","由|a|<|b|等价于a²<b²，判断为充要条件。"],
  "该原解析只用奇偶性、单调性和充要条件，应在函数性质课可用；导数不是必需前置。"),
 (16639,"x \\ln x",["kp:b1:4.2:l1","kp:s2:5.2:l2","kp:s2:5.2:l3","kp:s2:5.3:l1","kp:s2:5.3:l3"],
  ["在x>1使用分段函数对应分支，作差φ(x)=xe^(x-1)-2x+1。","求导φ'(x)=(x+1)e^(x-1)-2；由x+1>2且e^(x-1)>1得φ'(x)>0。","由φ(1)=0与严格递增得到φ(x)>0。"],
  "此解法实际需要导数运算及导数研究单调性。分段函数在其他区间的表达式不参与当前证明。"),
]


def main():
    store=get_store();snapshot=store.export();count=0
    for pool_id,guard,knowledge,steps,note in CASES:
        sols=[n for n in snapshot["entities"] if n["kind"]=="solution" and n["data"]["pool_item_id"]==pool_id]
        for sol in sols:
            if guard not in sol["data"]["question_snapshot"] or sol["status"]!="draft" or sol["data"].get("editorial_sequence_checked"):continue
            for target in knowledge:
                store.relation({"source":sol["id"],"target":target,"kind":"requires","status":"draft",
                    "evidence":{"source_id":sol["data"]["source_id"],"locator":sol["data"]["source_locator"]["source_key"],
                                "reason":note,"origin":"editorial_solution_analysis"}},
                    store.revision(),"按已读取原解析逐步分析前置知识")
            store.edit(sol["id"],{"data":{"steps":steps,"requirements_status":"declared",
                "editorial_sequence_checked":True,"mapping_note":note}},store.revision(),note)
            count+=1
    # A real problem, two methods, two earliest-use stages.
    sol=next((n for n in snapshot["entities"] if n["kind"]=="solution" and n["data"]["pool_item_id"]==17226),None)
    if sol and not any(n["kind"]=="solution" and n["title"]=="点集交集：代入消元（早期解法）" for n in snapshot["entities"]):
        d=sol["data"]
        attach_question(store,QuestionLink(expected_revision=store.revision(),reason="同一原题的原创代数解法：不使用直线与圆的几何性质，可在集合运算后学习。",
            lesson_id="b1:1.3:practice",pool_item_id=17226,occurrence_id=d["occurrence_id"],
            method="点集交集：代入消元（早期解法）",knowledge_ids=["kp:b1:1.1:l2","kp:b1:1.3:l1"],
            routine_ids=["SET-002"],steps=["由x+y=2得y=2-x。","代入另一条件，得到2x²-6x+4=0，即(x-1)(x-2)=0。",
              "回代得到点(1,1)、(2,0)，两个点都满足原条件，所以交集含2个元素。"]),
            origin="editorial_derived_solution")
    print("已补充原解析逐步前置分析：",count,"项；仍保留教师待审。")


if __name__=="__main__":main()
