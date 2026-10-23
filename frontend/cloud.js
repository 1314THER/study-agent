(function(){
'use strict';
const $=id=>document.getElementById(id);let section='library',offset=0,total=0,selected=null,session=null,pollTimer=null;
const draftsPrefix='cloud-draft:';
function node(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=String(text);if(cls)e.className=cls;return e;}
function button(text,action){const e=node('button',text);e.type='button';e.addEventListener('click',()=>Promise.resolve(action()).catch(report));return e;}
function report(error){$('status').textContent=error.message||String(error);}
async function api(path,method='GET',body){return StudyAuth.request('/api/v1'+path,method,body);}
function math(root){const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT),texts=[];while(walker.nextNode())texts.push(walker.currentNode);texts.forEach(n=>{const re=/\$\$([\s\S]+?)\$\$|\$([^$\n]+?)\$/g,fragment=document.createDocumentFragment();let m,last=0;while((m=re.exec(n.textContent))){fragment.append(document.createTextNode(n.textContent.slice(last,m.index)));const s=node(m[1]?'div':'span');katex.render(m[1]||m[2],s,{displayMode:!!m[1],throwOnError:false,trust:false});fragment.append(s);last=re.lastIndex;}fragment.append(document.createTextNode(n.textContent.slice(last)));n.replaceWith(fragment);});}
async function library(more=false){offset=more?offset:0;const query=new URLSearchParams({q:$('query').value,limit:'50',offset:String(offset),wrong:String(section==='wrong')});const data=await api('/questions?'+query);total=data.total;if(!more)$('questions').replaceChildren();if(!data.items.length&&!more)$('questions').append(node('p',section==='wrong'?'还没有需要复习的题目。完成一次练习后再来看看。':'还没有题目。可以添加想练习的题目。','empty'));data.items.forEach(q=>{const b=button(q.content,()=>openQuestion(q));b.className='question-row';b.append(node('small',q.owner_user_id?'我的题目':'公共题库'));$('questions').append(b);});offset+=data.items.length;$('more').hidden=offset>=total;math($('questions'));}
function draftKey(q){return draftsPrefix+StudyAuth.state.user.id+':'+q.id;}
async function submit(kind,args,channel){
 const key='cloud-request:'+channel, fingerprint=JSON.stringify({kind,args});let pending;try{pending=JSON.parse(sessionStorage.getItem(key));}catch(_){}
 if(!pending||pending.fingerprint!==fingerprint){pending={fingerprint,request_id:crypto.randomUUID()};sessionStorage.setItem(key,JSON.stringify(pending));}
 const job=await api('/jobs','POST',{kind,args,request_id:pending.request_id});$('status').textContent=job.stage;
 await watch(job.id,async result=>{sessionStorage.removeItem(key);await loadSection();if(kind==='grade'&&selected?.id===args.question_id)showGrade(result);if(kind==='teach_start'&&result.session_id)await openTeaching(result.session_id);if(kind.startsWith('teach_')&&args.session_id)await openTeaching(args.session_id);});
}
async function watch(id,complete){
 for(;;){const job=await api('/jobs/'+id);$('status').textContent=job.stage;
 if(job.status==='done'){await complete(job.result);return;}
 if(['error','interrupted','cancelled'].includes(job.status))throw new Error(job.error?.detail||job.stage);
 await new Promise(resolve=>setTimeout(resolve,1800));}
}
async function openQuestion(q){selected=q;$('library').hidden=true;$('other').hidden=true;$('detail').hidden=false;const back=button('返回题库',()=>navigate(section==='wrong'?'wrong':'library'));const layout=node('div',undefined,'practice'),statement=node('div',undefined,'statement'),answer=node('div',undefined,'answer');statement.append(node('p',q.content));const geometry=node('div');statement.append(geometry);StudyGeometry.mount(geometry,q.answer_json,{});const parsed=node('div');parsed.hidden=true;(q.answer_json.chunk_results||[]).forEach(chunk=>{(chunk.steps||[]).forEach(s=>parsed.append(node('h3',s.title||s.step_level1||'步骤'),node('p',s.standard_writing||s.detailed_writing||'')));if(chunk.final_answer)parsed.append(node('p','答案：'+chunk.final_answer));});if(!(q.answer_json.chunk_results||[]).length)parsed.append(node('p',q.answer_json.final_answer||''));statement.append(button('显示 / 隐藏解析',()=>{parsed.hidden=!parsed.hidden;}),parsed);
 const input=node('textarea');input.rows=9;input.placeholder='写下你的思路';input.setAttribute('aria-label','我的作答');input.value=localStorage.getItem(draftKey(q))||'';input.addEventListener('input',()=>localStorage.setItem(draftKey(q),input.value));const upload=node('input');upload.type='file';upload.accept='image/png,image/jpeg,application/pdf';upload.setAttribute('aria-label','上传手写作答');let assetID;upload.addEventListener('change',async()=>{try{const file=upload.files[0];if(!file)return;const form=new FormData();form.append('file',file);const response=await fetch('/api/v1/assets',{method:'POST',body:form});const data=await response.json();if(!response.ok)throw new Error(data.detail||'上传未完成');assetID=data.id;$('status').textContent='作答文件已上传';if(file.type==='application/pdf')await submit('parse_file',{asset_id:assetID},'parse:'+assetID);}catch(e){report(e);}});answer.append(node('h2','写下你的思路'),node('p','草稿保存在当前浏览器。'),input,upload,button('批改作答',()=>submit('grade',{question_id:q.id,question_revision:q.revision,student_answer:input.value,...(assetID?{asset_id:assetID}:{})},'grade:'+q.id)),button('请老师带我做',()=>submit('teach_start',{question_id:q.id},'teach:'+q.id)));const feedback=node('div');feedback.id='feedback';answer.append(feedback);layout.append(statement,answer);$('detail').replaceChildren(back,layout);math(statement);}
function showGrade(attempt){const feedback=$('feedback');if(!feedback)return;feedback.replaceChildren(node('p',attempt.result?.feedback||'批改已完成','feedback'));(attempt.result?.step_results||[]).forEach(s=>feedback.append(node('p',s.feedback||s.comment||'')));}
async function openTeaching(id){session=await api('/teaching/'+id);$('library').hidden=true;$('detail').hidden=false;$('other').hidden=true;const root=$('detail');root.replaceChildren(button('返回教学列表',()=>navigate('teaching')),node('h2',session.question));(session.messages||[]).forEach(m=>{const message=node('div',undefined,'message');message.append(node('small',m.role==='student'?'我的回答':'老师'),node('p',m.content));root.append(message);});const input=node('textarea');input.rows=3;input.setAttribute('aria-label','教学回答');if(!session.step_introduced&&session.steps?.[session.current_step])root.append(node('p',session.steps[session.current_step].step_prompt||''));const send=(kind,message=input.value)=>submit(kind,{session_id:id,expected_revision:session.revision,message},'teaching:'+id).then(()=>openTeaching(id));root.append(input,button('发送回答',()=>send('teach_chat')),button('跳过此步',()=>send('teach_chat','跳过')),button('保存学习结果',()=>send('teach_finish')));math(root);}
async function loadSection(){if(['library','wrong'].includes(section))return library();const root=$('other');root.replaceChildren();if(section==='jobs'){const data=await api('/jobs');data.items.forEach(j=>{const item=node('div',undefined,'list-item');item.append(node('h3',({solve:'解题',grade:'批改',parse_file:'识别文件',teach_start:'开始教学',teach_chat:'教学对话'})[j.kind]||'学习任务'),node('p',j.stage));if(!['done','error','interrupted'].includes(j.status)){const progress=node('progress');progress.max=100;progress.value=j.progress;item.append(progress);}if(j.kind==='parse_file'&&j.result)(j.result.questions||[]).forEach(q=>{const text=q.question||q.content||'';item.append(node('p',text),button('解题并加入题库',()=>submit('solve',{question:text},'import:'+text)));});root.append(item);});if(!data.items.length)root.append(node('p','还没有后台任务。','empty'));}
 else if(section==='progress'){const data=await api('/progress');root.append(node('h2','已完成 '+data.attempt_count+' 次作答'),node('p','回答正确 '+data.correct_count+' 次，需要复习 '+data.review_count+' 次。'));data.recent_attempts.forEach(a=>{const item=node('div',undefined,'list-item');item.append(node('p',a.student_answer),node('p',a.result.feedback||''));root.append(item);});}
 else if(section==='teaching'){const data=await api('/teaching');data.items.forEach(s=>root.append(button(s.question,()=>openTeaching(s.session_id))));if(!data.items.length)root.append(node('p','在题目中选择“请老师带我做”，开始分步学习。','empty'));}
 else if(section==='admin'){
 const select=node('select');select.setAttribute('aria-label','管理内容');
 const kinds={'pool.pool_items':'原题审核','pool.pool_sources':'题目来源','review.review_humans':'套路审核'};
 Object.entries(kinds).forEach(([value,label])=>{const option=node('option',label);option.value=value;select.append(option);});
 const records=node('div');
 const load=async()=>{
  const data=await api('/admin/records?kind='+encodeURIComponent(select.value));records.replaceChildren();
  if(!data.items.length)records.append(node('p','还没有待审核的记录。','empty'));
  data.items.forEach(record=>{
   const value=record.data,item=node('div',undefined,'list-item');
   item.append(node('h3',value.question||value.name||value.title||'来源记录'));
   if(value.answer)item.append(node('p','原答案：'+value.answer));
   if(value.solution)item.append(node('p',value.solution));
   if(value.reason)item.append(node('p',value.reason));
   item.append(node('p',({confirmed:'已确认',rejected:'已排除',deferred:'待补充'})[value.status]||'待审核'));
   const actions=node('div',undefined,'row');
   ['confirmed','deferred','rejected'].forEach(status=>actions.append(button(({confirmed:'确认可用',deferred:'稍后处理',rejected:'排除此题'})[status],async()=>{await api('/admin/records/'+record.id+'/review','PUT',{expected_revision:value._revision||0,status});await load();})));
   if(record.kind==='pool.pool_items'){
    actions.append(button('准备 AI 解析',()=>submit('pool_prepare',{record_id:record.id,expected_revision:value._revision||0},'prepare:'+record.id).then(load)));
    if(value.status==='confirmed'&&value.prepared_json){
     actions.append(button('发布为公共题',async()=>{await api('/admin/records/'+record.id+'/publish','POST',{content:value.question,answer_json:value.prepared_json,expected_revision:value._revision||0});$('status').textContent='已发布到公共题库';await load();}));
    }
    if(value.prepared_json)item.append(node('p','已准备标准解析，发布前请对照原答案核对。'));
   }
   item.append(actions);records.append(item);
  });math(records);
 };
 select.addEventListener('change',()=>load().catch(report));root.append(select,records);await load();
 }
 else if(section==='account'){root.append(node('h2',StudyAuth.state.user.username));const key=node('input');key.type='password';key.placeholder='新的 DeepSeek API Key';key.setAttribute('aria-label','DeepSeek API Key');root.append(key,button('保存密钥',async()=>{await api('/auth/api-key','PUT',{api_key:key.value});key.value='';$('status').textContent='密钥已保存';}));const data=await api('/auth/devices');data.items.forEach(d=>{const row=node('div',undefined,'list-item');row.append(node('span',d.device_name+' '),button('撤销设备会话',async()=>{await api('/auth/devices/'+d.id,'DELETE');await loadSection();}));root.append(row);});root.append(button('退出账号',logout));}}
async function navigate(value){section=value;selected=null;session=null;$('library').hidden=!['library','wrong'].includes(value);$('detail').hidden=true;$('other').hidden=!$('library').hidden;$('page-title').textContent={library:'题库',wrong:'错题复习',teaching:'教学',progress:'学习进度',jobs:'后台任务',account:'账号',admin:'原题与审核'}[value];document.querySelectorAll('nav button').forEach(b=>{if(b.dataset.section===value)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});await loadSection();}
async function logout(){if(!confirm('退出会清除此浏览器的作答草稿，是否继续？'))return;for(let i=localStorage.length-1;i>=0;i--){const key=localStorage.key(i);if(key&&key.startsWith(draftsPrefix))localStorage.removeItem(key);}await StudyAuth.request('/auth/logout','POST',{});location.replace('/login.html');}
document.querySelectorAll('[data-section]').forEach(b=>b.addEventListener('click',()=>navigate(b.dataset.section).catch(report)));$('search').addEventListener('submit',e=>{e.preventDefault();library().catch(report);});$('more').addEventListener('click',()=>library(true).catch(report));$('logout').addEventListener('click',()=>logout().catch(report));$('add-question').addEventListener('click',()=>$('new-question').showModal());$('close-new').addEventListener('click',()=>$('new-question').close());$('solve-form').addEventListener('submit',e=>{e.preventDefault();const question=$('question-text').value;$('new-question').close();submit('solve',{question},'solve:'+question).catch(report);});
StudyAuth.ready.then(async state=>{$('account-label').textContent=state.user?.username||'';$('admin-nav').hidden=state.user?.role!=='owner';await navigate('library');}).catch(report);
})();
