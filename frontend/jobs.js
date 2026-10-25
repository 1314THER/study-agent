/* Shared task client. The server owns execution; leaving this page only stops polling. */
(function () {
  'use strict';
  if (window.StudyJobs) return;
  var nativeFetch = window.fetch.bind(window), jobs = new Map(), waiters = new Map();
  var timer, polling = false, uploads = 0, pendingNavigation = null;
  var titles = {solve:'题目解答',teach_start:'教学准备',teach_chat:'教学对话',teach_check:'步骤检查',teach_ack:'教学进度',teach_finish:'教学记录',generate:'仿题生成',grade:'AI 批改',parse_file:'文件识别',ocr_file:'手写识别',batch_solve:'批量解题',agent:'AI 教练',pattern_check:'套路检查',pattern_variants:'变式生成',provider_test:'连接测试',pool_prepare:'原题解析准备',pool_import:'原题来源采集',pool_collect:'在线找题',routine_match:'全量套路匹配',exam_extract:'整卷切题识别',exam_solve:'整卷逐题解答'};
  titles.curriculum_research='课时资料整理';
  function uuid() { return window.crypto && crypto.randomUUID ? crypto.randomUUID() : Date.now().toString(36)+'-'+Math.random().toString(36).slice(2); }
  function read(key) { try{return JSON.parse(localStorage.getItem('study_job_'+key)||'null');}catch(e){return null;} }
  function write(key,value) { try{localStorage.setItem('study_job_'+key,JSON.stringify(value));}catch(e){} }
  function emit(name,j) { document.dispatchEvent(new CustomEvent(name,{detail:j}));document.dispatchEvent(new CustomEvent('study:job-update',{detail:{job:j,type:j.kind,id:j.job_id}})); }
  function terminal(j) { return ['done','error','interrupted','cancelled'].includes(j.status); }
  function errorFor(j) { var e=new Error(typeof j.error==='string'?j.error:(j.error&&j.error.detail)||j.detail||'任务未完成');e.job=j;return e; }
  async function api(url,options) { var r=await nativeFetch(url,options);var d=await r.json();if(!r.ok){throw new Error(d.detail||d.error||('HTTP '+r.status));}return d; }
  function publish(j) {
    var old=jobs.get(j.job_id);jobs.set(j.job_id,Object.assign({},old||{},j));j=jobs.get(j.job_id);
    emit('studyjobupdate',j);
    var ws=waiters.get(j.job_id)||[];
    ws.forEach(function(w){if(w.onProgress)w.onProgress(j);});
    if(terminal(j)&&Object.prototype.hasOwnProperty.call(j,'result')) {
      waiters.delete(j.job_id);ws.forEach(function(w){if(j.status==='done')w.resolve(j.result);else w.reject(errorFor(j));});
      if(!old||!terminal(old)){
        emit('studyjobdone',j);
        if(old&&!terminal(old)){
          var notice=node('button',(titles[j.kind]||'后台任务')+(j.status==='done'?'已完成 · 查看结果':'未完成 · 查看原因'),'study-job-notice');
          notice.onclick=function(){showResult(j.job_id);notice.remove();};document.body.appendChild(notice);setTimeout(function(){notice.remove();},18000);
        }
      }
    }
    render();
  }
  async function get(id) { var j=await api('/jobs/'+encodeURIComponent(id));publish(j);return j; }
  function wait(j,onProgress) {
    if(terminal(j)&&Object.prototype.hasOwnProperty.call(j,'result'))return j.status==='done'?Promise.resolve(j.result):Promise.reject(errorFor(j));
    return new Promise(function(resolve,reject){var ws=waiters.get(j.job_id)||[];ws.push({resolve:resolve,reject:reject,onProgress:onProgress});waiters.set(j.job_id,ws);if(onProgress)onProgress(j);schedule(0);});
  }
  async function submit(kind,args,options) {
    options=options||{};var key=options.key||kind, signature=JSON.stringify(args), old=read(key);
    var intent=old&&old.signature===signature&&old.status==='pending'?old:{request_id:uuid(),signature:signature,status:'pending'};
    write(key,intent);
    var j=await api('/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:kind,args:args,request_id:intent.request_id})});
    intent.job_id=j.job_id;write(key,intent);publish(j);emit('studyjobsubmitted',j);
    if(options.acceptOnly){wait(j).then(function(){intent.status='done';write(key,intent);}).catch(function(e){if(e.job){intent.status='error';write(key,intent);}});return j;}
    try {var value=await wait(j,options.onProgress);intent.status='done';write(key,intent);return value;}
    catch(e){intent.status=e.job?'error':'pending';write(key,intent);throw e;}
  }
  async function upload(kind,form,options) {
    options=options||{};var key=options.key||kind,file=form.get('file');
    uploads++;render();window.dispatchEvent(new Event('studyuploadstart'));
    var j,intentKey,intent,accepted=false;
    try {
      var signature=(form.get('teacher')||'liangliang')+':'+(file?[file.name,file.size,file.lastModified].join(':'):'upload');
      // Protect navigation while hashing as well as uploading. A retry reuses
      // its acceptance ID even when the first HTTP response was lost.
      if(file&&window.crypto&&crypto.subtle){var digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());signature=(form.get('teacher')||'liangliang')+':'+file.name+':'+file.size+':'+Array.from(new Uint8Array(digest)).map(function(b){return b.toString(16).padStart(2,'0');}).join('');}
      intentKey=key+':'+signature;var previous=read(intentKey);
      intent=previous&&previous.status==='pending'?previous:{request_id:uuid(),signature:signature,status:'pending'};
      write(intentKey,intent);form.set('kind',kind);form.set('request_id',intent.request_id);
      j=await api('/jobs/uploads',{method:'POST',body:form});
      if(!j||!j.job_id)throw new Error('服务器未确认文件任务，请重试上传。');
      intent.job_id=j.job_id;write(intentKey,intent);write(key,intent);
      write('route:'+j.job_id,Object.assign({page:location.pathname.split('/').pop()},options.route||{}));
      if(options.onAccepted)options.onAccepted(j);
      publish(j);emit('studyjobsubmitted',j);accepted=true;
    } catch(e) {pendingNavigation=null;throw e;}
    finally {uploads--;render();if(!uploads&&accepted&&pendingNavigation){var target=pendingNavigation;pendingNavigation=null;location.href=target;}}
    try{var result=await wait(j,options.onProgress);intent.status='done';write(intentKey,intent);write(key,intent);return result;}catch(e){if(e.job){intent.status='error';write(intentKey,intent);}throw e;}
  }
  async function resume(key,onProgress) {var saved=read(key);if(!saved||!saved.job_id)return null;var j=await get(saved.job_id);return wait(j,onProgress);}
  async function latest(kind) {await poll();return Array.from(jobs.values()).filter(function(j){return j.kind===kind;}).sort(function(a,b){return b.created_at-a.created_at;})[0]||null;}
  function schedule(delay) {clearTimeout(timer);timer=setTimeout(poll,delay===undefined?(document.hidden?15000:3000):delay);}
  async function poll() {
    if(polling)return;polling=true;
    try {
      var list=await api('/jobs'), ids=new Set();
      for(var j of list.jobs||[]){ids.add(j.job_id);var old=jobs.get(j.job_id);if(terminal(j)&&(!old||!terminal(old)||waiters.has(j.job_id)))await get(j.job_id);else publish(j);}
      jobs.forEach(function(j,id){if(!ids.has(id)){jobs.delete(id);var ws=waiters.get(id)||[];ws.forEach(function(w){w.reject(new Error('本次体验已结束，任务不可再访问。'));});waiters.delete(id);}});
    }catch(e){var status=document.getElementById('studyJobsNetwork');if(status)status.textContent='连接暂时中断，重新连接后会继续查询。';}
    finally {polling=false;schedule();}
  }
  function node(tag,text,cls) {var n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
  function render() {
    var list=document.getElementById('studyJobsList');if(!list)return;list.replaceChildren();
    var values=Array.from(jobs.values()).sort(function(a,b){return Number(b.created_at)-Number(a.created_at);});
    if(!values.length)list.appendChild(node('p','暂时没有任务。启动 AI 操作后，可以在任何页面查看进度。'));
    values.slice(0,60).forEach(function(j){
      var row=node('article',undefined,'study-job-row');row.appendChild(node('strong',titles[j.kind]||j.kind));
      var status={queued:'等待执行',running:'进行中',done:'完成',error:'失败',interrupted:'服务重启，任务已中断',cancelled:'已停止'}[j.status]||j.status;
      row.appendChild(node('span',status,'study-job-state '+j.status));
      row.appendChild(node('p',j.detail||j.stage||''));
      if(j.args&&j.args.question)row.appendChild(node('p',j.args.question.slice(0,120),'study-job-question'));
      if(!terminal(j)){var bar=node('progress');bar.max=100;bar.value=j.progress||0;row.appendChild(bar);}
      var btn=node('button',terminal(j)?'查看结果':'查看进度');btn.onclick=function(){showResult(j.job_id);};row.appendChild(btn);list.appendChild(row);
    });
    var running=values.filter(function(j){return !terminal(j);}).length, entry=document.getElementById('studyJobsButton');
    if(entry)entry.textContent='后台任务'+(running?' · '+running:'');
    var up=document.getElementById('studyJobsUpload');if(up){up.hidden=!uploads;up.textContent='文件上传中，请稍候。站内跳转将在服务器确认后继续。';}
  }
  function renderValue(value,container,depth) {
    if(value===null||value===undefined)return;
    if(typeof value==='string'){var p=node('p',value);p.style.whiteSpace='pre-wrap';container.appendChild(p);return;}
    if(typeof value!=='object'){container.appendChild(node('span',String(value)));return;}
    if(Array.isArray(value)){value.forEach(function(v){var box=node('section',undefined,'study-job-result-block');renderValue(v,box,depth+1);container.appendChild(box);});return;}
    var labels={question:'题目',final_answer:'答案',answer:'答案',content:'内容',reply:'教练回复',message:'反馈',explanation:'说明',chunk_results:'分步解析',steps:'步骤',solution:'解题过程',text:'识别文字（草稿）',questions:'识别题目',items:'逐题结果',error:'错误',detail:'说明',stage:'阶段',title:'标题',summary:'总结',knowledge_points:'知识点',strategy:'思路',score:'得分',full_score:'满分',current_step:'当前步骤',total_steps:'步骤总数',stats:'本次记录'};
    Object.keys(value).forEach(function(k){if(['token_usage','raw','messages','history','source_meta'].includes(k))return;var v=value[k];if(typeof v==='object'||labels[k]){container.appendChild(node('h4',labels[k]||k));renderValue(v,container,depth+1);}else if(['status','is_correct','source','saved_question_id'].includes(k))container.appendChild(node('p',k+'：'+String(v)));});
  }
  async function showResult(id) {
    var panel=document.getElementById('studyJobsPanel');if(panel)panel.hidden=false;
    var target=document.getElementById('studyJobsResult');target.replaceChildren(node('p','正在读取任务…'));
    try {
      var j=await get(id);target.replaceChildren(node('h3',titles[j.kind]||j.kind));
      if(j.source==='prepared_cache'||j.result&&j.result.source==='prepared_cache')target.appendChild(node('p','预先准备的示例解析 · 本次实时 AI 未在 300 秒内完成。','study-job-cache'));
      if(j.status!=='done')target.appendChild(node('p',(j.error&&j.error.detail)||j.detail||'任务仍在后台进行。'));
      if(j.result){
        var visibleResult=j.result;
        if(j.kind==='grade'&&j.result.loop){
          var loop=j.result.loop;
          target.appendChild(node('p',loop.completed?'本轮已通过，掌握状态已保存。':loop.needs_variants?'母题已通过，生成并完成变式后继续。':j.result.is_correct?'本题已通过，挑战进度已保存。':'本次未通过，尝试记录与掌握状态已保存。'));
          visibleResult=Object.assign({},j.result);delete visibleResult.loop;
        }
        renderValue(visibleResult,target,0);
      }
      if(j.kind==='routine_match'){
        var reviewLink=node('a','打开套路审核');
        reviewLink.href='routine-review.html?run='+encodeURIComponent(j.args&&j.args.run_id||j.result&&j.result.run_id||'');
        target.appendChild(reviewLink);
      }
      if(j.kind==='curriculum_research'){
        var curriculumLink=node('a','打开课时整理建议');
        curriculumLink.href='curriculum-wiki.html?panel=tasks';
        target.appendChild(curriculumLink);
      }
      if(j.status==='done'&&['solve','teach_start','teach_chat','teach_ack','grade','parse_file','ocr_file','batch_solve','pool_prepare','pool_import','exam_extract','exam_solve'].includes(j.kind)){
        var page={solve:'index.html',teach_start:'teach.html',teach_chat:'teach.html',teach_ack:'teach.html',grade:'grade.html',parse_file:'multimodal.html',ocr_file:'teach.html',batch_solve:'multimodal.html',pool_prepare:'question-pool.html',pool_import:'question-pool.html',exam_extract:'exam-analysis.html',exam_solve:'exam-analysis.html'}[j.kind];
        if(j.kind==='solve'&&(window.STUDY_DEMO||j.args&&j.args.client_page==='multimodal'))page='multimodal.html';
        if(j.kind==='grade'&&j.args&&j.args.loop)page='loop.html?pattern_id='+encodeURIComponent(j.args.loop.pattern_id);
        if(j.kind==='ocr_file'){var route=read('route:'+j.job_id);if(route&&['grade.html','teach.html'].includes(route.page))page=route.page;}
        var link=node('a','在功能页面打开');link.href=page+(page.includes('?')?'&':'?')+'job='+encodeURIComponent(id);target.appendChild(link);
      }
      if(j.kind==='agent'&&j.result&&(j.result.actions||[]).length){var actionButton=node('button','打开相关功能');actionButton.onclick=function(){if(window.AgentGlobal){actionButton.disabled=true;AgentGlobal.applyActions(j.result.actions);}};target.appendChild(actionButton);}
      if(window.renderMathInElement)renderMathInElement(target,{delimiters:[{left:'$$',right:'$$',display:true},{left:'$',right:'$',display:false}]});
    }catch(e){target.replaceChildren(node('p',e.message));}
  }
  function init() {
    var link=document.createElement('link');link.rel='stylesheet';link.href='/jobs.css';document.head.appendChild(link);
    var entry=node('button','后台任务','study-jobs-button');entry.id='studyJobsButton';entry.onclick=function(){document.getElementById('studyJobsPanel').hidden=false;poll();};document.body.appendChild(entry);
    var panel=node('aside',undefined,'study-jobs-panel');panel.id='studyJobsPanel';panel.hidden=true;
    var close=node('button','关闭','study-jobs-close');close.onclick=function(){panel.hidden=true;};panel.appendChild(close);panel.appendChild(node('h2','后台任务'));
    panel.appendChild(node('p','切换页面或刷新后，任务仍由服务器执行。完成后点击查看结果。'));
    var up=node('p',undefined,'study-jobs-upload');up.id='studyJobsUpload';up.hidden=true;panel.appendChild(up);
    var network=node('p');network.id='studyJobsNetwork';panel.appendChild(network);
    var result=node('div');result.id='studyJobsResult';panel.appendChild(result);
    var list=node('div');list.id='studyJobsList';panel.appendChild(list);document.body.appendChild(panel);poll();
  }
  document.addEventListener('click',function(e){if(!uploads)return;var a=e.target.closest('a[href]');if(a&&a.origin===location.origin&&!a.hash){e.preventDefault();e.stopImmediatePropagation();pendingNavigation=a.href;document.getElementById('studyJobsPanel').hidden=false;render();}},true);
  window.addEventListener('beforeunload',function(e){if(uploads){e.preventDefault();e.returnValue='文件尚未上传完成';}});
  document.addEventListener('visibilitychange',function(){schedule(document.hidden?15000:0);});
  window.StudyJobs={submit:submit,upload:upload,resume:resume,latest:latest,get:get,poll:poll,showResult:showResult,wait:wait,uuid:uuid,read:read};
  // Existing small AI entry points use the same persisted jobs without duplicating their page renderers.
  window.fetch=async function(input,options) {
    var url=typeof input==='string'?input:(input&&input.url)||'', path;
    try{var u=new URL(url,location.href);if(u.origin!==location.origin)return nativeFetch(input,options);path=u.pathname;}catch(e){return nativeFetch(input,options);}
    options=options||{};if((options.method||'GET').toUpperCase()!=='POST')return nativeFetch(input,options);
    var kind,args,match;
    if(path==='/settings/test')kind='provider_test';
    else if(/^\/grade(?:\/text)?$/.test(path))kind='grade';
    else if(path==='/teach/check')kind='teach_check';
    else if(path==='/teach/start')kind='teach_legacy_start';
    else if(path==='/teach/session/start')kind='teach_start';
    else if((match=path.match(/^\/teach\/session\/([a-f0-9-]+)\/(chat|ack)$/))){kind='teach_'+match[2];}
    else if((match=path.match(/^\/patterns\/(-?\d+)\/(check|ensure-variants)$/)))kind=match[2]==='check'?'pattern_check':'pattern_variants';
    else if((match=path.match(/^\/questions\/(-?\d+)\/generate(?:\/async)?$/)))kind='generate';
    else if(path==='/multimodal/parse'||path==='/ocr/answer'){
      try{var result=await upload(path==='/ocr/answer'?'ocr_file':'parse_file',options.body,{key:location.pathname+path});return new Response(JSON.stringify(result),{status:200,headers:{'Content-Type':'application/json'}});}catch(e){return new Response(JSON.stringify({error:'task_error',detail:e.message}),{status:500});}
    }
    if(!kind)return nativeFetch(input,options);
    try{args=JSON.parse(options.body||'{}');if(match&&kind.startsWith('teach_')){args.session_id=match[1];if(window.studyTeachRevision!==undefined)args.expected_revision=window.studyTeachRevision;}if(match&&kind.startsWith('pattern_'))args.pattern_id=Number(match[1]);if(match&&kind==='generate')args.question_id=Number(match[1]);
      var data=await submit(kind,args,{key:location.pathname+path,acceptOnly:kind==='generate'&&path.endsWith('/async')});return new Response(JSON.stringify(data),{status:200,headers:{'Content-Type':'application/json'}});
    }catch(e){return new Response(JSON.stringify({error:'task_error',detail:e.message}),{status:500,headers:{'Content-Type':'application/json'}});}
  };
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
