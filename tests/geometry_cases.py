"""Offline examples: two retained corpus questions plus explicit construction cases."""
from copy import deepcopy
import math
from backend.geometry import compile_geometry, fingerprint


def answer(category, writing, count=2):
    return {"chunk_results": [{"chunk_id": 1, "category": {"level1": category}, "chunk_type": "大题",
             "steps": [{"step_number": i+1, "title": "辅助构造" if i == 0 else "计算结论",
                        "standard_writing": writing, "step_prompt": "请完成本步构造与计算。",
                        "step_answer": writing, "step_difficulty": {"level": "困难" if i == 0 else "容易", "score": 8 if i == 0 else 2},
                        "step_level1": "建立几何关系"} for i in range(count)]}]}


def point(id, xyz, base=True):
    return {"id": id, "kind": "point", "coords": xyz, "label": id, "base": base}


def steps(visible, groups=None):
    return [{"step_key": "1-1", "scene_id": "main", "full_visible": visible,
             "hint_groups": groups if groups is not None else [{"text": "连接辅助线，建立本步所需的几何关系。", "visible": visible}]},
            {"step_key": "1-2", "scene_id": "main", "full_visible": visible, "hint_groups": []}]


def corpus_ellipse():
    # highmath/Plane_Analytic_Geometry.jsonl, first question (retained locally).
    q = r"设 $F_{1}, F_{2}$ 为椭圆 $C: \frac{x^{2}}{5}+y^{2}=1$ 的两个焦点, 点 $P$ 在 $C$ 上, 若 $\overrightarrow{P F_{1}} \cdot \overrightarrow{P F_{2}}=0$, 则 $\left|P F_{1}\right| \cdot\left|P F_{2}\right|=$ ()"
    a = answer("解析几何", "连接两条焦半径。由焦距4、两焦半径和为2√5以及勾股定理，乘积为2。")
    objs = [point("F1",[-2,0]),point("F2",[2,0]),point("P",["sqrt(15)/2",.5]),
            {"id":"ellipse","kind":"conic","coefficients":[.2,0,1,0,0,-1],"base":True},
            {"id":"PF1","kind":"segment","a":"P","b":"F1"},
            {"id":"PF2","kind":"segment","a":"P","b":"F2"}]
    raw = {"scenes":[{"id":"main","dimension":2,"bounds":[-3,2,3,-2],"objects":objs,
                     "constraints":[{"kind":"on_conic","point":"P","conic":"ellipse","source":q},
                                    {"kind":"perpendicular","a":"P","b":"F1","c":"P","d":"F2","source":q}]}],
           "steps":steps(["PF1","PF2"],[{"text":"先连接PF₁，观察第一条焦半径。","visible":["PF1"]},
                                     {"text":"再连接PF₂，利用题设得到直角三角形。","visible":["PF2"]}])}
    return q,a,raw


def corpus_pyramid():
    # highmath/Solid_Geometry.jsonl, second question (retained locally).
    q = r"在三棱雉 $P-A B C$ 中, $\triangle A B C$ 是边长为 2 的等边三角形, $P A=P B=2, P C=\sqrt{6}$, 则该棱雉的体积为 $(\quad)$"
    writing = "取AB中点E，连接PE、CE。PE⊥AB、CE⊥AB，由PC²=PE²+CE²得到PE⊥CE，分割体积为1。"
    a = answer("立体几何", writing)
    objs = [point("A",[-1,0,0]),point("B",[1,0,0]),point("C",[0,"sqrt(3)",0]),point("P",[0,0,"sqrt(3)"]),
            {"id":"pyramid","kind":"solid","faces":[["A","B","C"],["A","B","P"],["A","C","P"],["B","C","P"]],"base":True},
            {"id":"E","kind":"point","construct":{"kind":"midpoint","a":"A","b":"B"},"label":"E"},
            {"id":"PE","kind":"segment","a":"P","b":"E","dashed":True},
            {"id":"CE","kind":"segment","a":"C","b":"E","dashed":True}]
    conditions = [{"kind":"distance","a":x,"b":y,"value":v,"source":q} for x,y,v in
                  [("A","B",2),("A","C",2),("B","C",2),("P","A",2),("P","B",2),("P","C","sqrt(6)")]]
    conditions.extend([{"kind":"perpendicular","a":"P","b":"E","c":"C","d":"E","source":"PE⊥CE"},
                       {"kind":"on_line","a":"A","b":"B","point":"E","source":"取AB中点E"}])
    raw = {"scenes":[{"id":"main","dimension":3,"objects":objs,"constraints":conditions}],
           "steps":steps(["E","PE","CE"],[{"text":"取AB中点E，连接PE。利用PA=PB，得到PE⊥AB。","visible":["E","PE"]},
                                         {"text":"连接CE，结合等边三角形建立另一个垂直关系。","visible":["CE"]}])}
    return q,a,raw


def construction_case(kind):
    q = "正方体棱长为2，作平行于底面的截面。" if kind=="section" else "立体几何：AC=2，将三角形绕AB折起。" if kind=="fold" else "解析几何：动点P在椭圆x²/4+y²=1上，求轨迹。"
    a=answer("立体几何" if kind in ("section","fold") else "解析几何",q)
    if kind=="fold":
        objs=[point("A",[0,0,0]),point("B",[2,0,0]),point("C",[0,2,0]),
              {"id":"R","kind":"point","construct":{"kind":"rotate","a":"A","b":"B","point":"C","angle":"t"},"label":"C′"},
              {"id":"fold","kind":"polygon","points":["A","B","R"]}]
        scene={"dimension":3,"objects":objs,"parameter":{"name":"t","min":.05,"max":math.pi/2,"value":.05},
               "constraints":[{"kind":"distance","a":"A","b":"R","value":2,"source":"AC=2"}]}
        visible=["R","fold"]
    elif kind=="section":
        objs=[point("A",[0,0,0]),point("B",[2,0,0]),point("C",[2,2,0]),point("D",[0,2,0]),
              point("U",[0,0,2]),point("V",[2,0,2]),point("W",[2,2,2]),point("X",[0,2,2]),
              {"id":"cube","kind":"solid","faces":[["A","B","C","D"],["U","V","W","X"],["A","B","V","U"],["B","C","W","V"],["C","D","X","W"],["D","A","U","X"]],"base":True}]
        for id,xy in [("E",[0,0]),("F",[2,0]),("G",[2,2]),("H",[0,2])]:objs.append(point(id,xy+["t"],False))
        objs.append({"id":"section","kind":"plane","points":["E","F","G","H"]})
        scene={"dimension":3,"objects":objs,"parameter":{"name":"t","min":.1,"max":1.9,"value":1},
               "constraints":[{"kind":"distance","a":"A","b":"B","value":2,"source":"棱长为2"},
                              {"kind":"parallel","a":"E","b":"F","c":"A","d":"B","source":"平行于底面"}]}
        visible=["E","F","G","H","section"]
    else:
        objs=[point("P",["2*cos(t)","sin(t)"]),
              {"id":"ellipse","kind":"conic","coefficients":[.25,0,1,0,0,-1],"base":True},
              {"id":"locus","kind":"curve","samples":[[2*math.cos(i*math.pi/30),math.sin(i*math.pi/30)] for i in range(61)]}]
        scene={"dimension":2,"objects":objs,"parameter":{"name":"t","min":0,"max":math.tau,"value":0},
               "constraints":[{"kind":"on_conic","point":"P","conic":"ellipse","source":"动点P在椭圆x²/4+y²=1上"},
                              {"kind":"curve_on_conic","curve":"locus","conic":"ellipse","source":"求轨迹"}]}
        visible=["locus"]
    scene["id"]="main"
    return q,a,{"scenes":[scene],"steps":steps(visible)}


def prepared(case=corpus_pyramid):
    q,a,raw=case();a["geometry"]=compile_geometry(raw,q,a);a["geometry"]["source_hash"]=fingerprint(q,a)
    return q,deepcopy(a)
