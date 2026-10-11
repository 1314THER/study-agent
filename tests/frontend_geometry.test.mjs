import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const context=vm.createContext({});
vm.runInContext(readFileSync(new URL('../frontend/geometry.js',import.meta.url),'utf8'),context);
const {viewFor,assetUrl,keyOf}=context.StudyGeometry;
const g={scenes:[{id:'main',objects:[{id:'A',base:true},{id:'PE'},{id:'CE'},{id:'future'}]}],
  steps:[{step_key:'1-1',scene_id:'main',full_visible:['PE','CE'],hint_groups:[{text:'连接PE',visible:['PE'],highlight:['PE']},{text:'连接CE',visible:['CE'],highlight:['CE']}]},
    {step_key:'2-1',scene_id:'main',full_visible:['future'],hint_groups:[{text:'后续构造',visible:['future'],highlight:['future']}]}]};
let view=viewFor(g,{released:{},completed:[]},'1-1',0,true);
assert.deepEqual([...view.visible],['A']);
view=viewFor(g,{released:{'1-1':1},completed:[]},'1-1',0,true);
assert.deepEqual([...view.visible],['A','PE']);assert.equal(view.text,'连接PE');assert(!view.visible.has('future'));
view=viewFor(g,{released:{'1-1':2},completed:['1-1']},'2-1',0,true);
assert.deepEqual([...view.visible],['A','PE','CE']);assert(!view.visible.has('future'));
view=viewFor(g,{released:{},completed:[]},null,1,false);assert(view.visible.has('future'));
assert.equal(keyOf({chunk_id:2,step_number:1}),'2-1');
assert.equal(assetUrl('../settings.json'),null);assert.equal(assetUrl('/tmp/figure.png'),null);
assert.equal(assetUrl('a'.repeat(64)+'.png'),'/question-assets/'+'a'.repeat(64)+'.png');
console.log('geometry frontend state: passed');
