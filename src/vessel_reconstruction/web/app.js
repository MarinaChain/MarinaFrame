'use strict';

// This workbench renders only geometry and evidence emitted by the pipeline.
// No demonstration hull, fabricated metric or automatic approval is inserted.
const $ = (id) => document.getElementById(id);
const SNAPSHOT = window.__VESSEL_SNAPSHOT__ || null;
let csrfToken = '';
let activeJobId = null;
const state = {runs: [], result: null, runId: null, section: null, image: null, crop: true, loading: 0, sourceId: null, selectedCell: null, imageRequest: 0, inspectionSections: [], localReview: null};
const number = (value, digits = 2) => typeof value === 'number' && Number.isFinite(value)
  ? value.toLocaleString(undefined, {maximumFractionDigits: digits}) : '—';
const percent = (value, digits = 1) => typeof value === 'number' && Number.isFinite(value) ? `${number(value * 100, digits)}%` : '—';
const titleCase = (value) => String(value ?? '').replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());
const assetUrl = (name) => SNAPSHOT ? (SNAPSHOT.assets[String(name)] || '') : `/api/run/${encodeURIComponent(state.runId)}/${String(name).split('/').map(encodeURIComponent).join('/')}`;
const setText = (id, value) => { $(id).textContent = String(value); };

function notify(message, error = false) {
  const element = $('notification');
  element.hidden = !message;
  element.classList.toggle('error', error);
  element.textContent = message || '';
}

async function jsonFetch(url, options) {
  if (SNAPSHOT && url === '/api/runs') return {runs: [{id:'snapshot',name:SNAPSHOT.vessel_id,status:SNAPSHOT.status,has_mesh:!!SNAPSHOT.assets['mesh.json']}]};
  if (!url) throw new Error('This artifact is not included in the portable snapshot');
  const settings = {...(options || {})};
  settings.headers = {...(settings.headers || {})};
  if (settings.method && !['GET', 'HEAD'].includes(settings.method)) settings.headers['X-MarinaFrame-CSRF'] = csrfToken;
  const response = await fetch(url, {...settings, credentials: 'same-origin'});
  let value;
  try { value = await response.json(); } catch (_) { throw new Error(`Unable to read response (${response.status})`); }
  if (!response.ok) throw new Error(value.error || `Request failed (${response.status})`);
  return value;
}

function vectorSubtract(a, b) { return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]; }
function dot(a, b) { return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]; }
function cross(a, b) { return [a[1]*b[2] - a[2]*b[1], a[2]*b[0] - a[0]*b[2], a[0]*b[1] - a[1]*b[0]]; }
function normalize(a) { const n = Math.hypot(...a) || 1; return a.map((v) => v / n); }
function multiply4(a, b) {
  const c = new Float32Array(16);
  for (let col = 0; col < 4; col++) for (let row = 0; row < 4; row++) {
    let sum = 0; for (let k = 0; k < 4; k++) sum += a[k*4+row] * b[col*4+k];
    c[col*4+row] = sum;
  }
  return c;
}
function lookAt(eye, center, up) {
  const z = normalize(vectorSubtract(eye, center));
  const x = normalize(cross(up, z));
  const y = cross(z, x);
  return new Float32Array([x[0], y[0], z[0], 0, x[1], y[1], z[1], 0, x[2], y[2], z[2], 0, -dot(x, eye), -dot(y, eye), -dot(z, eye), 1]);
}
function perspective(fovy, aspect, near, far) {
  const f = 1 / Math.tan(fovy / 2), nf = 1 / (near - far);
  return new Float32Array([f/aspect,0,0,0, 0,f,0,0, 0,0,(far+near)*nf,-1, 0,0,2*far*near*nf,0]);
}
function orthographic(left, right, bottom, top, near, far) {
  return new Float32Array([2/(right-left),0,0,0, 0,2/(top-bottom),0,0, 0,0,-2/(far-near),0, -(right+left)/(right-left),-(top+bottom)/(top-bottom),-(far+near)/(far-near),1]);
}
function transformPoint(matrix, p) {
  const x = p[0], y = p[1], z = p[2];
  const w = matrix[3]*x + matrix[7]*y + matrix[11]*z + matrix[15];
  return [(matrix[0]*x + matrix[4]*y + matrix[8]*z + matrix[12])/w,
          (matrix[1]*x + matrix[5]*y + matrix[9]*z + matrix[13])/w,
          (matrix[2]*x + matrix[6]*y + matrix[10]*z + matrix[14])/w];
}

class MeshViewer {
  constructor(canvas, onSelect) {
    this.canvas = canvas; this.onSelect = onSelect; this.mesh = null; this.sections = [];
    this.selected = null; this.showSections = true; this.yaw = -1.15; this.pitch = 0.40;
    this.view = 'perspective'; this.distance = 10; this.radius = 1; this.center = [0,0,0];
    this.drawQueued = false; this.pointers = new Map(); this.pointerStart = null;
    this.gl = new URLSearchParams(location.search).get('renderer') === 'software' ? null : canvas.getContext('webgl', {antialias: true, alpha: false, preserveDrawingBuffer: true});
    if (this.gl) {
      try { this.initGL(); } catch (error) { console.warn('WebGL setup failed', error); this.gl = null; }
    }
    if (!this.gl) {
      // A different canvas is necessary when a WebGL context was allocated first.
      if (!canvas.getContext('2d')) {
        const replacement = canvas.cloneNode(false); canvas.replaceWith(replacement); this.canvas = replacement;
      }
      this.ctx = this.canvas.getContext('2d');
      setText('viewport-help', 'Drag to orbit · Scroll to zoom · Software rendering');
    }
    this.attach();
    this.resizeObserver = new ResizeObserver(() => this.resize());
    this.resizeObserver.observe(this.canvas.parentElement);
    this.resize();
  }
  initGL() {
    const gl = this.gl;
    const vertex = `attribute vec3 aPosition; attribute vec3 aNormal; uniform mat4 uMatrix; varying vec3 vNormal; void main(){vNormal=aNormal; gl_Position=uMatrix*vec4(aPosition,1.0);}`;
    const fragment = `precision mediump float; varying vec3 vNormal; uniform vec4 uColor; uniform bool uLit; void main(){float l=1.0;if(uLit){vec3 n=normalize(vNormal);l=0.48+0.40*abs(dot(n,normalize(vec3(-0.3,-0.5,0.9))))+0.12*abs(dot(n,normalize(vec3(0.6,0.3,0.4))));}gl_FragColor=vec4(uColor.rgb*l,uColor.a);}`;
    const shader = (type, source) => { const item=gl.createShader(type);gl.shaderSource(item,source);gl.compileShader(item);if(!gl.getShaderParameter(item,gl.COMPILE_STATUS))throw new Error(gl.getShaderInfoLog(item));return item; };
    const program=gl.createProgram();gl.attachShader(program,shader(gl.VERTEX_SHADER,vertex));gl.attachShader(program,shader(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw new Error(gl.getProgramInfoLog(program));
    this.program=program; gl.useProgram(program);
    this.aPosition=gl.getAttribLocation(program,'aPosition');this.aNormal=gl.getAttribLocation(program,'aNormal');
    this.uMatrix=gl.getUniformLocation(program,'uMatrix');this.uColor=gl.getUniformLocation(program,'uColor');this.uLit=gl.getUniformLocation(program,'uLit');
    this.positionBuffer=gl.createBuffer();this.normalBuffer=gl.createBuffer();this.lineBuffer=gl.createBuffer();
    gl.enable(gl.DEPTH_TEST);gl.depthFunc(gl.LEQUAL);gl.disable(gl.CULL_FACE);
    gl.enable(gl.BLEND);gl.blendFunc(gl.SRC_ALPHA,gl.ONE_MINUS_SRC_ALPHA);
  }
  attach() {
    const canvas=this.canvas;
    canvas.addEventListener('pointerdown',(event)=>{
      if (!this.mesh) return;
      canvas.setPointerCapture(event.pointerId);this.pointers.set(event.pointerId,[event.clientX,event.clientY]);
      this.pointerStart={x:event.clientX,y:event.clientY,moved:0};
      if(this.pointers.size===2)this.pinchDistance=this.pointerDistance();
    });
    canvas.addEventListener('pointermove',(event)=>{
      if(!this.pointers.has(event.pointerId))return;
      const previous=this.pointers.get(event.pointerId);this.pointers.set(event.pointerId,[event.clientX,event.clientY]);
      const dx=event.clientX-previous[0],dy=event.clientY-previous[1];
      if(this.pointerStart)this.pointerStart.moved+=Math.abs(dx)+Math.abs(dy);
      if(this.pointers.size===2){const d=this.pointerDistance();if(this.pinchDistance&&d)this.distance*=this.pinchDistance/d;this.pinchDistance=d;}
      else {this.yaw-=dx*.007;this.pitch=Math.max(-1.45,Math.min(1.45,this.pitch+dy*.006));this.view='perspective';this.syncView();}
      this.distance=Math.max(this.radius*.2,Math.min(this.radius*50,this.distance));this.schedule();
    });
    const finish=(event)=>{
      if(this.pointerStart&&this.pointerStart.moved<5&&this.pointers.size===1&&event.type==='pointerup')this.pickSection(event);
      this.pointers.delete(event.pointerId);if(!this.pointers.size)this.pointerStart=null;
    };
    canvas.addEventListener('pointerup',finish);canvas.addEventListener('pointercancel',finish);
    canvas.addEventListener('wheel',(event)=>{if(!this.mesh)return;event.preventDefault();this.distance*=Math.exp(event.deltaY*.001);this.distance=Math.max(this.radius*.2,Math.min(this.radius*50,this.distance));this.schedule();},{passive:false});
    canvas.addEventListener('dblclick',()=>this.fit());
  }
  pointerDistance(){const p=[...this.pointers.values()];return p.length>=2?Math.hypot(p[0][0]-p[1][0],p[0][1]-p[1][1]):0;}
  setModel(mesh, sections) {
    this.mesh=mesh;this.sections=Array.isArray(sections)?sections:[];this.selected=null;
    if(!mesh||!Array.isArray(mesh.vertices)||!Array.isArray(mesh.faces)||!mesh.vertices.length){this.mesh=null;this.schedule();return;}
    if(mesh.vertices.length>500000||mesh.faces.length>600000)throw new Error('Mesh is too large for this review workbench');
    if(mesh.vertices.some(v=>!Array.isArray(v)||v.length<3||v.slice(0,3).some(n=>!Number.isFinite(n))))throw new Error('Mesh contains invalid coordinates');
    const min=[Infinity,Infinity,Infinity],max=[-Infinity,-Infinity,-Infinity];
    for(const v of mesh.vertices)for(let i=0;i<3;i++){min[i]=Math.min(min[i],v[i]);max[i]=Math.max(max[i],v[i]);}
    this.center=min.map((v,i)=>(v+max[i])/2);this.bounds={min,max};this.radius=Math.max(Math.hypot(...max.map((v,i)=>v-min[i]))/2,0.01);
    this.triangles=[];
    const positions=[],normals=[];
    for(const face of mesh.faces){if(face.length<3)continue;for(let i=1;i<face.length-1;i++){
      const ids=[face[0],face[i],face[i+1]];if(ids.some(id=>!Number.isInteger(id)||id<0||id>=mesh.vertices.length))throw new Error('Mesh contains invalid face indices');
      const points=ids.map(id=>mesh.vertices[id]);const normal=normalize(cross(vectorSubtract(points[1],points[0]),vectorSubtract(points[2],points[0])));
      this.triangles.push({points,normal});for(const point of points){positions.push(...point);normals.push(...normal);}
    }}
    if(this.gl){const gl=this.gl;gl.bindBuffer(gl.ARRAY_BUFFER,this.positionBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(positions),gl.STATIC_DRAW);gl.bindBuffer(gl.ARRAY_BUFFER,this.normalBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(normals),gl.STATIC_DRAW);this.vertexCount=positions.length/3;}
    this.sectionPaths=this.sections.map(section=>{
      const points=section.points_yz_m||[];const x=section.x_m;
      return {id:section.id,points:[...points.map(([y,z])=>[x,y,z]),...points.slice().reverse().map(([y,z])=>[x,-y,z])]};
    });
    this.fit();
  }
  fit(){this.distance=this.radius*2.7;this.yaw=-1.15;this.pitch=.40;this.view='perspective';this.syncView();this.schedule();}
  setView(view){this.view=view;if(view==='perspective'){this.yaw=-1.15;this.pitch=.40;}this.syncView();this.schedule();}
  syncView(){document.querySelectorAll('[data-view]').forEach(button=>{const active=button.dataset.view===this.view;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));});setText('view-label',titleCase(this.view));}
  select(id){this.selected=id;this.schedule();}
  resize(){const rect=this.canvas.parentElement.getBoundingClientRect();const dpr=Math.min(devicePixelRatio||1,2);this.width=Math.max(1,rect.width);this.height=Math.max(300,rect.height);this.canvas.width=Math.round(this.width*dpr);this.canvas.height=Math.round(this.height*dpr);this.schedule();}
  matrix(){
    const d=this.distance,center=this.center;let eye,up=[0,0,1];
    if(this.view==='profile')eye=[center[0],center[1]-d,center[2]];
    else if(this.view==='plan'){eye=[center[0],center[1],center[2]+d];up=[0,1,0];}
    else if(this.view==='body')eye=[center[0]+d,center[1],center[2]];
    else eye=[center[0]+d*Math.cos(this.pitch)*Math.cos(this.yaw),center[1]+d*Math.cos(this.pitch)*Math.sin(this.yaw),center[2]+d*Math.sin(this.pitch)];
    const view=lookAt(eye,center,up),aspect=this.width/this.height,near=Math.max(this.radius*.001,.00001),far=this.radius*100;
    let projection;
    if(this.view==='perspective')projection=perspective(Math.PI/4,aspect,near,far);
    else {let height=this.distance*.42;if(this.view==='body')height=Math.max((this.bounds.max[1]-this.bounds.min[1])/aspect,this.bounds.max[2]-this.bounds.min[2])*.68*(this.distance/(this.radius*3));projection=orthographic(-height*aspect,height*aspect,-height,height,near,far);}
    return multiply4(projection,view);
  }
  schedule(){if(this.drawQueued)return;this.drawQueued=true;requestAnimationFrame(()=>{this.drawQueued=false;this.draw();});}
  draw(){if(this.gl)this.drawGL();else this.drawSoftware();}
  lineSegments(points,closed=false){const values=[];for(let i=1;i<points.length;i++)values.push(...points[i-1],...points[i]);if(closed&&points.length>1)values.push(...points[points.length-1],...points[0]);return values;}
  gridLines(){
    const min=this.bounds.min,max=this.bounds.max,size=this.radius*1.25,step=size/8,z=min[2]-this.radius*.055,values=[];
    const cx=this.center[0],cy=this.center[1];
    for(let i=-8;i<=8;i++){values.push(cx+i*step,cy-size,z,cx+i*step,cy+size,z);values.push(cx-size,cy+i*step,z,cx+size,cy+i*step,z);}return values;
  }
  drawGLLines(values,color,width=1,depth=true){
    if(!values.length)return;const gl=this.gl;
    if(depth)gl.enable(gl.DEPTH_TEST);else gl.disable(gl.DEPTH_TEST);
    gl.bindBuffer(gl.ARRAY_BUFFER,this.lineBuffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(values),gl.DYNAMIC_DRAW);gl.vertexAttribPointer(this.aPosition,3,gl.FLOAT,false,0,0);gl.enableVertexAttribArray(this.aPosition);gl.disableVertexAttribArray(this.aNormal);gl.vertexAttrib3f(this.aNormal,0,0,1);gl.uniform4fv(this.uColor,color);gl.uniform1i(this.uLit,0);gl.lineWidth(width);gl.drawArrays(gl.LINES,0,values.length/3);
  }
  drawGL(){
    const gl=this.gl;gl.viewport(0,0,this.canvas.width,this.canvas.height);gl.clearColor(.043,.133,.196,1);gl.clear(gl.COLOR_BUFFER_BIT|gl.DEPTH_BUFFER_BIT);
    if(!this.mesh)return;gl.useProgram(this.program);gl.uniformMatrix4fv(this.uMatrix,false,this.matrix());
    this.drawGLLines(this.gridLines(),[.20,.34,.40,.40]);
    gl.enable(gl.DEPTH_TEST);gl.enable(gl.POLYGON_OFFSET_FILL);gl.polygonOffset(1,1);
    gl.bindBuffer(gl.ARRAY_BUFFER,this.positionBuffer);gl.vertexAttribPointer(this.aPosition,3,gl.FLOAT,false,0,0);gl.enableVertexAttribArray(this.aPosition);
    gl.bindBuffer(gl.ARRAY_BUFFER,this.normalBuffer);gl.vertexAttribPointer(this.aNormal,3,gl.FLOAT,false,0,0);gl.enableVertexAttribArray(this.aNormal);
    gl.uniform4fv(this.uColor,[.40,.77,.69,1]);gl.uniform1i(this.uLit,1);gl.drawArrays(gl.TRIANGLES,0,this.vertexCount);gl.disable(gl.POLYGON_OFFSET_FILL);
    if(this.showSections){const all=[];for(const section of this.sectionPaths)if(section.id!==this.selected)all.push(...this.lineSegments(section.points,true));this.drawGLLines(all,[.12,.35,.36,.62]);}
    const selected=this.sectionPaths.find(section=>section.id===this.selected);if(selected)this.drawGLLines(this.lineSegments(selected.points,true),[1,.77,.42,1],2,false);
    gl.enable(gl.DEPTH_TEST);
  }
  project(point,matrix){const p=transformPoint(matrix,point);return [(p[0]+1)*.5*this.width,(1-p[1])*.5*this.height,p[2]];}
  drawSoftware(){
    const ctx=this.ctx;if(!ctx)return;const ratio=this.canvas.width/this.width;ctx.setTransform(ratio,0,0,ratio,0,0);ctx.fillStyle='#0b2232';ctx.fillRect(0,0,this.width,this.height);if(!this.mesh)return;
    const matrix=this.matrix();const drawLine=(points,color,width,closed=false)=>{if(!points.length)return;ctx.beginPath();points.forEach((p,i)=>{const q=this.project(p,matrix);if(i===0)ctx.moveTo(q[0],q[1]);else ctx.lineTo(q[0],q[1]);});if(closed)ctx.closePath();ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();};
    const grid=this.gridLines();for(let i=0;i<grid.length;i+=6)drawLine([grid.slice(i,i+3),grid.slice(i+3,i+6)],'#24404f',.6);
    const light=normalize([-.3,-.5,.9]);
    const faces=this.triangles.map(triangle=>({triangle,points:triangle.points.map(p=>this.project(p,matrix))}));
    faces.sort((a,b)=>(b.points[0][2]+b.points[1][2]+b.points[2][2])-(a.points[0][2]+a.points[1][2]+a.points[2][2]));
    for(const face of faces){const l=.5+.5*Math.abs(dot(face.triangle.normal,light));ctx.beginPath();face.points.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle=`rgb(${Math.round(102*l)},${Math.round(196*l)},${Math.round(176*l)})`;ctx.strokeStyle=ctx.fillStyle;ctx.lineWidth=.3;ctx.fill();ctx.stroke();}
    if(this.showSections)for(const section of this.sectionPaths)if(section.id!==this.selected)drawLine(section.points,'#376e70',.7,true);
    const selected=this.sectionPaths.find(section=>section.id===this.selected);if(selected)drawLine(selected.points,'#ffc46b',1.8,true);
  }
  pickSection(event){
    if(!this.mesh||!this.sectionPaths.length)return;const rect=this.canvas.getBoundingClientRect(),mouse=[event.clientX-rect.left,event.clientY-rect.top],matrix=this.matrix();let nearest=null,best=14;
    for(const section of this.sectionPaths){const points=section.points.map(p=>this.project(p,matrix));for(let i=1;i<points.length;i++){
      const a=points[i-1],b=points[i],dx=b[0]-a[0],dy=b[1]-a[1],length=dx*dx+dy*dy;
      const t=length?Math.max(0,Math.min(1,((mouse[0]-a[0])*dx+(mouse[1]-a[1])*dy)/length)):0;
      const distance=Math.hypot(mouse[0]-a[0]-t*dx,mouse[1]-a[1]-t*dy);if(distance<best){best=distance;nearest=section.id;}
    }}if(nearest)this.onSelect(nearest);
  }
}

const viewer = new MeshViewer($('model-canvas'), (id) => selectSection(id));

async function refreshRuns(preferredId = null) {
  try {
    const data=await jsonFetch('/api/runs');state.runs=data.runs||[];
    const select=$('run-select');select.replaceChildren();
    if(!state.runs.length){const option=document.createElement('option');option.textContent='No saved reconstructions';select.append(option);select.disabled=true;return;}
    select.disabled=false;
    for(const run of state.runs){const option=document.createElement('option');option.value=run.id;option.textContent=`${run.name}${run.status==='blocked'?' · blocked':''}`;select.append(option);}
    const selected=preferredId&&state.runs.some(r=>r.id===preferredId)?preferredId:state.runId&&state.runs.some(r=>r.id===state.runId)?state.runId:(state.runs.find(run=>run.has_mesh)||state.runs[0]).id;
    select.value=selected;await loadRun(selected);
  } catch(error) { notify(error.message,true); }
}

async function loadRun(id) {
  const load=++state.loading;notify('');state.runId=id;state.image=null;
  viewer.setModel(null,[]);$('viewport-empty').hidden=false;
  $('viewport-empty').querySelector('h3').textContent='Loading verified reconstruction';
  $('viewport-empty').querySelector('p').textContent='Loading the model and its source evidence…';
  try{
    const result=await jsonFetch(assetUrl('result.json'));if(load!==state.loading)return;
    state.result=result;state.section=null;state.selectedCell=null;
    let replay={};try{replay=await jsonFetch(assetUrl('replay_spec.json'));}catch(_){/* Observations remain inspectable without optional replay UI. */}
    if(load!==state.loading)return;
    const observed=new Map((result.sections||[]).map(section=>[section.id,section]));
    state.inspectionSections=Array.isArray(replay?.sections)?replay.sections.filter(section=>section&&typeof section.id==='string').map(section=>observed.get(section.id)||{id:section.id,x_m:section.x_m,unresolved:true,evidence:{roi_px:section.roi_px,calibration:section.calibration,contour_selection:section.contour_selection,source_id:result.sources?.[0]?.id},warnings:[]}):(result.sections||[]);
    try{state.localReview=SNAPSHOT?SNAPSHOT.review_state:await jsonFetch(`/api/review/${encodeURIComponent(id)}`);}catch(_){state.localReview={state:'unavailable'};}
    if(load!==state.loading)return;
    renderSummary(result);renderInventory(result);renderIssues(result);
    const exports=result.exports||{};setDownload('download-step',exports.step);setDownload('download-stl',exports.stl);setDownload('download-result','result.json');
    setDownload('download-replay','replay_spec.json');
    const sources=result.sources||[],sourceSelect=$('evidence-source-select');sourceSelect.replaceChildren();sourceSelect.hidden=sources.length<2;
    for(const source of sources){const option=document.createElement('option');option.value=source.id;option.textContent=titleCase(source.role||source.id);sourceSelect.append(option);}
    loadSource(sources[0]?.id);
    let mesh=null;
    if(exports.mesh){try{mesh=await jsonFetch(assetUrl(exports.mesh));}catch(error){notify(`Geometry could not be displayed: ${error.message}`,true);}}
    if(load!==state.loading)return;
    viewer.setModel(mesh,result.sections||[]);
    const empty=$('viewport-empty');empty.hidden=!!mesh;
    if(!mesh){empty.querySelector('h3').textContent=result.status==='blocked'?'Reconstruction blocked':'No 3D geometry available';empty.querySelector('p').textContent=result.status==='blocked'?'Missing or inconsistent evidence must be resolved before a solid can be built.':'Inspect the source evidence and open questions below.';}
    const sections=state.inspectionSections;if(sections.length)selectSection(sections[Math.floor(sections.length/2)].id);else renderEvidence(null);
  }catch(error){notify(`Unable to open reconstruction: ${error.message}`,true);}
}

function currentSource(){return (state.result?.sources||[]).find(source=>source.id===state.sourceId)||(state.result?.sources||[])[0];}
function loadSource(id){state.sourceId=id;state.image=null;const source=currentSource(),request=++state.imageRequest;$('evidence-source-select').value=id||'';$('source-placeholder').textContent='Loading source evidence…';if(source&&source.file&&assetUrl(source.preview_file||source.file)){const image=new Image();image.onload=()=>{if(request===state.imageRequest){state.image=image;drawSource();}};image.onerror=()=>{if(request===state.imageRequest){$('source-placeholder').hidden=false;$('source-placeholder').textContent='Source preview unavailable. Download the original for inspection.';}};image.src=assetUrl(source.preview_file||source.file);setDownload('source-download',source.file);}else{setDownload('source-download',null);$('source-placeholder').textContent='No display preview is included.';}setText('evidence-hash',source?.sha256?`${source.sha256.slice(0,16)}…`:'—');$('evidence-hash').title=source?.sha256||'';drawSource();}
$('evidence-source-select').addEventListener('change',event=>loadSource(event.target.value));

function setDownload(id,file){const link=$(id);const url=file?assetUrl(file):'';link.hidden=!url;if(url){link.href=url;link.download=String(file).split('/').pop();}else link.removeAttribute('href');}
function renderSummary(result){
  const m=result.metrics||{};setText('metric-volume',number(m.volume_m3,m.volume_m3<1?4:2));
  setText('metric-dimensions',[m.length_m,m.beam_m,m.depth_m].every(Number.isFinite)?`${number(m.length_m)} × ${number(m.beam_m)} × ${number(m.depth_m)}`:'—');
  const sections=result.sections||[];setText('metric-sections',sections.length);
  const scores=sections.map(s=>s.confidence).filter(Number.isFinite);setText('metric-quality',scores.length?`Mean heuristic quality ${percent(scores.reduce((a,b)=>a+b,0)/scores.length)}`:'No section quality observations');
  setText('metric-review',result.status==='review_required'?'Review required':titleCase(result.status));
  setText('model-title',result.vessel_id||'Hull envelope');
  const badge=$('status-badge');badge.textContent=result.status==='review_required'?'Engineer review required':titleCase(result.status);badge.classList.toggle('blocked',result.status!=='review_required');
  setText('local-review-state',`Local review: ${titleCase(state.localReview?.state||'unreviewed')}. Reviewer identity is unverified; engineering approval remains absent.`);
  const approximation=m.geometry_approximation;
  setText('cad-deviation',Number.isFinite(approximation?.maximum_half_breadth_deviation_m)?`${number(approximation.maximum_half_breadth_deviation_m*1000,3)} mm / ${number(approximation.maximum_allowed_half_breadth_deviation_m*1000,3)} mm limit`:'Not measured');
  setText('cad-valid',m.cad_valid===true?'Valid solid':m.cad_valid===false?'Invalid':'Not generated');
  setText('step-error',Number.isFinite(m.step_roundtrip_relative_error)?percent(m.step_roundtrip_relative_error,5):'Not measured');
  setText('run-time',Number.isFinite(result.timing_seconds)?`${number(result.timing_seconds,2)} s`:'—');
}
function renderInventory(result){
  const parts=result.parts||[];setText('part-count',`${parts.length} part${parts.length===1?'':'s'}`);const partList=$('part-list');partList.replaceChildren();
  for(const part of parts){const row=document.createElement('button');row.className='part-item';row.type='button';const icon=document.createElement('span');icon.className='part-icon';icon.textContent='◇';const content=document.createElement('span');const name=document.createElement('span');name.className='part-name';name.textContent=part.name||part.id;const kind=document.createElement('span');kind.className='part-kind';kind.textContent=titleCase(part.kind||'reconstructed geometry');content.append(name,kind);row.append(icon,content);row.addEventListener('click',()=>viewer.fit());partList.append(row);}
  if(!parts.length){const p=document.createElement('p');p.className='muted small';p.style.padding='8px';p.textContent='No geometry accepted for reconstruction.';partList.append(p);}
  const sections=state.inspectionSections;setText('section-count',sections.length);const list=$('section-list');list.replaceChildren();
  for(const section of sections){const button=document.createElement('button');button.className='section-button';button.type='button';button.dataset.section=section.id;button.setAttribute('aria-pressed','false');const dot=document.createElement('span');dot.className='section-dot';dot.setAttribute('aria-hidden','true');const name=document.createElement('span');name.textContent=section.id;const position=document.createElement('small');position.textContent=`${number(section.x_m)} m`;button.append(dot,name,position);button.addEventListener('click',()=>selectSection(section.id));list.append(button);}
}
function selectSection(id){
  const section=state.inspectionSections.find(item=>item.id===id);if(!section)return;state.section=section;state.selectedCell=null;if(section.evidence?.source_id&&state.sourceId!==section.evidence.source_id)loadSource(section.evidence.source_id);viewer.select(id);
  document.querySelectorAll('[data-section]').forEach(button=>{const active=button.dataset.section===id;button.classList.toggle('selected',active);button.setAttribute('aria-pressed',String(active));if(active){const list=$('section-list'),a=button.getBoundingClientRect(),b=list.getBoundingClientRect();if(a.top<b.top)list.scrollTop-=b.top-a.top;else if(a.bottom>b.bottom)list.scrollTop+=a.bottom-b.bottom;}});renderEvidence(section);
}
function renderEvidence(section){
  setText('evidence-section-id',section?section.id:'SOURCE DOCUMENT');setText('evidence-position',section?`Station at x = ${number(section.x_m)} m`:'No extracted section');
  setText('evidence-coverage',percent(section?.coverage));setText('evidence-confidence',percent(section?.confidence));
  const calibration=section?.evidence?.calibration||{};
  setText('evidence-calibration',Number.isFinite(calibration.pixels_per_metre)?`${number(calibration.pixels_per_metre)} px/m`:section?.evidence?.table_value_units?'Table units declared':'Not available');
  const source=currentSource();setText('evidence-hash',source?.sha256?`${source.sha256.slice(0,16)}…`:'—');$('evidence-hash').title=source?.sha256||'';
  const warnings=$('section-warnings');warnings.replaceChildren();const messages=section?.warnings||[];if(messages.length){const detail=document.createElement('details');detail.className='extraction-notes';const summary=document.createElement('summary');summary.textContent=`${messages.length} extraction notes`;detail.append(summary);for(const warning of messages){const p=document.createElement('p');p.textContent=typeof warning==='string'?warning:warning.message||JSON.stringify(warning);detail.append(p);}warnings.append(detail);}renderTableObservations(section);drawSource();
  const diagnostic=state.result?.diagnostics?.sections?.[section?.id];
  if(diagnostic){const p=document.createElement('p');p.className='small';p.textContent=`Contour identity: ${titleCase(diagnostic.identity_status||diagnostic.status)}. ${section?.unresolved?'This station has no accepted observations. ':''}Orange numbered dots mark competing source samples; dashed blue marks an explicit selection corridor. Neither overlay is an accepted hull.`;warnings.prepend(p);}
}
function drawSource(){
  const canvas=$('source-canvas'),container=$('source-image-container'),ctx=canvas.getContext('2d'),rect=container.getBoundingClientRect(),ratio=Math.min(devicePixelRatio||1,2);
  canvas.width=Math.round(rect.width*ratio);canvas.height=Math.round(rect.height*ratio);ctx.setTransform(ratio,0,0,ratio,0,0);ctx.fillStyle='#fafbf9';ctx.fillRect(0,0,rect.width,rect.height);
  $('source-placeholder').hidden=!!state.image;if(!state.image)return;
  let sourceRect=[0,0,state.image.naturalWidth,state.image.naturalHeight];const source=currentSource(),sx=Number(source?.preview_scale_x)||1,sy=Number(source?.preview_scale_y)||1;const primary=source?.id===(state.section?.evidence?.source_id||state.result?.sources?.[0]?.id);const rawRoi=primary?(state.selectedCell?.roi_px||state.section?.evidence?.roi_px):source?.roi_px;const roi=Array.isArray(rawRoi)?rawRoi.map((v,i)=>v*(i%2===0?sx:sy)):null;
  if(state.crop&&Array.isArray(roi)&&roi.length===4){const padding=Math.max(8,(roi[2]-roi[0])*.05);sourceRect=[Math.max(0,roi[0]-padding),Math.max(0,roi[1]-padding),Math.min(state.image.naturalWidth,roi[2]+padding),Math.min(state.image.naturalHeight,roi[3]+padding)];}
  const sw=sourceRect[2]-sourceRect[0],sh=sourceRect[3]-sourceRect[1];if(sw<=0||sh<=0)return;
  const scale=Math.min((rect.width-16)/sw,(rect.height-16)/sh),dw=sw*scale,dh=sh*scale,dx=(rect.width-dw)/2,dy=(rect.height-dh)/2;
  ctx.drawImage(state.image,sourceRect[0],sourceRect[1],sw,sh,dx,dy,dw,dh);
  if(roi){ctx.strokeStyle='#bd8740';ctx.lineWidth=1.5;ctx.setLineDash([4,3]);ctx.strokeRect(dx+(roi[0]-sourceRect[0])*scale,dy+(roi[1]-sourceRect[1])*scale,(roi[2]-roi[0])*scale,(roi[3]-roi[1])*scale);ctx.setLineDash([]);}
  // Overlay recovered points using the declared global pixel calibration.
  const calibration=state.section?.evidence?.calibration;
  if(primary&&state.crop&&calibration&&state.section?.points_yz_m){const ppm=calibration.pixels_per_metre;if(Number.isFinite(ppm)){ctx.beginPath();state.section.points_yz_m.forEach(([y,z],i)=>{const px=(calibration.centerline_px+y*ppm)*sx,py=(calibration.baseline_px-z*ppm)*sy;const x=dx+(px-sourceRect[0])*scale,yy=dy+(py-sourceRect[1])*scale;i?ctx.lineTo(x,yy):ctx.moveTo(x,yy);});ctx.strokeStyle='#16867bc4';ctx.lineWidth=1.5;ctx.stroke();}}
  if(primary&&state.section){
    const project=([x,y])=>[dx+(x*sx-sourceRect[0])*scale,dy+(y*sy-sourceRect[1])*scale];
    const diagnostic=state.result?.diagnostics?.sections?.[state.section.id];
    (diagnostic?.candidate_evidence||[]).forEach((candidate,index)=>{ctx.fillStyle='#ad5109';ctx.font='bold 11px sans-serif';(candidate.source_points_px||[]).forEach((point,i)=>{const [x,y]=project(point);ctx.beginPath();ctx.arc(x,y,1.5,0,Math.PI*2);ctx.fill();if(i===0)ctx.fillText(`C${index+1}`,x+4,y+11);});});
    const selection=state.section.evidence?.contour_selection;
    if(selection?.anchors_px?.length){ctx.strokeStyle='#275fa8';ctx.lineWidth=1.5;ctx.setLineDash([5,4]);for(const sign of [-1,1]){ctx.beginPath();selection.anchors_px.forEach(([x,y],i)=>{const p=project([x+sign*selection.half_width_px,y]);i?ctx.lineTo(...p):ctx.moveTo(...p);});ctx.stroke();}ctx.setLineDash([]);}
  }
}
function renderTableObservations(section){
  const cells=section?.evidence?.cell_evidence||section?.evidence?.cells||[],panel=$('table-observations'),rows=$('table-observation-rows');panel.hidden=!cells.length;rows.replaceChildren();setText('evidence-coverage-label',cells.length?'Observation coverage':'Curve coverage');setText('evidence-confidence-label',cells.length?'OCR confidence score':'Quality score');setText('evidence-calibration-label',cells.length?'Measurement notation':'Pixel calibration');
  document.querySelector('.score-explanation').textContent=cells.length?'OCR confidence is a recognizer heuristic, not a probability of correct dimensions. Cell positions and row elevations are supplied by the operator.':'Quality is a heuristic, not a probability of correctness. Regions and scale are supplied by the operator.';
  for(const cell of cells){const row=document.createElement('tr');row.classList.toggle('selected',state.selectedCell===cell);const z=document.createElement('td');z.textContent=number(cell.z_m,3);const text=document.createElement('td'),button=document.createElement('button');button.type='button';const values=Array.isArray(cell.raw_ocr)?[...new Set(cell.raw_ocr)]:[cell.raw_ocr||cell.source_token||'Unresolved'];button.textContent=values.join(' / ');button.setAttribute('aria-label',`Inspect source cell at z ${number(cell.z_m,3)} metres, recognized ${button.textContent}`);button.addEventListener('click',()=>{state.selectedCell=cell;state.crop=true;$('crop-source').classList.add('active');$('crop-source').setAttribute('aria-pressed','true');$('full-source').classList.remove('active');$('full-source').setAttribute('aria-pressed','false');if(section.evidence?.source_id&&state.sourceId!==section.evidence.source_id)loadSource(section.evidence.source_id);renderTableObservations(section);drawSource();});text.append(button);const y=document.createElement('td');y.textContent=number(cell.parsed_value_m,4);row.append(z,text,y);rows.append(row);}
}
new ResizeObserver(()=>drawSource()).observe($('source-image-container'));
function renderIssues(result){
  const gaps=(result.gaps||[]).map(gap=>({title:titleCase(gap.kind||gap.id||'Evidence gap'),message:gap.message||gap.description||'',severity:gap.severity||'review'}));
  const assumptions=Array.isArray(result.assumptions)?result.assumptions:Object.entries(result.assumptions||{}).map(([key,value])=>({kind:key,message:value}));
  const items=[...gaps,...assumptions.map((item,index)=>typeof item==='string'?{title:`Model assumption ${index+1}`,message:item,severity:'assumption'}:{title:titleCase(item.kind||item.id||item.name||'Model assumption'),message:item.message||item.description||item.statement||JSON.stringify(item),severity:'assumption'})];
  setText('issue-count',`${gaps.length} gap${gaps.length===1?'':'s'} · ${assumptions.length} assumption${assumptions.length===1?'':'s'}`);
  const list=$('issue-list');list.replaceChildren();
  for(const item of items){const row=document.createElement('div');row.className=`issue${item.severity==='blocking'?' blocking':''}`;const symbol=document.createElement('span');symbol.className='issue-symbol';symbol.textContent=item.severity==='blocking'?'!':'i';symbol.setAttribute('aria-hidden','true');const content=document.createElement('div');const title=document.createElement('strong');title.textContent=item.title;const body=document.createElement('p');body.textContent=item.message;content.append(title,body);row.append(symbol,content);list.append(row);}
  if(!items.length){const p=document.createElement('p');p.className='muted';p.textContent='No gaps were emitted by the pipeline. Engineering review is still required.';list.append(p);}
}

$('run-select').addEventListener('change',event=>loadRun(event.target.value));
$('refresh-runs').addEventListener('click',()=>refreshRuns());
$('fit-model').addEventListener('click',()=>viewer.fit());
$('show-sections').addEventListener('change',event=>{viewer.showSections=event.target.checked;viewer.schedule();});
for(const button of document.querySelectorAll('[data-view]'))button.addEventListener('click',()=>viewer.setView(button.dataset.view));
for(const [id,crop] of [['crop-source',true],['full-source',false]])$(id).addEventListener('click',()=>{state.crop=crop;for(const key of ['crop-source','full-source']){$(key).classList.toggle('active',key===id);$(key).setAttribute('aria-pressed',String(key===id));}drawSource();});

const dialog=$('upload-dialog');
$('new-reconstruction').addEventListener('click',()=>{ $('upload-status').hidden=true;dialog.showModal(); });
$('close-dialog').addEventListener('click',()=>dialog.close());
$('cancel-upload').addEventListener('click',async()=>{
  if(!activeJobId){dialog.close();return;}
  try{await jsonFetch(`/api/jobs/${activeJobId}/cancel`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});uploadStatus('Cancellation requested. Waiting for the isolated worker to stop…');}
  catch(error){uploadStatus(error.message,true);}
});
function uploadStatus(message,error=false){const element=$('upload-status');element.hidden=false;element.classList.toggle('error',error);element.textContent=message;}
async function sourceDescriptor(file){const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());return {bytes:file.size,sha256:Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('')};}
async function pollJob(id){
  for(;;){
    const job=await jsonFetch(`/api/jobs/${encodeURIComponent(id)}`);
    if(['succeeded','blocked'].includes(job.state)){uploadStatus(job.state==='blocked'?'Evidence gaps detected. Opening the blocked run for inspection.':'Reconstruction complete. Opening the evidence workbench.');await refreshRuns(job.run_id);dialog.close();notify(job.state==='blocked'?'Reconstruction was blocked by incomplete or inconsistent evidence. Inspect the open questions below.':'Drawing reconstructed. Engineering review remains required.',job.state==='blocked');return;}
    if(['failed','cancelled','timed_out','resource_limited','interrupted'].includes(job.state))throw new Error(`${titleCase(job.state)}: ${titleCase(job.error_code || 'The job did not publish a successful model')}. You can correct the input and submit a new job.`);
    uploadStatus(job.state==='queued'?'Queued for reconstruction…':'Extracting curves, reconstructing CAD and checking evidence within the local worker budget…');
    await new Promise(resolve=>setTimeout(resolve,700));
  }
}
$('upload-form').addEventListener('submit',async event=>{
  event.preventDefault();const drawing=$('drawing-file').files[0],specFile=$('spec-file').files[0];if(!drawing||(!calibration.active&&!specFile))return;
  const submit=$('submit-upload');submit.disabled=true;
  try{
    if(drawing.size>20*1024*1024)throw new Error('Please use a drawing smaller than 20 MiB');if(specFile&&specFile.size>2*1024*1024)throw new Error('Specification must be smaller than 2 MiB');
    const spec=calibration.active?calibration.spec():JSON.parse(await specFile.text());if(!Array.isArray(spec.sections)||!spec.sections.length)throw new Error('The specification must contain section regions and calibration');
    const files={primary:drawing};
    if(spec.station_reference){const reference=$('reference-file').files[0];if(!reference)throw new Error('Upload the supporting station-reference document required by this specification.');if(reference.size>12*1024*1024)throw new Error('The supporting reference must be smaller than 12 MiB.');files.reference=reference;}
    uploadStatus('Checking source hashes and reserving local queue capacity…');
    const sources={};for(const [role,file] of Object.entries(files))sources[role]=await sourceDescriptor(file);
    const job=await jsonFetch('/api/uploads',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':crypto.randomUUID()},body:JSON.stringify({spec,sources})});activeJobId=job.id;$('cancel-upload').textContent='Cancel job';
    for(const [role,file] of Object.entries(files)){uploadStatus(`Uploading ${role==='primary'?'drawing':'station reference'}…`);await jsonFetch(`/api/jobs/${job.id}/sources/${role}`,{method:'PUT',headers:{'Content-Type':'application/octet-stream'},body:file});}
    await jsonFetch(`/api/jobs/${job.id}/submit`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});await pollJob(job.id);
  }catch(error){uploadStatus(error.message,true);}finally{submit.disabled=false;activeJobId=null;$('cancel-upload').textContent='Cancel';}
});


class CalibrationEditor {
  constructor(){
    this.active=false;this.image=null;this.sections=[];this.editIndex=null;this.roi=null;this.origin=null;this.scaleLine=null;
    this.tool='region';this.zoom=1;this.pan=[0,0];this.pointer=null;this.canvas=$('calibration-canvas');this.ctx=this.canvas.getContext('2d');
    this.canvas.addEventListener('pointerdown',(event)=>this.down(event));
    this.canvas.addEventListener('pointermove',(event)=>this.move(event));
    this.canvas.addEventListener('pointerup',(event)=>this.up(event));
    this.canvas.addEventListener('pointercancel',()=>{this.pointer=null;});
    new ResizeObserver(()=>this.draw()).observe($('calibration-viewport'));
    for(const button of document.querySelectorAll('[data-calibration-tool]'))button.addEventListener('click',()=>this.setTool(button.dataset.calibrationTool));
    $('calibration-zoom').addEventListener('input',(event)=>{this.zoom=Number(event.target.value);this.draw();});
    $('calibration-fit').addEventListener('click',()=>{this.zoom=1;this.pan=[0,0];$('calibration-zoom').value='1';this.draw();});
    $('calibration-reference').addEventListener('input',()=>this.measure());
    $('calibration-add').addEventListener('click',()=>this.add());
    $('calibration-new').addEventListener('click',()=>this.resetSelection());
    $('calibration-download').addEventListener('click',()=>{try{const spec=this.spec();const blob=new Blob([JSON.stringify(spec,null,2)],{type:'application/json'});const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='calibration-spec.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch(error){this.feedback(error.message,true);}});
    $('drawing-file').addEventListener('change',()=>this.loadImage());
    $('mode-json').addEventListener('click',()=>this.mode(false));
    $('mode-editor').addEventListener('click',()=>this.mode(true));
  }
  async mode(active){
    this.active=active;dialog.classList.toggle('editor-open',active);$('calibration-editor').hidden=!active;$('spec-file-field').hidden=active;$('spec-file').required=!active;
    for(const [id,value] of [['mode-json',!active],['mode-editor',active]]){$(id).classList.toggle('active',value);$(id).setAttribute('aria-pressed',String(value));}
    updateReferenceField();
    if(active&&!this.image&&$('drawing-file').files[0])await this.loadImage();
    if(active&&this.sections.length===0&&$('spec-file').files[0]){
      try{const spec=JSON.parse(await $('spec-file').files[0].text());if(Array.isArray(spec.sections)){this.sections=spec.sections.filter(s=>Array.isArray(s.roi_px)&&s.calibration).map(s=>JSON.parse(JSON.stringify(s)));$('calibration-vessel').value=spec.vessel_id||'Uploaded vessel';$('calibration-symmetry').checked=spec.symmetry==='port_starboard';this.renderList();this.feedback(`Imported ${this.sections.length} section calibrations. Confirm that they belong to this image.`);}}
      catch(error){this.feedback(`Could not import the existing calibration: ${error.message}`,true);}
    }
    requestAnimationFrame(()=>this.draw());
  }
  async loadImage(){
    const file=$('drawing-file').files[0];if(!file)return;
    if(this.objectUrl)URL.revokeObjectURL(this.objectUrl);
    this.objectUrl=URL.createObjectURL(file);const image=new Image();
    try{await new Promise((resolve,reject)=>{image.onload=resolve;image.onerror=()=>reject(new Error('This browser cannot preview that image. Use PNG or JPEG for interactive calibration.'));image.src=this.objectUrl;});
      this.image=image;this.sections=[];this.zoom=1;this.pan=[0,0];$('calibration-zoom').value='1';this.resetSelection();this.renderList();this.draw();
    }catch(error){this.image=null;this.feedback(error.message,true);this.draw();}
  }
  setTool(tool){this.tool=tool;for(const button of document.querySelectorAll('[data-calibration-tool]')){const active=button.dataset.calibrationTool===tool;button.classList.toggle('active',active);button.setAttribute('aria-pressed',String(active));}this.canvas.style.cursor=tool==='pan'?'grab':'crosshair';}
  transform(){
    const rect=this.canvas.getBoundingClientRect(),width=rect.width,height=rect.height;
    const scale=this.image?Math.min(width/this.image.naturalWidth,height/this.image.naturalHeight)*.96*this.zoom:1;
    return {width,height,scale,x:(width-(this.image?.naturalWidth||0)*scale)/2+this.pan[0],y:(height-(this.image?.naturalHeight||0)*scale)/2+this.pan[1]};
  }
  point(event){const t=this.transform(),rect=this.canvas.getBoundingClientRect();return [Math.max(0,Math.min(this.image.naturalWidth,(event.clientX-rect.left-t.x)/t.scale)),Math.max(0,Math.min(this.image.naturalHeight,(event.clientY-rect.top-t.y)/t.scale))];}
  down(event){
    if(!this.image)return;event.preventDefault();this.canvas.setPointerCapture(event.pointerId);
    const point=this.point(event);this.pointer={id:event.pointerId,start:point,screen:[event.clientX,event.clientY],pan:this.pan.slice(),tool:this.tool};
    if(this.tool==='origin'){this.origin=point.map(Math.round);this.readout();this.draw();}
    if(this.tool==='region')this.roi=[...point,...point];
    if(this.tool==='scale')this.scaleLine=[point,point];
  }
  move(event){
    if(!this.pointer||this.pointer.id!==event.pointerId)return;
    const point=this.point(event),start=this.pointer.start;
    if(this.pointer.tool==='pan'){this.pan=[this.pointer.pan[0]+event.clientX-this.pointer.screen[0],this.pointer.pan[1]+event.clientY-this.pointer.screen[1]];}
    else if(this.pointer.tool==='region'){this.roi=[Math.round(Math.min(point[0],start[0])),Math.round(Math.min(point[1],start[1])),Math.round(Math.max(point[0],start[0])),Math.round(Math.max(point[1],start[1]))];}
    else if(this.pointer.tool==='origin')this.origin=point.map(Math.round);
    else if(this.pointer.tool==='scale'){this.scaleLine=[start,point];this.measure();}
    this.readout();this.draw();
  }
  up(event){
    if(!this.pointer||this.pointer.id!==event.pointerId)return;this.move(event);const tool=this.pointer.tool;this.pointer=null;
    if(tool==='region'&&this.roi&&this.roi[2]-this.roi[0]>5){this.feedback('Region selected. Mark the intersection of the centreline and baseline.');this.setTool('origin');}
    else if(tool==='origin'){this.feedback('Origin recorded. Enter pixels/metre or drag a known distance with Measure scale.');}
    else if(tool==='scale'){this.feedback('Scale measured. Set the station coordinate and vertical range, then add the section.');}
  }
  measure(){if(!this.scaleLine)return;const [a,b]=this.scaleLine,metres=Number($('calibration-reference').value),pixels=Math.hypot(b[0]-a[0],b[1]-a[1]);if(metres>0&&pixels>1)$('calibration-ppm').value=String(Number((pixels/metres).toFixed(6)));this.draw();}
  feedback(message,error=false){const item=$('calibration-feedback');item.textContent=message;item.classList.toggle('error',error);}
  readout(){setText('calibration-region-readout',this.roi?`Region: [${this.roi.join(', ')}] px`:'Region: not selected');setText('calibration-origin-readout',this.origin?`Origin: ${this.origin[0]}, ${this.origin[1]} px`:'Origin: not selected');}
  numeric(id,label){const raw=$(id).value.trim();const value=Number(raw);if(!raw||!Number.isFinite(value))throw new Error(`Enter ${label}.`);return value;}
  add(){
    try{
      if(!this.image)throw new Error('Select a drawing image first.');
      if(!this.roi||this.roi[2]-this.roi[0]<6||this.roi[3]-this.roi[1]<6)throw new Error('Draw a region around one half-section contour.');
      if(!this.origin)throw new Error('Mark the centreline/baseline origin with the Origin tool.');
      const id=$('calibration-id').value.trim(),x=this.numeric('calibration-x','the longitudinal station coordinate'),zmin=this.numeric('calibration-zmin','the bottom z coordinate'),zmax=this.numeric('calibration-zmax','the top z coordinate'),ppm=this.numeric('calibration-ppm','a positive pixel scale');
      if(!id)throw new Error('Enter a section identifier.');if(ppm<=0)throw new Error('Pixel scale must be positive.');if(zmax<=zmin)throw new Error('Top z must be above bottom z.');
      if(this.sections.some((section,index)=>index!==this.editIndex&&(section.id===id||section.x_m===x)))throw new Error('Each section needs a unique identifier and station coordinate.');
      if(this.sections.length>=300&&this.editIndex===null)throw new Error('A run supports up to 300 section views.');
      const section={id,x_m:x,roi_px:this.roi.slice(),calibration:{centerline_px:this.origin[0],baseline_px:this.origin[1],pixels_per_metre:ppm},z_min_m:zmin,z_max_m:zmax,evidence:'Operator selected the image region, centreline/baseline origin, longitudinal station, vertical range and pixel scale in the local workbench. Port/starboard symmetry is an explicit unverified assumption.'};
      if(this.editIndex!==null)this.sections[this.editIndex]=section;else this.sections.push(section);
      this.resetSelection();this.renderList();this.feedback(`${this.sections.length} section${this.sections.length===1?'':'s'} recorded. ${this.sections.length<3?'Add at least '+(3-this.sections.length)+' more.':'Add more views or reconstruct the drawing.'}`);
    }catch(error){this.feedback(error.message,true);}
  }
  resetSelection(){this.editIndex=null;this.roi=null;this.origin=null;this.scaleLine=null;$('calibration-id').value=`section-${String(this.sections.length+1).padStart(2,'0')}`;setText('calibration-add','Add section');this.readout();this.setTool('region');this.renderList();this.draw();}
  edit(index){const section=this.sections[index];this.editIndex=index;this.roi=section.roi_px.slice();this.origin=[section.calibration.centerline_px,section.calibration.baseline_px];this.scaleLine=null;$('calibration-id').value=section.id;$('calibration-x').value=section.x_m;$('calibration-zmin').value=section.z_min_m;$('calibration-zmax').value=section.z_max_m;$('calibration-ppm').value=section.calibration.pixels_per_metre;setText('calibration-add','Update section');this.readout();this.renderList();this.draw();}
  renderList(){
    setText('editor-section-count',`${this.sections.length} sections`);const list=$('calibration-section-list');list.replaceChildren();
    this.sections.forEach((section,index)=>{const row=document.createElement('div');row.className=`calibration-entry${this.editIndex===index?' selected':''}`;const button=document.createElement('button');button.type='button';button.textContent=`${section.id} · ${number(section.x_m)} m`;button.addEventListener('click',()=>this.edit(index));const remove=document.createElement('button');remove.type='button';remove.textContent='×';remove.setAttribute('aria-label',`Remove ${section.id}`);remove.addEventListener('click',()=>{this.sections.splice(index,1);this.resetSelection();});row.append(button,remove);list.append(row);});
  }
  spec(){
    if(this.sections.length<3)throw new Error('Record at least three calibrated section views.');
    if(!$('calibration-symmetry').checked)throw new Error('Explicitly acknowledge the port/starboard symmetry assumption.');
    const vessel=$('calibration-vessel').value.trim();if(!vessel)throw new Error('Enter a vessel or drawing name.');
    return {schema_version:'1.0',vessel_id:vessel,source:{file:$('drawing-file').files[0]?.name||'drawing.png',license:'User-provided; rights not verified'},units:'m',symmetry:'port_starboard',symmetry_evidence:'Port/starboard symmetry explicitly assumed by the operator in the calibration editor; engineering verification is required.',end_closure:'flat_at_terminal_stations',sections:JSON.parse(JSON.stringify(this.sections)),components:[]};
  }
  draw(){
    const container=$('calibration-viewport');if(container.offsetWidth===0)return;const rect=container.getBoundingClientRect(),ratio=Math.min(devicePixelRatio||1,2);this.canvas.width=Math.max(1,Math.round(rect.width*ratio));this.canvas.height=Math.max(1,Math.round(rect.height*ratio));this.ctx.setTransform(ratio,0,0,ratio,0,0);this.ctx.fillStyle='#e8edef';this.ctx.fillRect(0,0,rect.width,rect.height);$('calibration-placeholder').hidden=!!this.image;if(!this.image)return;
    const t=this.transform(),ctx=this.ctx,point=([x,y])=>[t.x+x*t.scale,t.y+y*t.scale];ctx.drawImage(this.image,t.x,t.y,this.image.naturalWidth*t.scale,this.image.naturalHeight*t.scale);
    const box=(roi,color,width)=>{const p=point(roi),q=point(roi.slice(2));ctx.strokeStyle=color;ctx.lineWidth=width;ctx.strokeRect(p[0],p[1],q[0]-p[0],q[1]-p[1]);};
    this.sections.forEach((section,index)=>{if(index===this.editIndex)return;box(section.roi_px,'#16867b99',1);const p=point(section.roi_px);ctx.font='11px system-ui';const label=section.id,w=ctx.measureText(label).width+8;ctx.fillStyle='#edf8f1ee';ctx.fillRect(p[0],p[1],w,17);ctx.fillStyle='#116b64';ctx.fillText(label,p[0]+4,p[1]+12);});
    if(this.roi){box(this.roi,'#c2852a',2);const p=point(this.roi),q=point(this.roi.slice(2));ctx.fillStyle='#deb36812';ctx.fillRect(p[0],p[1],q[0]-p[0],q[1]-p[1]);}
    if(this.origin){const p=point(this.origin);ctx.strokeStyle='#b54e79';ctx.lineWidth=1.5;ctx.beginPath();ctx.moveTo(p[0]-12,p[1]);ctx.lineTo(p[0]+12,p[1]);ctx.moveTo(p[0],p[1]-12);ctx.lineTo(p[0],p[1]+12);ctx.stroke();ctx.beginPath();ctx.arc(p[0],p[1],3,0,Math.PI*2);ctx.fillStyle='#b54e79';ctx.fill();}
    if(this.scaleLine){const a=point(this.scaleLine[0]),b=point(this.scaleLine[1]);ctx.beginPath();ctx.moveTo(...a);ctx.lineTo(...b);ctx.strokeStyle='#357bbd';ctx.lineWidth=2;ctx.stroke();for(const p of [a,b]){ctx.beginPath();ctx.arc(...p,3,0,Math.PI*2);ctx.fillStyle='#357bbd';ctx.fill();}}
  }
}
async function updateReferenceField(){
  let needed=false;const file=$('spec-file').files[0];
  if(file&&!calibration.active){try{needed=!!JSON.parse(await file.text()).station_reference;}catch{}}
  $('reference-file-field').hidden=!needed;$('reference-file').required=needed;
}
$('spec-file').addEventListener('change',updateReferenceField);
const calibration = new CalibrationEditor();
if(SNAPSHOT){document.querySelector('.brand').href=location.href;document.querySelector('.build-label').textContent='Portable research snapshot';$('new-reconstruction').disabled=true;$('new-reconstruction').title='Run the local application to reconstruct a new drawing.';$('refresh-runs').hidden=true;}
async function initializeSession(){
  if(SNAPSHOT){await refreshRuns();return;}
  const token=new URLSearchParams(location.hash.slice(1)).get('session');
  if(token){history.replaceState(null,'',location.pathname+location.search);const response=await jsonFetch('/api/session',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token})});csrfToken=response.csrf;}
  else csrfToken=(await jsonFetch('/api/session')).csrf;
  await refreshRuns();
}
initializeSession().catch(error=>{notify(error.message,true);$('new-reconstruction').disabled=true;});
