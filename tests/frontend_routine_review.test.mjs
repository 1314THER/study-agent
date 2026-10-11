import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this._text='';this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.dataset={};this.elements=[];}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(c=>c.textContent||'').join('');}
  get firstChild(){return this.children[0];}
  get options(){return this.children.filter(c=>c.tagName==='OPTION');}
  get selectedOptions(){return this.options.filter(o=>o.selected);}
  append(...values){this.children.push(...values.map(v=>typeof v==='string'?{textContent:v}:v));}
  prepend(...values){this.children.unshift(...values);}
  replaceChildren(...values){this.children=[];this._text='';this.append(...values);}
  setAttribute(key,value){this[key]=value;}
}
const html=fs.readFileSync(new URL('../frontend/routine-review.html',import.meta.url),'utf8');
const elements=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element()]));
for(const name of ['keyword','review_status','confidence','completeness']){const el=new Element('select');el.name=name;elements.get('filterForm').elements.push(el);}
const batch=['confirm','assign','defer','reject'].map(action=>{const el=new Element('button');el.dataset.batch=action;el.textContent=action;return el;});
const document={getElementById:id=>elements.get(id),createElement:tag=>new Element(tag),querySelectorAll:selector=>selector==='[data-batch]'?batch:[]};
let run={run_id:'real-run',created_at:1791720000,revision:0,total:53,status:'done',processed:53,calls:53,counts:{classified:53},review_counts:{pending:53},needs_content:0,kind_counts:{},reason:''};
const groups=[{id:'SET-014',name:'子集个数',category:'集合与逻辑用语',total:53,confirmed:0},{id:'SET-015',name:'受限子集',category:'集合与逻辑用语',total:0,confirmed:0}];
const rows=Array.from({length:53},(_,i)=>({item_id:i+1,item:{question:'原题 '+(i+1),answer:'4',solution:'原解析',version:1,completeness:'complete'},primary_id:'SET-014',secondary_ids:[],review_status:'pending',confidence:'high',needs_content:0,status:'classified',kind:'',marks:[],result:{classification:{method_summary:'原文理由',evidence:[]}},occurrences:[],assets:[],human:null}));
let requests=[], resolveOld;
const fetch=async(url,options={})=>{
  const parsed=new URL(url,'http://localhost');const body=options.body?JSON.parse(options.body):null;requests.push({url,body});
  let data;
  if(url.endsWith('/runs/latest'))data={run};
  else if(url.endsWith('/groups'))data={groups,catalog:{routines:groups},unmatched:0};
  else if(url.includes('/items?')){const page=Number(parsed.searchParams.get('page'));data={data:rows.slice((page-1)*50,page*50),total:53,page,page_size:50};}
  else if(url.endsWith('/decisions')){assert.equal(body.expected_revision,run.revision);run={...run,revision:run.revision+1};data={updated:body.all_filtered?53:body.item_ids.length,revision:run.revision};}
  else if(url.endsWith('/runs')&&body)data={run_id:run.run_id};
  else if(url.endsWith('/control'))data={run};
  else if(url.endsWith('/web-packet'))data={packet_id:'web-test',prompt:'冻结目录与原题',item_ids:[1,2,3,4,5],reused:false};
  else if(url.endsWith('/web-packets/web-test/response'))data={packet_id:'web-test',imported:5,idempotent:false};
  else if(url.endsWith('/items/1')&&resolveOld===true)return new Promise(resolve=>{resolveOld=()=>resolve({ok:true,json:async()=>structuredClone(rows[0])});});
  else if(/\/items\/\d+$/.test(url))data=rows[Number(url.split('/').at(-1))-1];
  else data=run;
  return {ok:true,json:async()=>structuredClone(data)};
};
const saved=new Map();let confirmations=[];
const window={addEventListener(){},PoolMath:null,history:{replaceState(_state,_title,url){context.location.search=new URL(url,'http://localhost').search;}}};
const context={document,window,fetch,URLSearchParams,crypto:{randomUUID:()=> 'unique-request'},location:{search:'?run=discarded-run'},localStorage:{getItem:k=>saved.get(k)||null,setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},
  StudyAuth:{ready:Promise.resolve(),isOwner:()=>true,state:{user:{id:'owner'}}},setInterval(){},confirm:text=>{confirmations.push(text);return true;},FormData:class{constructor(form){this.form=form;}*[Symbol.iterator](){for(const el of this.form.elements)yield [el.name,el.value];}},console};
vm.runInNewContext(fs.readFileSync(new URL('../frontend/routine-review.js',import.meta.url),'utf8'),context);
const flush=async()=>{for(let i=0;i<8;i++)await new Promise(resolve=>setImmediate(resolve));};
await flush();
assert.equal(elements.get('itemList').children.length,50);
assert.match(elements.get('resultCount').textContent,/53/);
assert.match(elements.get('groupList').textContent,/53/);
assert.equal(elements.get('filterCategory').options.length,2);
assert.equal(elements.get('exportReport').href,'/routine-review/runs/real-run/report');

const selectFirst=()=>{const checkbox=elements.get('itemList').children[0].children[0].children[0].children[0];checkbox.checked=true;checkbox.onchange();};
selectFirst();elements.get('nextPage').onclick();await flush();
assert.equal(elements.get('itemList').children.length,3);selectFirst();
assert.match(elements.get('selectionCount').textContent,/已选 2/);
elements.get('actionScope').value='selected';await batch[0].onclick();await flush();
const selected=requests.filter(r=>r.url.endsWith('/decisions')).at(-1).body;
assert.deepEqual([...selected.item_ids],[1,51]);
assert.equal(selected.all_filtered,false);

elements.get('actionScope').value='filtered';await batch[0].onclick();await flush();
const all=requests.filter(r=>r.url.endsWith('/decisions')).at(-1).body;
assert.equal(all.all_filtered,true);assert.equal(all.expected_count,53);assert.match(confirmations.at(-1),/53/);

// Out-of-order detail responses must not replace the newest clicked question.
elements.get('prevPage').onclick();await flush();resolveOld=true;
elements.get('itemList').children[0].onclick();await flush();
elements.get('itemList').children[1].onclick();await flush();
assert.match(elements.get('itemDetail').textContent,/原题 #2/);
resolveOld();await flush();
assert.match(elements.get('itemDetail').textContent,/原题 #2/);
assert(!elements.get('itemDetail').textContent.includes('原题 #1 ·'));
assert(saved.has('routine_review_v1_owner'));
assert(html.includes('loop.html'));
// Existing progress disables new snapshots, even when a stale link names another run.
assert.equal(elements.get('startRun').disabled,true);
assert.equal(context.location.search,'?run=real-run');
assert.equal(requests.some(r=>r.url.includes('/runs/discarded-run')),false);
await elements.get('startRun').onclick();await flush();
assert.equal(requests.filter(r=>r.url.endsWith('/runs')&&r.body).length,0);
elements.get('matchEngine').value='deepseek';await elements.get('applyEngine').onclick();await flush();
assert.equal(requests.findLast(r=>r.url.endsWith('/control')).body.action,'optimize');
assert.match(elements.get('usageSummary').textContent,/旧请求没有保存/);
await elements.get('openWebReview').onclick();await flush();
assert.equal(elements.get('webReviewPanel').hidden,false);
assert.match(elements.get('webPacketSummary').textContent,/本批 5 道/);
assert.equal(elements.get('webPrompt').value,'冻结目录与原题');
elements.get('webResponse').value='{"packet_id":"web-test","results":[]}';
await elements.get('importWebResponse').onclick();await flush();
assert.equal(requests.findLast(r=>r.url.endsWith('/web-test/response')).body.response,'{"packet_id":"web-test","results":[]}');
assert.equal(elements.get('webResponse').value,'');
assert.match(elements.get('reviewMessage').textContent,/已保存 5 道网页匹配建议/);
console.log('Routine review checks passed: all 53 questions, pagination, cross-page selection, explicit whole-filter scope, count/revision contract, restored state and stale detail protection.');
