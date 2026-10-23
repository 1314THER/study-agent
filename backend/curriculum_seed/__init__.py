"""Versioned, original curriculum seed; source documents stay private."""
from hashlib import sha256
import json
from pathlib import Path
from .content import BOOKS, CHAPTERS, ROWS, ACTIVITIES, REVIEWS

VERSION = "rja2019-20261024-v1"

def build_seed(catalog):
    nodes, edges = [], []
    def node(id, kind, title, *, book="", section="", category="", position=0, **data):
        value = dict(id=id, kind=kind, title=title, book_id=book, section_id=section,
                     category=category, position=position, status="draft", active=True, data=data)
        nodes.append(value); return value
    def edge(source, target, kind, reason, source_id="source:editorial"):
        key = sha256(f"{source}|{kind}|{target}".encode()).hexdigest()[:24]
        edges.append(dict(id=key, source=source, target=target, kind=kind, status="draft",
                          evidence=dict(source_id=source_id, locator="章节与教学目标", reason=reason,
                                        origin="seed_editorial", verification="needs_review")))
    node("source:editorial","source","课时编排与教学说明（系统建议）",
         source_type="editorial", reading_status="authored", edition=VERSION, isbn=None,
         url="", scope="原创教学摘要与建议课时；未经过教师逐课审核",
         gap="建议拆分不代表教材规定课时，需教师校核。", read_units=0, total_units=None)
    sources = [
        ("jcb","教材帮","同步讲解","https://www.tesoon.com/customize/ebook"),
        ("ybg","一遍过","同步训练","https://www.tesoon.com/customize/ebook"),
        ("jtjx","解题觉醒","方法专题","https://www.tesoon.com/articles/detail?id=180886"),
        ("53","五年高考三年模拟","高考复习","https://mobile.quyixian.com/ProductManual/"),
    ]
    for id,title,role,url in sources:
        node("source:"+id,"source",title,source_type="workbook",role=role,url=url,
             edition=None,isbn=None,applicable_textbook="人教A版2019；具体版本待核",
             reading_status="entry_only",read_units=0,total_units=None,
             scope="仅取得官方入口或系列介绍，未计为逐题读取",
             gap="具体册次、版次、ISBN、目录及题目页码需从原书或试读核实。")
    for number,(bid,title) in enumerate(BOOKS):
        node(bid,"book",title,position=number+1,edition="人教A版2019教材体系",
             course="必修" if bid.startswith("b") else "选择性必修",source_id="source:"+bid)
        node("source:"+bid,"source","人教A版数学 "+title,source_type="textbook",
             reading_status="directory_pending",edition="2019教材体系；文件版次待版权页核查",
             url="https://github.com/litongjava/china_high_school_math_people_teach_a_version_pdf",
             isbn=None,read_units=0,total_units=None,scope="教材目录定位，正文摘要由系统原创编写",
             gap="PDF为公开镜像，出版社原作；需核查目录转录和具体印次。")
        for ch,ct in CHAPTERS[bid]:
            node(f"{bid}:ch:{ch}","chapter",ct,book=bid,position=int(ch),code=ch)
    sections = {}
    for line in ROWS.strip().splitlines():
        bid,code,title,category,focus,tail = line.split("|",5)
        formula,pitfall,foundation,deps = tail.rsplit("|",3)
        sid=f"{bid}:{code}"
        sections[sid]=dict(book=bid,code=code,title=title,category=category,
                           focuses=[x.split("=",1) for x in focus.split("~")],
                           formula=formula,pitfall=pitfall,foundation=foundation,
                           deps=deps.split(",") if deps else [])
    last_lesson, knowledge_by_section, position = {}, {}, 0
    for sid,s in sections.items():
        node(sid,"section",s["title"],book=s["book"],category=s["category"],
             section=sid,code=s["code"],chapter_id=f'{s["book"]}:ch:{s["code"].split(".")[0]}',
             source_id="source:"+s["book"],locator="§"+s["code"],
             directory_status="needs_review", coverage_reason="按本节教学目标拆分新授与习题课")
        previous=None; kps=[]
        for j,(title,focus) in enumerate(s["focuses"],1):
            position+=10; lid=f"{sid}:l{j}"; kid="kp:"+lid; kps.append(kid)
            node(kid,"knowledge",title,book=s["book"],section=sid,category=s["category"],
                 body=focus,formula=s["formula"],conditions=s["pitfall"],
                 source_id="source:"+s["book"],locator="§"+s["code"])
            node(lid,"lesson",title,book=s["book"],section=sid,category=s["category"],position=position,
                 duration_minutes=45,lesson_type="新授",route="textbook",allocation="system_proposed",
                 objectives=[focus],body=focus+"\n\n概念、公式与条件："+s["formula"]+"\n\n辨析："+s["pitfall"],
                 formula=s["formula"],pitfalls=[s["pitfall"]],foundations=[s["foundation"]],
                 source_id="source:"+s["book"],locator="§"+s["code"],
                 practice_stage="讲授例题 → 基础巩固 → 条件变化",new_knowledge=[kid],
                 gap="尚未逐题核实本课教辅题目。",editorial_note="约45分钟的系统建议拆分，等待教师审核。",
                 optional="选学" in s["title"])
            edge(lid,kid,"teaches","本课首次引入此教学目标。")
            if previous:
                edge(lid,previous,"prerequisite","本节前一课的定义或方法是当前应用的前提。")
                edge(lid,"kp:"+previous,"requires","复用本节前一课知识。")
            for dep in s["deps"]:
                if dep in last_lesson:
                    edge(lid,last_lesson[dep],"prerequisite","所需前置章节："+sections[dep]["title"])
                    for pk in knowledge_by_section[dep]:
                        edge(lid,pk,"requires","本课内容需要："+sections[dep]["title"])
            previous=lid
        last_lesson[sid]=previous;knowledge_by_section[sid]=kps
        position+=10;lid=sid+":practice"
        node(lid,"lesson",s["title"]+"：习题与变式",book=s["book"],section=sid,category=s["category"],position=position,
             duration_minutes=45,lesson_type="习题",route="textbook",allocation="system_proposed",
             objectives=["运用"+s["title"]+"解决基础、变式与条件辨析问题。"],
             body="先复述："+s["focuses"][0][1]+"\n\n练习顺序：概念辨析、基本运算、条件变化、反例与综合。每道题先列适用条件再选方法；本课方法重点："+s["focuses"][-1][1],
             formula=s["formula"],pitfalls=[s["pitfall"]],foundations=[s["foundation"]],
             source_id="source:"+s["book"],locator="§"+s["code"]+"练习、习题（题号待逐题核实）",
             practice_stage="基础 → 巩固 → 变式；跨章题须检查前置",new_knowledge=[],
             gap="题量与题号待从选定版本原书核查，当前不虚构教辅出处。",optional="选学" in s["title"])
        edge(lid,previous,"prerequisite","完成本节新授后进行练习。")
        for kid in kps:edge(lid,kid,"requires","本节练习复用所学知识。")
    # Place activities and chapter reviews inside each chapter, before the next.
    for bid,_ in BOOKS:
        for ch,ct in CHAPTERS[bid]:
            members=[n for n in nodes if n["kind"]=="lesson" and n["book_id"]==bid and n["section_id"].split(":")[-1].split(".")[0]==ch]
            if not members:continue
            end=max(n["position"] for n in members);last=max(members,key=lambda x:x["position"])
            kids=[n["id"] for n in nodes if n["kind"]=="knowledge" and n["book_id"]==bid and n["section_id"].split(":")[-1].split(".")[0]==ch]
            extras=[(t,body,"探究") for b,c,t,body in ACTIVITIES if b==bid and c==ch]
            extras += [(ct+"：章末知识整理","按定义、公式条件、典型方法和反例梳理本章。重点内容："+last["data"]["body"],"复习"),
                       (ct+"：章末综合与订正","用本章知识解释不同设问下的方法选择，整理错因并检查解法是否依赖后续知识。练习先基础后综合，逐题核对原题条件。","复习")]
            for j,(title,body,typ) in enumerate(extras,1):
                lid=f"{bid}:ch:{ch}:extra{j}"
                node(lid,"lesson",title,book=bid,section=f"{bid}:ch:{ch}",category=last["category"],position=end+j,
                     duration_minutes=45,lesson_type=typ,route="textbook",allocation="system_proposed",
                     objectives=[body],body=body,foundations=["本章各节"],pitfalls=["不得把数值试验当作一般性证明；综合题需列出全部前置条件。"],
                     source_id="source:"+bid,locator="本章探究、阅读、小结与复习题",new_knowledge=[],
                     gap="章末具体题号及活动印刷标题以目录核查记录为准。")
                edge(lid,last["id"],"prerequisite","本章新授知识是整理、探究和综合的基础。")
                for kid in kids:edge(lid,kid,"requires","章末复习调用本章知识。")
    for i,(title,category,deps,body) in enumerate(REVIEWS,1):
        for phase,label in enumerate(("专题梳理","综合应用与订正"),1):
            lid=f"review:{i:02}:{phase}"
            node(lid,"lesson",title+"："+label,book="review",category=category,position=10000+i*10+phase,
                 duration_minutes=45,lesson_type="专题复习" if i<=13 else "跨章综合",route="review",
                 allocation="system_proposed",objectives=[body],body=body+"\n\n先还原定义和条件，再对照典型方法；最后处理跨章变化并解释每一步依据。",
                 source_id="source:editorial",locator="高三复习建议路线",new_knowledge=[],
                 pitfalls=["综合路线不改变知识首次学习位置；不得将后学解法提前包装为基础解法。"],
                 foundations=["已完成所列前置课时"],gap="复习题优先引用真实高考或已核查教辅，待逐题补充。")
            for dep in deps:
                edge(lid,last_lesson[dep],"prerequisite","复习前需掌握："+sections[dep]["title"])
                for kid in knowledge_by_section[dep]:edge(lid,kid,"requires","复用已有知识，不另建同义知识实体。")
    # References are advisory curriculum alignments, not question classifications.
    lesson_nodes=[n for n in nodes if n["kind"]=="lesson" and n["data"].get("route")=="textbook"]
    for routine in catalog["routines"]:
        rid="routine:"+routine["id"]
        node(rid,"routine",routine["name"],category=routine["category"],
             namespace="routine_catalog",external_id=routine["id"],catalog_version=catalog["version"],
             signals=routine["signals"],key_steps=routine["key_steps"],exclusions=routine["exclusions"],
             retrieval_terms=routine["retrieval_terms"],formal_pattern_id=None)
        scored=[]
        for lesson in lesson_nodes:
            if lesson["category"]!=routine["category"]:continue
            hay=lesson["title"]+" "+lesson["data"]["body"]
            words=[w for w in routine["retrieval_terms"] if len(w)>1 and w in hay]
            score=sum(len(w) for w in words)
            if score:scored.append((score,lesson,words))
        for _,lesson,words in sorted(scored,key=lambda x:(-x[0],x[1]["position"]))[:2]:
            edge(lesson["id"],rid,"routine_candidate","目录词与课时内容相符："+", ".join(words)+"；仅为课程关联候选，需对照关键步骤审核。")
    for n in nodes:
        if n["kind"]=="lesson" and n["section_id"] in sections:
            edge(n["section_id"],n["id"],"covers","本节内容安排到该课时；课时拆分等待教师审核。","source:"+n["book_id"])
    from .directory import apply_directory
    apply_directory(nodes,edges,node,edge)
    return nodes,edges
