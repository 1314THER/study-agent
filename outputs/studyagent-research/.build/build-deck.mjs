import fs from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {FileBlob, PresentationFile} from '@oai/artifact-tool';

const ROOT='/Users/sqz/Desktop/study-agent';
process.env.RUNTIME_NODE_MODULES='/Users/sqz/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
const BUILD=path.join(ROOT,'outputs/studyagent-research/.build');
const SOURCE='/Users/sqz/Desktop/教育出题_20261022_v2.pptx';
const SKILL='/Users/sqz/.codex/plugins/cache/openai-primary-runtime/presentations/26.1015.12040/skills/presentations';
const FINAL=path.join(ROOT,'outputs/studyagent-research/deliverables/StudyAgent_项目亮点与相关研究_20261024.pptx');
const p=await PresentationFile.importPptx(await FileBlob.load(SOURCE));
const sourceSlides=[...p.slides.items];
const deck=[];
const C={ink:'#122D4C',body:'#263D50',gray:'#627380',blue:'#185E9B',teal:'#137A78',purple:'#65539A'};
const CN='Noto Sans CJK SC';
const BODY='Arial Unicode MS';
const urls={
 stepwise:'https://arxiv.org/abs/2610.16344',
 verify:'https://aclanthology.org/2024.emnlp-main.478/',
 longtutor:'https://aclanthology.org/2026.acl-long.1371/',
 mathcog:'https://arxiv.org/abs/2504.00843v2',
 mathtutorbench:'https://aclanthology.org/2025.emnlp-main.11/',
 copilot:'https://arxiv.org/pdf/2410.03017v3',
};
async function clone(index){
 const s=sourceSlides[index-1].duplicate();deck.push(s);
 return {s,l:JSON.parse(await (await s.export({format:'layout'})).text())};
}
function set(o,old,value,extra={}){
 const e=o.l.elements.find(e=>e.text===old);
 if(!e)throw Error('Missing template text: '+old);
 const x=p.resolve(e.id);x.text=value;x.text.style={...e.style,autoFit:'none',insets:0,...extra};
 return x;
}
function note(o,text){o.s.speakerNotes.text=text;}
function text(o,value,x,y,w,h,size=28,color=C.body,bold=false,font=CN){
 const s=o.s.shapes.add({geometry:'textbox',position:{left:x,top:y,width:w,height:h},fill:'none',line:{fill:'none',width:0},text:{text:value,style:{fontSize:size,typeface:font,color,bold,autoFit:'none',insets:0,wrap:'square'}}});
 return s;
}
function link(s,value,url){s.text.get(value).link={uri:url,isExternal:true};}
function bodyClear(o){
 p.delete(o.l.elements.filter(e=>e.text && e.position.top>=280 && e.position.top<820).map(e=>e.id));
}
async function figure(o,file,alt,frame){
 const e=o.l.elements.find(e=>e.kind==='image');
 const im=p.resolve(e.id);im.replace({blob:new Uint8Array(await fs.readFile(path.join(BUILD,'assets',file+'.png'))),contentType:'image/png',alt,fit:'contain'});
 im.crop={left:0,top:0,right:0,bottom:0};im.fit='contain';
 im.frame=frame??e.position;
}

// 01: Reuse the source's two-column introduction and four bottom labels.
{
 const o=await clone(1);
 const repl={
  '教育出题：把教学要求变成题目':'StudyAgent：高中数学过程诊断与训练',
  'Educational Question Generation（EQG）':'StudyAgent · Project Highlights and Related Research',
  '输入教学要求，生成题目、答案和解析。':'根据作答证据诊断，围绕数学方法组织训练。',
  '老师给出的要求':'系统处理的学习证据',
  '七年级，已学一元一次方程\n出一道基础应用题\n只使用已学知识':'题目与学生作答\n步骤批改与错误证据\n知识点、方法与历史记录',
  '出题结果示例':'系统连接的学习环节',
  '买 6 本同价笔记本，用 5 元优惠券后\n支付 31 元。每本笔记本多少钱？':'识别方法与出错环节\n安排母题、变式与间隔复测',
  '设每本笔记本的价格为 x 元':'研究目标：无 AI 条件下的独立迁移',
  '6x − 5 = 31':'诊断与训练',
  '每本 6 元':'复测回证',
  '能解':'过程诊断','条件充分':'定位错误步骤',
  '解对':'方法表示','答案与过程正确':'记录适用边界',
  '对目标':'针对训练','考查指定知识':'围绕错误设计变式',
  '适合学生':'课程适配','难度与已学范围适切':'核对解法前置知识',
  '例题为讲解自拟。任务定义参考 EQGEVAL、EQGBench 和 EDUMATH。':'依据当前工作区功能整理。工程实现与学习效果验证分别陈述。',
 };
 for(const [a,b]of Object.entries(repl))set(o,a,b);
 note(o,`项目依据：当前工作区 README.md；backend/routine_matching.py；backend/student_analysis.py；backend/generate.py；backend/patterns.py；backend/curriculum_wiki.py。\n截至2026-10-24，工程实现提供过程诊断、方法表示、变式和复测记录等基础。本页的独立迁移是研究目标，尚未取得学生学习效果的对照实验结论。\n版式参考：${SOURCE} 第1页。`);
}

// 02: Keep the source two-column structure and edit its existing text groups.
{
 const o=await clone(3);bodyClear(o);
 set(o,'这些 Benchmark 分别评什么','StudyAgent 的项目亮点');
 set(o,'先区分出题质量和教育内容的适配能力','围绕方法选择、作答证据和后续训练组织学习流程');
 set(o,'03','02');
 set(o,'生成的题目好不好？','方法与诊断');set(o,'教育内容适不适合？','训练与课程');
 set(o,'点击名称查看原论文。EduMath 与 EDUMATH 是两个不同项目。','基础目录为参考内容，仍需教师审核。诊断准确率与学习增益尚待实验验证。');
 const groups=[
  [60,295,'方法边界','记录触发条件与关键步骤\n区分排除条件和易混淆方法','基础参考目录 1,019 项，内容待审核',C.purple],
  [60,565,'跨次证据','保留支持证据与反证\n给出下一步验证任务','首次独立作答与重复练习分开记录',C.purple],
  [862,295,'训练与复测','围绕错误步骤生成变式\n衔接母题训练与复测记录','1 / 7 / 30 天为当前产品规则',C.teal],
  [862,565,'解法前置','同一道题分别记录不同解法\n检查所需知识何时引入','未核实完整前置时保留未知',C.teal],
 ];
 for(const [x,y,a,b,c,color]of groups){text(o,a,x,y,680,46,33,color,true);text(o,b,x,y+64,680,104,30,C.ink);text(o,c,x,y+185,680,34,22,C.gray);}
 note(o,`本地代码依据：backend/routine_catalog.json，版本2026-10-24.v2，实际读取1,019项，均有exclusions与confusable_ids字段。字段存在不等于内容已验证。\n方法匹配：backend/routine_matching.py。\n独立作答与跨次证据：backend/student_analysis.py 的 _first_independent_questions 与 build_report。\n仿题：backend/generate.py；复测规则：backend/patterns.py 的 _complete_pattern_loop。\n解法前置：backend/curriculum_wiki.py 的 checks；docs/curriculum-wiki.md。\n参考目录与正式学习套路编号属于不同命名空间，不代表1,019项均已接入正式训练。`);
}

// 03: Research map. Exact paper names link to their original sources.
{
 const o=await clone(3);bodyClear(o);
 set(o,'这些 Benchmark 分别评什么','数学诊断与辅导的相关研究');
 set(o,'先区分出题质量和教育内容的适配能力','六项代表工作，覆盖过程诊断、长期教学、能力评测与真人辅导');
 set(o,'生成的题目好不好？','过程诊断与长期教学');set(o,'教育内容适不适合？','教学评测与真人辅导');
 set(o,'点击名称查看原论文。EduMath 与 EDUMATH 是两个不同项目。','点击研究名称查看原文。会议论文与预印本状态按本次调研时可核实版本标注。');
 const data=[
  [60,295,'STEPwise','KAIST · Yoonsu Kim、Juho Kim 等','阶段诊断、子问与量规 · 2026 预印本','stepwise',C.purple],
  [60,466,'Verify-then-Generate','ETH Zurich / TU Darmstadt · Daheim 等','作答验证后的反馈生成 · EMNLP 2024','verify',C.purple],
  [60,637,'LongTutor','中国科学技术大学 · Ning Li、黄振亚等','长期取证、诊断与教学 · ACL 2026','longtutor',C.purple],
  [862,295,'MathCog','KAIST / 密歇根大学等 · Yoonsu Kim 等','手写作答与证据强弱 · 2026 修订预印本','mathcog',C.teal],
  [862,466,'MathTutorBench','ETH Zurich / TU Darmstadt · Macina 等','开放式教学能力评测 · EMNLP 2025','mathtutorbench',C.teal],
  [862,637,'Tutor CoPilot','Stanford · Rose Wang、Dora Demszky 等','实时辅助教师 · 2026.10 v3 预印本','copilot',C.teal],
 ];
 for(const [x,y,a,b,c,key,color]of data){const sh=text(o,a,x,y,680,43,31,color,true);link(sh,a,urls[key]);text(o,b,x,y+49,680,36,23,C.ink);text(o,c,x,y+94,680,35,22,C.gray);}
 note(o,'本页为代表工作地图，不是穷尽性综述，也不按论文数统计独立团队数。\n'+Object.entries(urls).map(([k,v])=>k+': '+v).join('\n'));
}

const sourceFull='EDUMATH: Generating Standards-aligned Educational Math Word Problems';
const fullQuestion='生成题目能否同时符合课程标准和学生兴趣？';
const fullContribution='教师标注四项质量要求，构建 STEM 数据。\n结合模型微调与输出过滤，改善标准对齐。';
const fullEvidence='生成题与人工题表现接近，\n学生更偏好个性化生成题。\n（3–5 年级课堂研究）';
const fullCaption='原文图 1｜课程标准与学生兴趣共同约束生成';
const fullFooter='Bryan R. Christ et al. ACL 2026. DOI: 10.18653/v1/2026.acl-long.1973';
const sideTitle='From Objectives to Questions: A Planning-based Framework for Educational Mathematical Question Generation';
const sideQuestion='怎样让生成题目\n满足多维教学目标？';
const sideContribution='构建多维目标数据集。\nMCTS 搜索结合评审与反思。\n分评可解性与目标满足。';
const sideEvidence='DeepSeek-V3，EduMath-CQ\n目标通过率 43.11%\n指标来自模型评审';
const sideCaption='原文图 2｜EQPR 总体框架';
const sideFooter='Cheng Cheng et al. ACL 2025. DOI: 10.18653/v1/2025.acl-long.628';

async function side(d){
 const o=await clone(5);
 set(o,sideTitle,d.title,{fontSize:d.titleSize??32});
 set(o,sideQuestion,d.question,{fontSize:30});
 set(o,sideContribution,d.contribution,{fontSize:28});
 set(o,sideEvidence,d.evidence,{fontSize:d.evidenceSize??26});
 set(o,sideCaption,d.caption);
 const footer=set(o,sideFooter,d.footer);link(footer,d.footer,urls[d.key]);
 set(o,'05',String(deck.length).padStart(2,'0'));
 await figure(o,d.figure,d.caption,d.frame);
 if(d.extra)text(o,d.extra,505,720,1020,80,25,C.body,false,BODY);
 note(o,d.notes+'\n原文链接：'+urls[d.key]+'\n图像依据：'+d.caption+'。从原文PDF裁切，未重绘数据。\n版式参考：原参考PPT第5页。');
 return o;
}

// 04: STEPwise overall research process.
{
 const o=await clone(6);
 set(o,sourceFull,'STEPwise: Supporting Teachers in Diagnosing Students’ Mathematical Problem-Solving Skills',{fontSize:28});
 set(o,fullQuestion,'如何为数学应用题生成可用于过程诊断的子问与量规？',{fontSize:32});
 set(o,fullContribution,'六名专家共创诊断框架，生成子问与评分量规。\n教师审核后部署，自动评分汇总过程报告。',{fontSize:28});
 set(o,fullEvidence,'5 名教师、64 名学生。\n一个月课堂研究。\n90 题、720 个子问。',{fontSize:25});
 set(o,fullCaption,'原文图 1：从教师需求研究到框架、系统与课堂应用');
 const f=set(o,fullFooter,'Yoonsu Kim et al. KAIST 等. arXiv:2610.16344v1, 2026.10（预印本）');link(f,'Yoonsu Kim et al. KAIST 等. arXiv:2610.16344v1, 2026.10（预印本）',urls.stepwise);
 set(o,'06','04');await figure(o,'stepwise-overview','STEPwise 原文图1研究流程',{left:75,top:300,width:1450,height:340});
 note(o,`完整题名：STEPwise: Supporting Teachers in Diagnosing Students’ Mathematical Problem-Solving Skills through LLM-Generated Questions and Rubrics。Yoonsu Kim, Hayeon Doh, Eunhye Kim, Jinho Son, Juho Kim。arXiv:2610.16344v1，2026-10-12，预印本；PDF中模板会议占位信息不作为已录用会议证据。\n研究先访谈教师，再与6名数学教育专家共创STEP框架；8名教师评审生成材料；在5名教师与64名3–9年级学生中进行一个月课堂研究，累计生成90题、720个子问及量规。\n系统支持教师审核与编辑、学生纸笔作答上传识别、LLM评分及诊断报告。课堂研究主要支持可用性和过程可见性，未证明随机对照下的提分效果。\n图片：PDF第1页图1。\n来源：${urls.stepwise}`);
}

// 05: STEPwise diagnostic framework detail.
await side({key:'stepwise',title:'STEPwise: Four Stages and Eight Diagnostic Sub-skills',
 question:'如何把解题障碍拆成\n可观察的诊断子技能？',
 contribution:'四阶段、八项子技能。\n子问对应可观察的推理证据。\n三级量规刻画表现差异。',
 evidence:'8 名教师评审 36 道题。\n构念效度标准：91.32%。\n数学准确性标准：90.97%。',evidenceSize:25,
 caption:'原文图 2：四阶段、八项子技能、诊断子问与主要错误类型',
 footer:'Yoonsu Kim et al. STEPwise. arXiv:2610.16344v1, 2026.10（预印本）',
 figure:'stepwise-framework',frame:{left:505,top:230,width:1020,height:460},
 extra:'理解：信息识别与目标确认　　组织：条件整理与关联\n表达：知识调用与数学建模　　计算：执行与结果解释',
 notes:'STEP四阶段：Problem Comprehension、Information Structuring、Mathematical Expression、Mathematical Computation。八子技能：识别关键信息、识别问题目标、组织条件、连接条件、应用数学知识、构造数学表达/模型、执行计算、解释与组织结果。\n生成流程先求解并生成子问，经阶段目标、情境、提示与答案有效性检查后，模拟高/中/低表现，分析错误模式并生成三级量规。\n专家评审：36道3–6年级题目，8名教师参与，其中6名主要评审、2名仲裁。91.32%与90.97%为子技能层材料满足相应标准的Yes比例，不是系统诊断学生能力的准确率。年级适切性80.21%、情境对齐72.22%，提示仍需教师审核。\n原图见PDF第6页图2，评审结果见第8页。'});

// 06: Verify-then-Generate.
await side({key:'verify',title:'Stepwise Verification and Remediation of Student Reasoning Errors with LLM Tutors',titleSize:28,
 question:'怎样找准学生的错误，\n再给出针对性反馈？',
 contribution:'作答验证与反馈生成分开。\n输出错步、描述及步骤对齐。\n依据验证结果生成反馈。',
 evidence:'1,002 条逐步推理链。\n教师标注首错位置。\n自动评价与人工评价。',
 caption:'原文图 1：验证学生推理后，再生成面向错误的辅导回复',
 footer:'Nico Daheim et al. EMNLP 2024. DOI: 10.18653/v1/2024.emnlp-main.478',
 figure:'verify-framework',frame:{left:505,top:250,width:1020,height:400},
 extra:'验证结果：正确性、错误描述与步骤对齐\n反馈生成：依据错误证据给出针对性引导',
 notes:'完整题名：Stepwise Verification and Remediation of Student Reasoning Errors with Large Language Model Tutors。Nico Daheim, Jakub Macina, Manu Kapur, Iryna Gurevych, Mrinmaya Sachan。ETH Zurich与TU Darmstadt等，EMNLP 2024，8386–8411页。\n以MathDial等数学辅导场景为基础，为1,002条逐步推理链收集教师标注的首错位置。比较分类式验证、错误描述与学生/参考步骤对齐等方式，将验证输出提供给回复生成模型。自动与人工评估显示，反馈更有针对性、更正确，幻觉减少。\n本研究验证的是学生作答，并不等同于只检查模型参考解答的正确性。该研究的离线反馈质量结果不直接等同于学生学习增益。原图：PDF第2页图1。'});

// 07: LongTutor.
await side({key:'longtutor',title:'LongTutor: Benchmarking Large Language Models for Long-term Personalized Tutoring',titleSize:29,
 question:'如何利用长期作答历史\n诊断状态并指导教学？',
 contribution:'分评取证、诊断与教学。\n识别遗忘与程序性错误。\n覆盖同构题的迁移障碍。',
 evidence:'真实学习日志与专家标注。\n取证较强，诊断仍有缺口。\n教学行动另设独立评价。',
 caption:'原文图 2：历史证据获取、知识状态诊断与个性化教学行动',
 footer:'Ning Li et al. 中国科学技术大学. ACL 2026. DOI: 10.18653/v1/2026.acl-long.1371',
 figure:'longtutor-framework',frame:{left:505,top:185,width:1020,height:610},
 notes:'作者：Ning Li, Zheng Zhang, Zhenya Huang, Rui Li, Yi Zhan, Yinbo Luo, Qi Liu, Enhong Chen。中国科学技术大学等。ACL 2026，29712–29737页。\n三层任务：历史证据获取包含单记录信息提取、多次交互推理、幻觉检查；状态诊断区分Recall Failure、Conceptual Gap、Procedural Error、Transfer Deficit；教学行动要求依据历史证据和诊断生成个性化反馈。状态诊断主要报告Macro-F1，教学行动采用单独的评价维度。\n论文发现历史取证能力不必然转化为诊断及教学能力。图2用先前成功与11天后同知识出错的记录说明遗忘诊断和提取练习策略。图1另以锯木头/爬楼梯同构题说明迁移障碍。\n原图：PDF第4页图2。离线任务和模拟学生实验不能直接替代长期真实学生学习效果验证。'});

// 08: MathCog. Table excerpt is an original-paper evidence image.
await side({key:'mathcog',title:'MathCog: Diagnosing Students’ Cognitive Skills from Handwritten Math Work',titleSize:31,
 question:'省略或模糊的手写作答\n能否支持可靠的技能诊断？',
 contribution:'依据 TIMSS 构建技能清单。\n分别标注判断及证据强度。\n分析证据幻觉与过度推断。',
 evidence:'18 个模型，F1 均低于 0.5。\n模糊证据下表现更弱。\n结论限于本研究设置。',evidenceSize:25,
 caption:'原文表 1 节选：题目、学生作答、诊断清单与证据强弱判断',
 footer:'Yoonsu Kim et al. KAIST / Michigan 等. arXiv:2504.00843v2, 2026.02（预印本）',
 figure:'mathcog-example-one',frame:{left:505,top:280,width:1020,height:405},
 extra:'同一份作答中，技能判断与证据强度分别标注。\nEvident / Vague 表示证据是否清晰充分。',
 notes:'完整题名：Benchmarking Large Language Models for Diagnosing Students’ Cognitive Skills from Handwritten Math Work。Yoonsu Kim等，KAIST、University of Michigan、Ewha Womans University、AlgorithmLabs。arXiv:2504.00843v2，2026-02-04，预印本。\n依据TIMSS认知技能清单，对学生是否展示技能作Yes/No判断，并区分Evident/Vague证据。论文评估18个模型，在该任务上的F1均低于0.5，模糊证据尤其困难。模型常见错误包括把模糊证据当明确证据、从少量线索过度推断、幻觉出不存在的依据。\n版本注意：PDF摘要/引言列110题、639份作答、3,036诊断判断，正文部分仍出现137题、796份作答等不同口径。因此本页不使用样本量作为结论或规模比较，后续复现须核实实际数据版本。\n图片为PDF第4页表1的第一个样例节选，保留列标题与该样例全部诊断项。'});

// 09: MathTutorBench.
await side({key:'mathtutorbench',title:'MathTutorBench: Measuring Open-ended Pedagogical Capabilities of LLM Tutors',titleSize:30,
 question:'解题能力能否代表\n数学辅导的教学能力？',
 contribution:'覆盖三类能力、七项任务。\n奖励模型评价开放式反馈。\n分评错误定位与教学支架。',
 evidence:'评测开源与闭源模型。\n解题强不等于教学强。\n长对话增加辅导难度。',
 caption:'原文图 2：任务、数据与指标，以及模型在不同辅导任务上的表现',
 footer:'Jakub Macina et al. ETH Zurich / TU Darmstadt. EMNLP 2025. DOI: 10.18653/v1/2025.emnlp-main.11',
 figure:'mathtutorbench-framework',frame:{left:505,top:185,width:1020,height:610},
 notes:'完整题名：MathTutorBench: A Benchmark for Measuring Open-ended Pedagogical Capabilities of LLM Tutors。Jakub Macina, Nico Daheim, Ido Hakimi, Manu Kapur, Iryna Gurevych, Mrinmaya Sachan。EMNLP 2025，204–221页。\n三类能力：数学专长、理解学生、教学能力。七项主任务：解题、苏格拉底式提问、作答正确性判断、错误定位、错误纠正、教学支架生成、教学指令遵循；另有更难变体。数据包括GSM8K、MathDial、Bridge及StepVerify等。\n开放式教师回复采用训练的奖励模型评分，并验证其区分专家与新手回复的能力。论文发现解题专长不立即转化为教学能力，长对话也带来额外挑战。图2为原论文当时所评测模型，不代表当前模型排行榜。\n原图：PDF第3页图2。'});

// 10: Tutor CoPilot, using v3 consistently.
await side({key:'copilot',title:'Tutor CoPilot: A Human-AI Approach for Scaling Real-Time Expertise',titleSize:33,
 question:'AI 如何实时帮助教师\n选择有效的辅导策略？',
 contribution:'将专家决策过程用于提示。\n嵌入真人辅导对话工作流。\n教师选择并修改建议回复。',
 evidence:'随机对照实验。\n总体掌握概率提高 4 个百分点。\n低评分教师组提高 9 个百分点。',evidenceSize:24.5,
 caption:'原文图 1：嵌入实时辅导场景的前端与专家引导生成流程',
 footer:'Rose E. Wang et al. Stanford. arXiv:2410.03017v3, 2026.10（预印本修订版）',
 figure:'copilot-framework',frame:{left:505,top:180,width:1020,height:615},
 notes:'完整题名：Tutor CoPilot: A Human-AI Approach for Scaling Real-Time Expertise。Rose E. Wang, Ana T. Ribeiro, Carly D. Robinson, Susanna Loeb, Dora Demszky，Stanford。采用2026-10-10的v3 PDF。\n系统嵌入真人在线辅导对话。教师按需调用，收到基于专家决策模型的若干回复建议，可选择、编辑或重新生成。后端包括去识别处理以及专家式引导生成。\nv3 PDF报告700多名教师与1,000多名学生参与的随机对照实验。获得系统支持教师所辅导学生的数学主题掌握概率提高4个百分点（p<.01）；较低评分教师对应学生提高9个百分点。比较的是获得与未获得系统支持的教师条件，不是学生直接使用自动AI。\n摘要网页与v3 PDF存在旧样本数口径差异，故本页统一采用v3，不混用旧版样本数。原图：PDF第3页图1。学习掌握指标不等于长期考试提分。'});

const deckIds=await Promise.all(deck.map(async s=>JSON.parse(await (await s.export({format:'layout'})).text()).slide.id));
p.slides.keep(deckIds);
p.slides.reorder(deckIds);
await fs.mkdir(path.join(BUILD,'preview'),{recursive:true});
for(let i=0;i<p.slides.items.length;i++){
 const slide=p.slides.items[i];
 const b=await p.export({slide,format:'png',scale:1});
 await fs.writeFile(path.join(BUILD,'preview',`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await b.arrayBuffer()));
 await fs.writeFile(path.join(BUILD,'preview',`slide-${String(i+1).padStart(2,'0')}.json`),await (await slide.export({format:'layout'})).text());
}
await (await PresentationFile.exportPptx(p)).save(path.join(BUILD,'candidate.pptx'));
await fs.writeFile(path.join(BUILD,'authored.ndjson'),(await p.inspect({kind:'slide,textbox,image,notes',maxChars:300000})).ndjson);
const {finalizePresentation}=await import(pathToFileURL(path.join(SKILL,'container_tools/artifact_tool_utils.mjs')).href);
const result=await finalizePresentation({
 workspaceDir:ROOT,candidatePath:path.join(BUILD,'candidate.pptx'),finalPath:FINAL,
 pythonExecutable:'/Users/sqz/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',
 integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
 layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
 layoutArgs:['--expected-slide-size-emu','15240000,8572500','--validate-bullet-geometry','--validate-heading-fit'],
 requiredNativeTableOwnerSlides:[],requiredNativeChartOwnerSlides:[],
 fontPolicy:{basis:'reference',families:[CN,BODY,'Arial'],referencePath:SOURCE,referenceSha256:createHash('sha256').update(await fs.readFile(SOURCE)).digest('hex')},
 verifyArtifactToolImport:true,
 receiptPath:path.join(BUILD,'final-validation.json'),
});
console.log(JSON.stringify({slides:p.slides.items.length,final:FINAL,result},null,2));
