/* Page-specific restoration for the small AI operations handled by jobs.js. */
(function(){
  var page=location.pathname.split('/').pop(), explicit=new URLSearchParams(location.search).get('job');
  async function restore(key,kind,apply){
    var record=StudyJobs.read(key),id=explicit||(record&&record.job_id);if(!id)return;
    try{var j=await StudyJobs.get(id);if(j.kind!==kind)return;var data=j.status==='done'?j.result:await StudyJobs.wait(j);apply(data,j);}catch(e){if(page==='settings.html'&&typeof setStatus==='function')setStatus(e.message,'err');}
  }
  document.addEventListener('DOMContentLoaded',function(){
    if(page==='grade.html'){
      restore(location.pathname+'/grade','grade',function(data,j){
        var a=j.args||{},fields={questionInput:a.question,answerInput:a.student_answer,fullScore:a.full_score,duration:a.duration_seconds,qType:a.question_type,teacher:a.teacher,source:a.source};
        Object.keys(fields).forEach(function(id){var el=document.getElementById(id);if(el&&fields[id]!==undefined&&fields[id]!==null)el.value=fields[id];});
        if(a.question_id)document.getElementById('qSelect').value=String(a.question_id);
        if(typeof renderResult==='function')renderResult(data);
      });
      restore(location.pathname+'/ocr/answer','ocr_file',function(data,j){
        var route=StudyJobs.read('route:'+j.job_id),draft=route&&route.draft;
        if(draft)Object.keys(draft).forEach(function(id){var el=document.getElementById(id);if(!el)return;if(el.type==='checkbox')el.checked=!!draft[id];else{el.value=draft[id];if(id==='qSelect'&&el.value!==draft[id])el._studyRestoreValue=draft[id];}});
        if(data.text!==undefined)document.getElementById('answerInput').value=data.text;
        if(typeof toggleQuestionMode==='function')toggleQuestionMode();
      });
    }
    if(page==='teach.html')restore(location.pathname+'/ocr/answer','ocr_file',function(data){if(data.text){var input=document.getElementById('teachChatInput');input.value=data.text;input.dispatchEvent(new Event('input'));}});
    if(page==='settings.html')restore(location.pathname+'/settings/test','provider_test',function(data,j){if(typeof setStatus==='function')setStatus((j.args.provider||'API')+(data.ok?' 连接正常':' 测试失败：'+(data.error||'未知错误')),data.ok?'ok':'err');});
    if(page==='loop.html'&&explicit){if(typeof window.restoreLoopJob==='function')window.restoreLoopJob(explicit);else StudyJobs.showResult(explicit);}
  });
})();
