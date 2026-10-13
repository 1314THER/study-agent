/* Saved geometry only: no expression evaluation and no generated JavaScript. */
(function (global) {
  'use strict';
  const mounted = new WeakMap(), live = new Set();
  let jsxPromise, threePromise, counter = 0;
  const keyOf = s => String(s.chunk_id == null ? 1 : s.chunk_id) + '-' + String(s.step_number == null ? 0 : s.step_number);
  const assetUrl = id => typeof id === 'string' && /^[a-f0-9]{64}\.png$/.test(id) ? '/question-assets/' + id : null;
  function viewFor(geometry, state, activeKey, index, teaching) {
    const steps = geometry.steps || [];
    const current = teaching ? steps.find(s => s.step_key === activeKey) : steps[index];
    const scene = (geometry.scenes || []).find(s => s.id === (current && current.scene_id)) || (geometry.scenes || [])[0];
    const visible = new Set((scene && scene.objects || []).filter(o => o.base).map(o => o.id));
    let highlight = [], text = current ? '' : '本步暂无可用构造，保留题设图形。';
    if (scene) steps.forEach((s, i) => {
      if (s.scene_id !== scene.id) return;
      const completed = teaching ? (state.completed || []).includes(s.step_key) : i <= index;
      if (completed) s.full_visible.forEach(id => visible.add(id));
      if (teaching) {
        const count = Math.min((state.released || {})[s.step_key] || 0, s.hint_groups.length);
        s.hint_groups.slice(0, count).forEach(g => g.visible.forEach(id => visible.add(id)));
        if (s === current && count) { const g = s.hint_groups[count - 1]; highlight = g.highlight; text = g.text; }
      } else if (s === current) {
        highlight = s.full_visible;
        text = s.hint_groups.map(g => g.text).join('\n');
      }
    });
    return {scene, visible, highlight, text};
  }
  function node(tag, cls, text) {
    const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e;
  }
  function loadJSX() {
    if (!jsxPromise) jsxPromise = new Promise((resolve, reject) => {
      if (global.JXG) return resolve(global.JXG);
      const css = node('link'); css.rel = 'stylesheet'; css.href = '/vendor/jsxgraph-1.11.1/distrib/jsxgraph.css'; document.head.append(css);
      const script = node('script'); script.src = '/vendor/jsxgraph-1.11.1/distrib/jsxgraphcore.js';
      script.onload = () => resolve(global.JXG); script.onerror = () => reject(new Error('二维画板加载失败')); document.head.append(script);
    });
    return jsxPromise;
  }
  function loadThree() {
    if (!threePromise) threePromise = Promise.all([
      import('/vendor/three-0.180.0/build/three.module.min.js'),
      import('/vendor/three-0.180.0/examples/jsm/controls/OrbitControls.js')
    ]);
    return threePromise;
  }
  function images(root, refs) {
    const urls = [...new Set(refs || [])].map(assetUrl).filter(Boolean);
    if (!urls.length) return;
    const box = node('div', 'geometry-images');
    urls.forEach((url, i) => {
      const a = node('a', '', '查看原图 ' + (i + 1)); a.href = url; a.target = '_blank'; a.rel = 'noopener';
      const img = node('img'); img.src = url; img.loading = 'lazy'; img.alt = '原题图 ' + (i + 1);
      img.onerror = () => { img.remove(); a.textContent = '原题图暂不可访问'; a.removeAttribute('href'); };
      a.prepend(img); box.append(a);
    }); root.append(box);
  }
  function draw2D(host, scene, objects, visibility, highlight, JXG) {
    const box = node('div', 'jxgbox'); box.id = 'geometry-board-' + (++counter); host.append(box);
    const board = JXG.JSXGraph.initBoard(box.id, {boundingbox:scene.bounds, axis:true, keepaspectratio:true,
      showCopyright:false, showNavigation:false, pan:{enabled:true}, zoom:{wheel:true}, resize:{enabled:false}});
    const byId = new Map(objects.map(o => [o.id, o])), elements = new Map(), progress = new Map();
    const p = id => byId.get(id).coords;
    board.suspendUpdate();
    objects.forEach(o => {
      const color = o.base ? '#526b87' : '#e58b22';
      const attr = {fixed:true, highlight:false, visible:visibility.has(o.id), strokeColor:color, fillColor:color,
        strokeWidth:2, dash:o.dashed ? 2 : 0, name:'', withLabel:false};
      let element;
      if (o.kind === 'point') element = board.create('point',o.coords,{...attr,size:2});
      else if (['segment','line','vector'].includes(o.kind)) {
        const a=p(o.a),b=p(o.b);
        const endpoint=[()=>a[0]+(b[0]-a[0])*(progress.get(o.id)??1),()=>a[1]+(b[1]-a[1])*(progress.get(o.id)??1)];
        element = board.create(o.kind === 'vector' ? 'arrow' : o.kind,[a,endpoint],{...attr,point1:{visible:false},point2:{visible:false}});
      }
      else if (['polygon','plane'].includes(o.kind)) element = board.create('polygon',o.points.map(p),{...attr,fillOpacity:.12,vertices:{visible:false},borders:{...attr}});
      else if (o.kind === 'circle') element = board.create('circle',[p(o.center),o.radius],{...attr,center:{visible:false},fillOpacity:0});
      else if (o.kind === 'conic') {
        const [a,b,c,d,e,f] = o.coefficients;
        element = board.create('conic',[a,c,f,b/2,d/2,e/2],{...attr,fillOpacity:0});
      } else if (o.kind === 'curve') element = board.create('curve',[o.samples.map(p=>p[0]),o.samples.map(p=>p[1])],attr);
      else if (o.kind === 'angle') element = board.create('angle',o.points.map(p),{...attr,radius:.4,fillOpacity:.15,point:{visible:false}});
      else if (o.kind !== 'label') throw new Error('此二维对象暂不支持显示');
      // Use native textContent labels; JSXGraph text can interpret HTML.
      const labels = [];
      if (o.label) {
        const pos = o.coords || (o.a ? p(o.a) : o.center ? p(o.center) : o.points ? p(o.points[0]) : null);
        if (pos) { const label = node('span','geometry-label',o.label); host.append(label); labels.push({label,pos}); }
      }
      elements.set(o.id,{element,labels,o});
    });
    board.unsuspendUpdate();
    function update(visible, hi) {
      elements.forEach(({element,labels,o},id) => {
        const shown = visible.has(id), color = hi.includes(id) ? '#e57913' : o.base ? '#526b87' : '#b78226';
        if (element) {
          element.setAttribute({visible:shown,strokeColor:color,strokeWidth:hi.includes(id)?3:2});
          if (element.borders) element.borders.forEach(b=>b.setAttribute({visible:shown,strokeColor:color}));
        }
        labels.forEach(({label,pos}) => {
          const c = new JXG.Coords(JXG.COORDS_BY_USER,pos,board).scrCoords;
          label.style.left=(c[1]+5)+'px'; label.style.top=(c[2]-20)+'px'; label.hidden=!shown;
        });
      }); board.update();
    }
    const redraw = () => update(visibility,highlight);
    board.on('boundingbox',redraw);
    update(visibility,highlight);
    return {
      update(v,h,ratios){visibility=v;highlight=h;progress.clear();if(ratios)ratios.forEach((t,id)=>progress.set(id,t));update(v,h);},
      resize(){board.resizeContainer(Math.max(100,host.clientWidth),Math.max(100,host.clientHeight));redraw();},
      dispose(){board.off('boundingbox',redraw);JXG.JSXGraph.freeBoard(board);host.replaceChildren();}
    };
  }
  function draw3D(host, sceneData, objects, visibility, highlight, THREE, OrbitControls, savedCamera) {
    const scene = new THREE.Scene(); scene.background = new THREE.Color('#fbfcff');
    const renderer = new THREE.WebGLRenderer({antialias:true,alpha:false});
    renderer.setPixelRatio(Math.min(global.devicePixelRatio || 1,2)); host.append(renderer.domElement);
    const initialAspect=Math.max(100,host.clientWidth)/Math.max(100,host.clientHeight);
    const camera = new THREE.PerspectiveCamera(38,initialAspect,.001,1e8), controls = new OrbitControls(camera,renderer.domElement);
    controls.enableDamping=false;
    const entries=new Map(), byId=new Map(objects.map(o=>[o.id,o])), labels=[];
    const p = id => new THREE.Vector3(...byId.get(id).coords);
    const box = new THREE.Box3();
    objects.filter(o=>o.kind==='point').forEach(o=>box.expandByPoint(new THREE.Vector3(...o.coords)));
    objects.forEach(o=>{
      if(o.samples)o.samples.forEach(v=>box.expandByPoint(new THREE.Vector3(...v)));
      if(o.radius){const center=p(o.center),r=new THREE.Vector3(o.radius,o.radius,o.radius);box.expandByPoint(center.clone().sub(r));box.expandByPoint(center.clone().add(r));if(o.end){const end=p(o.end);box.expandByPoint(end.clone().sub(r));box.expandByPoint(end.clone().add(r));}}
    });
    if(box.isEmpty())box.set(new THREE.Vector3(-2,-2,-2),new THREE.Vector3(2,2,2));
    const center=box.getCenter(new THREE.Vector3()), scale=Math.max(box.getSize(new THREE.Vector3()).length(),1);
    // Fit the bounding sphere in both horizontal and vertical fields of view,
    // leaving space for labels on narrow phone canvases.
    const fitDistance=aspect=>{
      const vertical=camera.fov*Math.PI/360,horizontal=Math.atan(Math.tan(vertical)*aspect);
      return scale*.55/Math.sin(Math.min(vertical,horizontal));
    };
    camera.position.copy(center).add(new THREE.Vector3(1.2,-1.6,1.2).normalize().multiplyScalar(fitDistance(initialAspect)));
    camera.up.set(0,0,1); camera.lookAt(center); controls.target.copy(center);
    camera.near=scale/10000;camera.far=scale*1000;camera.updateProjectionMatrix();
    if(savedCamera){camera.position.fromArray(savedCamera.position);controls.target.fromArray(savedCamera.target);
      if(savedCamera.aspect>0)camera.position.sub(controls.target).multiplyScalar(fitDistance(initialAspect)/fitDistance(savedCamera.aspect)).add(controls.target);
      controls.update();}
    function line(points, color, dashed) {
      const geometry=new THREE.BufferGeometry().setFromPoints(points);
      const mat=dashed ? new THREE.LineDashedMaterial({color,dashSize:scale*.035,gapSize:scale*.02}) : new THREE.LineBasicMaterial({color});
      const l=new THREE.Line(geometry,mat);if(dashed)l.computeLineDistances();return l;
    }
    function face(ids,color) {
      const vertices=ids.map(p), coords=[];
      for(let i=1;i<vertices.length-1;i++) [vertices[0],vertices[i],vertices[i+1]].forEach(v=>coords.push(v.x,v.y,v.z));
      const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(coords,3));
      const group=new THREE.Group();group.add(new THREE.Mesh(geometry,new THREE.MeshBasicMaterial({color,transparent:true,opacity:.13,side:THREE.DoubleSide,depthWrite:false})));
      group.add(line([...vertices,vertices[0]],color,false));return group;
    }
    objects.forEach(o=>{
      const color=o.base ? '#526b87' : '#e58b22';let obj;
      if(o.kind==='point') {obj=new THREE.Mesh(new THREE.SphereGeometry(scale*.008,10,8),new THREE.MeshBasicMaterial({color}));obj.position.copy(p(o.id));}
      else if(['segment','line','vector'].includes(o.kind)) {
        let a=p(o.a),b=p(o.b),dir=b.clone().sub(a);
        if(o.kind==='line'){dir.normalize().multiplyScalar(scale*3);const mid=a.clone().add(b).multiplyScalar(.5);a=mid.clone().sub(dir);b=mid.clone().add(dir);}
        obj=o.kind==='vector'?new THREE.ArrowHelper(dir.clone().normalize(),a,dir.length(),color,scale*.06,scale*.025):line([a,b],color,o.dashed);
      }else if(['polygon','plane','solid'].includes(o.kind)){
        obj=new THREE.Group();(o.faces || [o.points]).forEach(ids=>obj.add(face(ids,color)));
      }else if(o.kind==='curve')obj=line(o.samples.map(v=>new THREE.Vector3(...v)),color,o.dashed);
      else if(o.kind==='circle'){
        const n=new THREE.Vector3(...o.normal).normalize(),u=new THREE.Vector3(Math.abs(n.x)<.8?1:0,Math.abs(n.x)<.8?0:1,0).cross(n).normalize(),v=n.clone().cross(u);
        obj=line(Array.from({length:97},(_,i)=>p(o.center).add(u.clone().multiplyScalar(o.radius*Math.cos(i*Math.PI/48))).add(v.clone().multiplyScalar(o.radius*Math.sin(i*Math.PI/48)))),color,o.dashed);
      }else if(o.kind==='sphere'){
        const g=new THREE.SphereGeometry(o.radius,32,20);obj=new THREE.Mesh(g,new THREE.MeshBasicMaterial({color,wireframe:true,transparent:true,opacity:.35}));obj.position.copy(p(o.center));
      }else if(['cone','cylinder'].includes(o.kind)){
        const a=p(o.center),b=p(o.end),dir=b.clone().sub(a);
        const g=new THREE.CylinderGeometry(o.kind==='cone'?0:o.radius,o.radius,dir.length(),40);
        obj=new THREE.Mesh(g,new THREE.MeshBasicMaterial({color,wireframe:true,transparent:true,opacity:.4}));
        obj.position.copy(a.clone().add(b).multiplyScalar(.5));obj.quaternion.setFromUnitVectors(new THREE.Vector3(0,1,0),dir.normalize());
      }else if(o.kind==='angle'){
        const a=p(o.points[0]),b=p(o.points[1]),c=p(o.points[2]),u=a.sub(b).normalize(),w=c.sub(b).normalize();
        const angle=Math.acos(Math.max(-1,Math.min(1,u.dot(w)))),v=w.sub(u.clone().multiplyScalar(u.dot(w))).normalize();
        obj=line(Array.from({length:33},(_,i)=>b.clone().add(u.clone().multiplyScalar(Math.cos(angle*i/32)*scale*.08)).add(v.clone().multiplyScalar(Math.sin(angle*i/32)*scale*.08))),color,false);
      }else if(o.kind==='label')obj=new THREE.Group();
      else throw new Error('此三维对象暂不支持显示');
      obj.visible=visibility.has(o.id);scene.add(obj);entries.set(o.id,{obj,o,original:obj.isLine?obj.geometry.getAttribute('position').array.slice():null});
      if(o.label){
        const pos=o.coords ? new THREE.Vector3(...o.coords):o.a?p(o.a):o.center?p(o.center):o.points?p(o.points[0]):null;
        if(pos){const el=node('span','geometry-label',o.label);host.append(el);labels.push({el,pos,id:o.id});}
      }
    });
    function render(){
      renderer.render(scene,camera);
      labels.forEach(({el,pos,id})=>{const v=pos.clone().project(camera);el.style.left=((v.x+1)*host.clientWidth/2+5)+'px';el.style.top=((1-v.y)*host.clientHeight/2-18)+'px';el.hidden=!visibility.has(id)||v.z>1||v.z< -1;});
    }
    function update(v,h,ratios){visibility=v;highlight=h;entries.forEach(({obj,o,original},id)=>{
      obj.visible=v.has(id);obj.traverse(child=>{if(child.material&&child.material.color)child.material.color.set(h.includes(id)?'#e57913':o.base?'#526b87':'#b78226');});
      if(original&&['segment','line'].includes(o.kind)){
        const attr=obj.geometry.getAttribute('position'),t=ratios&&ratios.has(id)?ratios.get(id):1;
        for(let j=0;j<3;j++)attr.array[j+3]=original[j]+(original[j+3]-original[j])*t;attr.needsUpdate=true;obj.geometry.computeBoundingSphere();if(o.dashed)obj.computeLineDistances();
      }
    });render();}
    controls.addEventListener('change',render);
    update(visibility,highlight);
    return {
      update,
      resize(){const w=Math.max(100,host.clientWidth),h=Math.max(100,host.clientHeight),aspect=w/h;renderer.setSize(w,h,false);
        if(aspect!==camera.aspect)camera.position.sub(controls.target).multiplyScalar(fitDistance(aspect)/fitDistance(camera.aspect)).add(controls.target);
        camera.aspect=aspect;camera.updateProjectionMatrix();render();},
      snapshot(){return {position:camera.position.toArray(),target:controls.target.toArray(),aspect:camera.aspect};},
      dispose(){controls.removeEventListener('change',render);controls.dispose();scene.traverse(o=>{if(o.geometry)o.geometry.dispose();if(o.material)o.material.dispose();});renderer.dispose();renderer.forceContextLoss();host.replaceChildren();}
    };
  }
  class Player {
    constructor(root,data,options) {
      this.root=root;this.data=data;this.options=options||{};this.index=-1;this.state=this.options.state||{released:{},completed:[]};this.activeKey=this.options.activeKey;
      this.visible=new Set();this.sceneId=null;this.frame=0;this.disposed=false;this.version=0;this.animation=0;this.initial=true;
      this.panel=node('details','geometry-panel');this.panel.open=global.innerWidth>700;
      this.panel.append(node('summary','',data.geometry?'几何演示与题图':'题目原图'));
      images(this.panel,data.asset_refs);this.toolbar=node('div','geometry-toolbar');this.panel.append(this.toolbar);
      this.prev=this.button('上一步',()=>this.go(this.index-1));this.next=this.button('下一步',()=>this.go(this.index+1));this.replay=this.button('重播',()=>this.show(true));
      this.select=node('select');this.select.setAttribute('aria-label','查看几何构造步骤');
      this.select.append(new Option('题设图形','-1'));
      const titles=new Map((data.chunk_results||[]).flatMap(c=>(c.steps||[]).map(s=>[keyOf({...s,chunk_id:c.chunk_id}),s.title])));
      (data.geometry&&data.geometry.steps||[]).forEach((s,i)=>this.select.append(new Option('块 '+s.step_key.split('-')[0]+' · 步骤 '+s.step_key.split('-')[1]+' '+(titles.get(s.step_key)||''),String(i))));
      this.select.onchange=()=>this.go(Number(this.select.value));this.toolbar.append(this.select);
      this.status=node('span','geometry-status');this.toolbar.append(this.status);
      this.stage=node('div','geometry-stage');this.panel.append(this.stage);
      this.parameter=node('div','geometry-parameter');this.panel.append(this.parameter);
      this.note=node('div','geometry-note');this.panel.append(this.note);
      root.prepend(this.panel);live.add(this);
      this.onClick=e=>{const step=e.target.closest('[data-chunk-id][data-step-number]');if(!this.options.teaching&&step&&root.contains(step)){const i=(this.data.geometry.steps||[]).findIndex(s=>s.step_key===keyOf({chunk_id:step.dataset.chunkId,step_number:step.dataset.stepNumber}));if(i>=0)this.go(i);}};
      root.addEventListener('click',this.onClick);
      this.panel.addEventListener('toggle',()=>{if(this.renderer)this.renderer.resize();});
      this.observer=new ResizeObserver(()=>{if(this.renderer)this.renderer.resize();});this.observer.observe(this.stage);
      this.show(false);
    }
    button(text,fn){const b=node('button','',text);b.type='button';b.onclick=fn;this.toolbar.append(b);return b;}
    go(index){const count=(this.data.geometry.steps||[]).length;this.index=Math.max(-1,Math.min(index,count-1));this.panel.open=true;this.select.value=String(this.index);this.show(true);}
    update(options){this.options={...this.options,...options};this.state=options.state||this.state;this.activeKey=options.activeKey;this.show(false);}
    async show(replay) {
      const g=this.data.geometry||{}, steps=g.steps||[], teaching=!!this.options.teaching;
      this.prev.hidden=this.next.hidden=this.select.hidden=teaching;
      this.prev.disabled=this.index<=-1;this.next.disabled=this.index>=steps.length-1;
      this.status.textContent=g.status==='partial'?'部分支持':g.status==='ready'?'可旋转 / 缩放':g.status==='unavailable'?'暂无可用演示':'';
      const view=viewFor(g,this.state,this.activeKey,this.index,teaching);
      if(!view.scene){this.stage.hidden=true;this.toolbar.hidden=true;this.note.textContent=g.reason||'';return;}
      this.stage.hidden=false;this.replay.disabled=false;
      this.note.textContent=view.text || (teaching?'请求提示时，将逐组画出本步辅助构造。':'点击解析步骤查看辅助构造。');
      if(g.status==='partial'&&g.reason)this.note.textContent+='\n'+g.reason;
      const scene=view.scene, token=++this.version;
      try {
        if(this.sceneId!==scene.id||!this.renderer){
          if(this.sceneId!==scene.id){this.savedCamera=null;clearInterval(this.parameterTimer);this.parameterTimer=null;}
          if(this.renderer)this.renderer.dispose();
          this.renderer=null;this.sceneId=scene.id;this.frame=scene.frames?scene.frames.findIndex(f=>f.value===scene.parameter.value):0;
          this.frame=Math.max(0,this.frame);
          this.parameter.replaceChildren();
          if(scene.frames) {
            const label=node('span','',scene.parameter.name),slider=node('input');slider.type='range';slider.min=0;slider.max=scene.frames.length-1;slider.value=this.frame;
            const value=node('span','',scene.frames[this.frame].value.toFixed(3));
            const apply=()=>{this.frame=Number(slider.value);value.textContent=scene.frames[this.frame].value.toFixed(3);if(this.renderer){this.savedCamera=this.renderer.snapshot?this.renderer.snapshot():null;this.renderer.dispose();}this.renderer=null;const token=++this.version;this.renderFrame(scene,viewFor(this.data.geometry,this.state,this.activeKey,this.index,!!this.options.teaching),false,token).catch(error=>{if(token===this.version&&!this.disposed)this.failed(error);});};
            slider.oninput=()=>{if(this.parameterTimer)clearInterval(this.parameterTimer);apply();};
            const play=node('button','','播放');play.type='button';play.onclick=()=>{if(this.parameterTimer){clearInterval(this.parameterTimer);this.parameterTimer=null;play.textContent='播放';return;}play.textContent='暂停';this.parameterTimer=setInterval(()=>{if(this.disposed)return;slider.value=(Number(slider.value)+1)%scene.frames.length;apply();},140);};
            this.parameter.append(label,slider,value,play);
          }
          this.visible=new Set();
        }
        this.parameter.hidden=!scene.frames;
        if(this.initial){this.visible=new Set(view.visible);this.initial=false;}
        await this.renderFrame(scene,view,replay,token);
      }catch(e){if(token!==this.version||this.disposed)return;this.failed(e);}
    }
    failed(error){clearInterval(this.parameterTimer);this.parameterTimer=null;this.parameter.hidden=true;this.stage.hidden=true;this.replay.disabled=true;this.note.textContent='画板暂不可用：'+error.message+'。文字解析和原题图仍可查看。';}
    async renderFrame(scene,view,replay,token) {
      token=token||++this.version;
      if(!this.renderer){
        const deps=scene.dimension===2?await loadJSX():await loadThree();
        if(token!==this.version||this.disposed)return;
        const objects=scene.frames?scene.frames[this.frame].objects:scene.objects;
        this.renderer=scene.dimension===2?draw2D(this.stage,scene,objects,this.visible,view.highlight,deps):draw3D(this.stage,scene,objects,this.visible,view.highlight,deps[0],deps[1].OrbitControls,this.savedCamera);
        this.renderer.resize();
      }
      if(token!==this.version||this.disposed)return;
      cancelAnimationFrame(this.animation);
      const base=new Set(scene.objects.filter(o=>o.base).map(o=>o.id));
      const start=replay?base:new Set([...this.visible].filter(id=>view.visible.has(id)));
      const added=[...view.visible].filter(id=>!start.has(id));
      this.visible=view.visible;
      // Reveal only newly released objects. Restore never repeats completed work.
      this.renderer.update(start,view.highlight);
      const begin=performance.now(),duration=added.length?Math.min(2400,added.length*300):0;
      const frame=now=>{if(token!==this.version||this.disposed)return;const t=duration?Math.min(1,(now-begin)/duration)*added.length:added.length,n=Math.ceil(t);
        const current=new Set([...start,...added.slice(0,n)]),ratios=new Map();
        if(n>0&&n<=added.length)ratios.set(added[n-1],Math.max(.001,t-(n-1)));
        this.renderer.update(current,view.highlight,ratios);if(t<added.length)this.animation=requestAnimationFrame(frame);};
      this.animation=requestAnimationFrame(frame);
    }
    dispose(){this.disposed=true;++this.version;cancelAnimationFrame(this.animation);clearInterval(this.parameterTimer);this.observer.disconnect();this.root.removeEventListener('click',this.onClick);if(this.renderer)this.renderer.dispose();this.panel.remove();live.delete(this);mounted.delete(this.root);}
  }
  function mount(root,data,options){
    if(!root)return;const previous=mounted.get(root);
    if(previous&&previous.panel.isConnected&&previous.data.geometry===data.geometry){previous.update(options||{});return previous;}
    if(previous)previous.dispose();
    if(!data.geometry&&!(data.asset_refs||[]).some(assetUrl))return;
    const player=new Player(root,data,options);mounted.set(root,player);return player;
  }
  function handoff(question,refs){try{localStorage.setItem('_teach_assets',JSON.stringify({question,asset_refs:refs||[]}));}catch(e){}}
  function teachingAssets(question){try{const d=JSON.parse(localStorage.getItem('_teach_assets')||'null');return d&&d.question===question?d.asset_refs||[]:[];}catch(e){return [];}}
  global.StudyGeometry={mount,images,keyOf,viewFor,assetUrl,handoff,teachingAssets,dispose:root=>{const p=mounted.get(root);if(p)p.dispose();}};
  if(typeof document!=='undefined'){
    let teachPlayer,sessionId;
    document.addEventListener('study:teach-opened',e=>{
      const d=e.detail,ended=d.current_step>=d.total_steps,root=document.getElementById(ended?'teachSummaryGeometry':'teachGeometry');if(!root)return;
      const active=(d.steps||[])[d.current_step];
      if(teachPlayer&&teachPlayer.root===root&&sessionId===d.session_id&&teachPlayer.data.geometry&&d.geometry&&teachPlayer.data.geometry.source_hash===d.geometry.source_hash){
        teachPlayer.update({state:d.geometry_state,activeKey:active?keyOf(active):null,teaching:!ended});if(ended)teachPlayer.go((d.geometry.steps||[]).length-1);
      }else{
        if(teachPlayer)teachPlayer.dispose();
        sessionId=d.session_id;teachPlayer=mount(root,d,{teaching:!ended,state:d.geometry_state,activeKey:active?keyOf(active):null});
        if(ended&&teachPlayer)teachPlayer.go((d.geometry&&d.geometry.steps||[]).length-1);
      }
    });
    document.addEventListener('click',e=>{const b=e.target.closest('[data-question]');if(!b)return;const question=b.getAttribute('data-question');if(!question)return;
      const player=[...live].find(p=>p.root.contains(b));if(player)handoff(question,player.data.asset_refs);
    },true);
    // Rendering a different question/removing a result releases WebGL contexts.
    document.addEventListener('DOMContentLoaded',()=>{
      const observer=new MutationObserver(()=>{live.forEach(p=>{if(!p.panel.isConnected)p.dispose();});});observer.observe(document.body,{childList:true,subtree:true});
    });
  }
})(typeof window!=='undefined'?window:globalThis);
