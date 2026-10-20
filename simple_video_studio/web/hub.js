(() => {
  const hubState = {project:null, projects:[], tasks:new Map(), media:[], toolJob:null};
  let saving = Promise.resolve(), saveTimer, searchTimer, librarySequence=0;
  const el = (tag, cls, text) => { const n=document.createElement(tag); if(cls)n.className=cls; if(text!==undefined)n.textContent=text; return n; };
  const button = (text, action, cls="secondary-button") => { const n=el("button",cls,text); n.type="button"; n.onclick=()=>Promise.resolve(action()).catch(e=>toast(e.message)); return n; };
  const id = () => crypto.randomUUID().replaceAll("-","");
  function download(name, object) { const url=URL.createObjectURL(new Blob([JSON.stringify(object,null,2)],{type:"application/json"})); const a=el("a"); a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000); }
  function inputPreview(asset) { return "/media/input/"+asset.split("/").map(encodeURIComponent).join("/"); }
  function newShot(values={}) { return {id:id(),title:"未命名镜头",prompt:"",provider:"local_h3",engine_profile:"comfy_stable",mode:"text",input_asset:"",end_asset:"",duration:5,aspect:"16:9",quality:"balanced",generate_audio:true,realism:true,seed:-1,...values,reference_assets:structuredClone(values.reference_assets||[])}; }
  function saveSoon() { clearTimeout(saveTimer); $("#projectSaveState").textContent="有改动，正在保存…";saveTimer=setTimeout(()=>persist().catch(e=>toast(e.message)),850); }
  async function persist() {
    clearTimeout(saveTimer);
    if(!hubState.project) return;
    const snapshot=JSON.parse(JSON.stringify(hubState.project));
    saving=saving.catch(()=>{}).then(async()=>{
      const result=await api("/api/projects",{method:"POST",body:JSON.stringify(snapshot)});
      if(hubState.project?.id===snapshot.id){ $("#projectSaveState").textContent="已保存在本机"; }
      localStorage.setItem("yingxu-project",result.id);
      await loadProjectList();
      return result;
    });
    return saving;
  }
  async function loadProjectList() {
    const {projects}=await api("/api/projects");hubState.projects=projects;
    const list=$("#projectList");list.replaceChildren();
    for(const p of projects) list.append(button(p.name,async()=>{await persist();hubState.project=p;renderProject();},"project-item"+(hubState.project?.id===p.id?" active":"")));
    if(!projects.length) list.append(el("p","field-hint","先创建你的第一个镜头项目。"));
  }
  async function createProject(shots=[]) {
    await persist();
    hubState.project=await api("/api/projects",{method:"POST",body:JSON.stringify({id:id(),name:"新项目 "+new Date().toLocaleDateString("zh-CN"),shots})});
    localStorage.setItem("yingxu-project",hubState.project.id);
    renderProject();await loadProjectList();
  }
  function renderProject() {
    const p=hubState.project;
    $("#projectName").value=p?.name||"";$("#projectNotes").value=p?.notes||"";
    $("#shotBoard").replaceChildren();
    if(!p?.shots.length) $("#shotBoard").append(el("div","empty-board","从一个镜头开始。\n可以在快速生成中“加入分镜”，也可以导入参考视频，自动拆出镜头和独立首帧。"));
    p?.shots.forEach((shot,index)=>$("#shotBoard").append(shotCard(shot,index)));
    updateShotStatuses();
  }
  function selectField(card,label,key,options,shot) {
    const wrap=el("label","",label), select=el("select");
    for(const [value,text] of options){const op=el("option","",text);op.value=value;select.append(op);}
    select.value=shot[key];select.onchange=()=>{shot[key]=select.value;saveSoon();if(key==="provider")renderProject();};wrap.append(select);card.append(wrap);
  }
  function shotCard(shot,index) {
    const card=el("article","shot-card");card.dataset.shot=shot.id;
    const head=el("div","shot-head");head.append(el("span","shot-index",`SHOT ${String(index+1).padStart(2,"0")}`));
    head.append(button("↑",async()=>moveShot(index,-1),"text-button"),button("↓",async()=>moveShot(index,1),"text-button"));
    const title=el("input","shot-title");title.value=shot.title;title.placeholder="镜头名称";title.setAttribute("aria-label","镜头名称");title.oninput=()=>{shot.title=title.value;saveSoon();};
    const frame=el("div","shot-frame");
    if(shot.input_asset){const img=el("img");img.src=inputPreview(shot.input_asset);img.alt="镜头首帧";frame.append(img);}else frame.append(el("span","","点击添加首帧（可选）；尾帧和参考图在下方添加"));
    const picker=el("input");picker.type="file";picker.accept="image/*";picker.hidden=true;
    picker.onchange=async()=>{try{const asset=await uploadAsset(picker.files[0]);shot.input_asset=asset.input_asset;shot.mode="image";await persist();renderProject();}catch(e){toast(e.message);}};
    frame.onclick=()=>picker.click();frame.title="点击选择首帧图片";
    const prompt=el("textarea");prompt.value=shot.prompt;prompt.placeholder="主体、动作、机位、环境反应、台词与声音。直接用中文写。";prompt.oninput=()=>{shot.prompt=prompt.value;saveSoon();};
    const settings=el("div","shot-settings");
    selectField(settings,"生成模型","provider",[["local_h3","MiniMax H3 · 音画同步"],["local_wan5b","Wan 2.2 · 无声画面"]],shot);
    selectField(settings,"本地引擎","engine_profile",[["comfy_stable","稳定版"],["comfy_latest","新版 0.42.1"]],shot);
    selectField(settings,"质量预设","quality",[["draft","快速草稿"],["balanced","均衡预览"],["final","质量优先"]],shot);
    const length=el("label","","时长 / 秒"),seconds=el("input");seconds.type="number";seconds.min=1;seconds.max=15;seconds.value=shot.duration;seconds.onchange=()=>{shot.duration=Number(seconds.value);saveSoon();};length.append(seconds);settings.append(length);
    const controls=el("div","shot-controls");controls.append(button("生成这一镜",()=>generateShot(shot),""),button("带到快速生成",()=>{applyStudioDraft(shot);setTab("create");},""),button("复制",async()=>{hubState.project.shots.splice(index+1,0,newShot({...shot,id:id(),task_id:undefined,title:shot.title+" 副本"}));renderProject();await persist();},""),button("移除",async()=>{hubState.project.shots.splice(index,1);renderProject();await persist();},""));
    if(shot.input_asset) controls.append(button("清除首帧",async()=>{shot.input_asset="";shot.mode=(shot.end_asset||shot.reference_assets?.length)?"image":"text";renderProject();await persist();},""));
    const extras=el("div");renderExtraImages(extras,shot,()=>{shot.mode=(shot.input_asset||shot.end_asset||shot.reference_assets?.length)?"image":"text";saveSoon();updateShotStatuses();},shot.provider==="local_h3");
    const status=el("div","shot-status");status.dataset.status=shot.id;
    card.append(head,title,frame,picker,extras,prompt,settings,controls,status);return card;
  }
  async function moveShot(index,direction) { const shots=hubState.project.shots;const target=index+direction;if(target<0||target>=shots.length)return;[shots[index],shots[target]]=[shots[target],shots[index]];renderProject();await persist(); }
  async function generateShot(shot) {
    const existing=hubState.tasks.get(shot.task_id);if(existing&&["queued","starting","running"].includes(existing.status))return toast("这个镜头已有生成任务");
    await persist();const task=await api("/api/generate",{method:"POST",body:JSON.stringify({...shot,project_id:hubState.project.id})});
    shot.task_id=task.id;hubState.tasks.set(task.id,task);await persist();updateShotStatuses();toast("镜头已加入生成队列");
  }
  function updateShotStatuses() {
    for(const shot of hubState.project?.shots||[]){const n=document.querySelector(`[data-status="${shot.id}"]`);if(!n)continue;const task=hubState.tasks.get(shot.task_id);n.replaceChildren();if(!task){n.textContent="未提交 · "+(shot.mode==="image"?"图片＋文字":"文生视频");continue;}n.append(el("span","",statusLabel(task.status)+" · "+(task.message||"")));const video=task.outputs?.find(o=>o.kind==="video");if(video)n.append(button("查看成片",()=>showMedia({name:video.name,kind:"video",url:video.media_url}),"text-button"));}
  }
  async function refreshShotTasks() {try{const {tasks}=await api("/api/tasks");hubState.tasks=new Map(tasks.map(t=>[t.id,t]));updateShotStatuses();}catch(e){console.warn(e);}}
  async function uploadAsset(file){if(!file)throw Error("请选择图片");if(file.size>20*1024**2)throw Error("图片不能超过20MB");const data=await new Promise((res,rej)=>{const r=new FileReader();r.onload=()=>res(r.result);r.onerror=rej;r.readAsDataURL(file);});return api("/api/upload",{method:"POST",body:JSON.stringify({name:file.name,data})});}
  window.applyStudioDraft=function(data){
    if(data.provider){$("#provider").value=data.provider;updateProviderUI();}
    state.quality=data.quality||"balanced";renderQualityCards();
    $("#realismStrength").value=data.realism_strength??"";
    $("#ambience").value=data.ambience||"none";$("#performance").value=data.performance||"none";
    for(const [key,target] of Object.entries({prompt:"prompt",duration:"duration",aspect:"aspect",engine_profile:"engineProfile",soundscape:"soundscape",seed:"seed",title:"title",steps:"customSteps",short_edge:"nativeEdge"})) if(data[key]!==undefined)$("#"+target).value=data[key]??"";
    for(const [key,target] of Object.entries({generate_audio:"generateAudio",music:"music",realism:"realism"}))if(data[key]!==undefined)$("#"+target).checked=data[key];
    if(data.input_asset){state.inputAsset=data.input_asset;$("#imagePreview").src=inputPreview(data.input_asset);$("#imageName").textContent="已载入首帧";$("#imagePreviewWrap").classList.remove("hidden");$("#uploadButton").classList.add("hidden");}else removeImage();
    state.end_asset=data.end_asset||"";state.reference_assets=structuredClone(data.reference_assets||[]);
    renderExtraImages($("#extraImageAssets"),state,updateExplanation,provider().id==="local_h3");
    updateMode(data.mode||"text");updateDurationUI();$("#prompt").dispatchEvent(new Event("input"));
  };
  async function addCurrent(){if(!hubState.project)await createProject();const draft=collectForm();delete draft.api_key;if(!draft.provider.startsWith("local_")){draft.provider="local_h3";toast("分镜批量工作流使用本地模型");}hubState.project.shots.push(newShot({...draft,title:draft.title||`镜头 ${hubState.project.shots.length+1}`}));await persist();renderProject();setTab("workflow");}
  async function loadLibrary(){const sequence=++librarySequence;const q=encodeURIComponent($("#librarySearch").value);const kind=$("#libraryKind").value;const frames=$("#libraryFrames").checked?"1":"0";$("#libraryCount").textContent="正在读取素材…";const result=await api(`/api/library?q=${q}&kind=${kind}&frames=${frames}`);if(sequence!==librarySequence)return;hubState.media=result.items;$("#libraryCount").textContent=`共 ${result.total} 个，显示最近 ${result.items.length} 个`;const grid=$("#libraryGrid");grid.replaceChildren();for(const item of result.items){const card=el("article","media-card"),thumb=el("div","media-thumb");if(item.kind==="image"){const image=el("img");image.src=item.url;image.alt=item.name;image.loading="lazy";thumb.append(image);}else{thumb.append(el("span","", "▷ 视频 · 点击预览"));}thumb.onclick=()=>showMedia(item);const meta=el("div","media-meta");meta.append(el("strong","",item.name),el("p","",({h3:"H3 / 工具输出",wangp:"WanGP 输出",assets:"项目资产"})[item.root]+" · "+(item.bytes/1024**2).toFixed(1)+" MB"),button(item.kind==="video"?"尾帧接拍":"用作首帧",()=>useLibraryAsset(item),"text-button"));card.append(thumb,meta);grid.append(card);}if(!result.items.length)grid.append(el("p","field-hint","暂时没有匹配的素材。可以上传首帧，或导入一个参考视频。"));}
  async function useLibraryAsset(item){const result=await api("/api/assets/use",{method:"POST",body:JSON.stringify(item)});applyStudioDraft({provider:"local_h3",mode:"image",input_asset:result.input_asset});$("#mediaDialog").close();setTab("create");toast("首帧已准备好，描述接下来发生什么即可");}
  function showMedia(item){$("#mediaTitle").textContent=item.name;$("#mediaContent").replaceChildren();$("#mediaTools").replaceChildren();$("#toolResult").replaceChildren();const media=el(item.kind==="video"?"video":"img");media.src=item.url;if(item.kind==="video"){media.controls=true;media.preload="metadata";}else media.alt=item.name;$("#mediaContent").append(media);if(item.root){$("#mediaTools").append(button(item.kind==="video"?"提取尾帧接拍":"用作首帧",()=>useLibraryAsset(item)));if(item.kind==="video"){
      $("#mediaTools").append(button("检查画质信息",async()=>{const r=await api("/api/tools/probe",{method:"POST",body:JSON.stringify(item)});$("#toolResult").textContent=`原生 ${r.width} × ${r.height} · ${r.duration.toFixed(2)} 秒 · ${r.frame_rate} fps · ${r.codec} · ${r.has_audio?"有音轨":"无音轨"} · 码率 ${r.bit_rate?Math.round(Number(r.bit_rate)/1000)+" kbps":"未知"}。分辨率不等于真实细节。`;}));
      $("#mediaTools").append(button("送入画质增强",()=>window.selectEnhanceSource(item)),button("自动拆镜 / 独立参考帧",()=>runTool(item,"analyze")),button("导出原片音轨",()=>runTool(item,"audio")));
      const soundBox=el("div","panel sound-controls"),soundPreset=el("select"),gain=el("input"),keep=el("input"),offset=el("input");
      for(const [value,label] of [["summer_street","夏日街边：蝉鸣与远车"],["night_street","夜间街道：轮胎与远处人声"],["room","室内：细微底噪"],["cicadas","独立蝉鸣"],["traffic","独立远处车流"],["crowd","独立远处人声"],["footsteps","画外路人脚步（需校准）"],["leaves","独立轻风树叶"]]){const o=el("option","",label);o.value=value;soundPreset.append(o);}
      soundPreset.value="night_street";gain.type="number";gain.min=-60;gain.max=6;gain.value=-12;gain.title="环境音增益 dB，建议先 -12";offset.type="number";offset.min=0;offset.step=0.1;offset.value=0;offset.title="声音入点 / 秒";keep.type="checkbox";keep.checked=true;
      const keepLabel=el("label","check-row","保留原声（含对白；误配乐也会保留）");keepLabel.prepend(keep);
      const presetWrap=el("label","sound-wide","声音预设"),gainWrap=el("label","","环境音音量 / dB"),offsetWrap=el("label","","声音入点 / 秒");presetWrap.append(soundPreset);gainWrap.append(gain);offsetWrap.append(offset);
      soundBox.append(el("h3","","本地环境声补配"),el("p","field-hint","MMAudio按预设文字生成环境音床，不自动识别或精确同步脚步。只开放5–10秒附近的短片；不是声音越多越真实。"),presetWrap,gainWrap,offsetWrap,keepLabel,
        button("本地生成环境音并混入",()=>runTool(item,"ambience",{ambience:soundPreset.value,gain_db:Number(gain.value),offset:Number(offset.value),keep_original:keep.checked})));
      const audioPicker=el("input");audioPicker.type="file";audioPicker.accept="audio/*,.flac,.wav,.mp3,.m4a,.ogg";audioPicker.hidden=true;
      audioPicker.onchange=async()=>{try{const file=audioPicker.files[0];if(!file)return;if(file.size>50*1024**2)throw Error("音频不能超过50MB");const asset=await api("/api/upload-audio?name="+encodeURIComponent(file.name),{method:"POST",headers:{"Content-Type":"application/octet-stream"},body:file});await runTool(item,"mix",{audio_root:asset.root,audio_path:asset.path,gain_db:Number(gain.value),offset:Number(offset.value),keep_original:keep.checked});}catch(e){toast(e.message);}};
      soundBox.append(audioPicker,button("导入自有/已授权声音并混入",()=>audioPicker.click()));$("#mediaTools").append(soundBox);
      const start=el("input"),duration=el("input");for(const n of [start,duration]){n.type="number";n.min=0;n.style.width="105px";}start.value=0;start.title="片段起点 / 秒";duration.value=5;duration.title="截取时长 / 秒";$("#mediaTools").append(el("span","field-hint","起点 / 时长（秒）"),start,duration,button("截取片段",()=>runTool(item,"trim",{start:Number(start.value),duration:Number(duration.value)})));
    }}const save=el("a","secondary-button","保存文件");save.href=item.url;save.download=item.name;$("#mediaTools").append(save);if(!$("#mediaDialog").open)$("#mediaDialog").showModal();}
  async function runTool(item,action,params={}){const job=await api("/api/tools/run",{method:"POST",body:JSON.stringify({...item,...params,action})});hubState.toolJob=job.id;$("#toolResult").textContent="工具已加入队列…";pollTool(job.id);}
  async function pollTool(jid){try{const job=await api("/api/tools/jobs/"+jid);if(hubState.toolJob!==jid)return;const result=$("#toolResult");result.replaceChildren(el("p","field-hint",job.message));if(["queued","running"].includes(job.status)){setTimeout(()=>pollTool(jid),1600);return;}if(job.status==="failed")return;
    if(job.output_url){const link=el("a","secondary-button","保存处理结果");link.href=job.output_url;link.download="";result.append(link);}
    if(job.audio_url){const player=el("audio");player.src=job.audio_url;player.controls=true;player.preload="metadata";const stem=el("a","secondary-button","保存独立环境音轨");stem.href=job.audio_url;stem.download="";result.append(player,stem);}
    if(job.analysis_note&&!job.shots)result.append(el("p","field-hint",job.analysis_note));
    if(job.shots){result.append(el("p","field-hint",job.analysis_note));result.append(button("把这些参考镜头建立成新项目",async()=>{const shots=job.shots.map(s=>newShot({title:`参考镜头 ${s.index} · ${s.start}–${s.end}秒`,mode:"image",input_asset:s.input_asset,duration:Math.max(1,Math.min(8,Math.round(s.duration))),prompt:""}));await createProject(shots);$("#mediaDialog").close();setTab("workflow");toast("独立参考帧已入分镜，请填写每个镜头的动作描述");}));const grid=el("div","scene-results");for(const shot of job.shots){const wrap=el("div"),image=el("img");image.src=shot.frame_url;image.alt=`参考镜头${shot.index}`;wrap.append(image,el("p","",`镜头 ${shot.index} · ${shot.start}–${shot.end} 秒`));grid.append(wrap);}result.append(grid);}
  }catch(e){$("#toolResult").textContent=e.message;}}
  async function loadEngines(){
    const [{engines},doctor]=await Promise.all([api('/api/engines'),api('/api/diagnostics')]);
    $('#doctorSummary').textContent=`网页依赖：${doctor.basic_ready?'就绪':'缺少psutil或Python版本不支持'}；媒体工具：${doctor.media_ready?'就绪':'请检查FFmpeg、FFprobe及requirements-media.txt'}；拆镜组件：${doctor.scenedetect?'已安装':'未安装'}。${doctor.next_step}。${doctor.scope}`;
    const grid=$('#engineCards');grid.replaceChildren();
    for(const engine of engines){const card=el('article','engine-card');const open=button('在工作室内打开',()=>openEngine(engine));open.disabled=!engine.installed;
      card.append(el('h3','',engine.name+' · '+engine.version),el('span','status-dot '+(engine.ready?'good':'muted'),engine.ready?'正在运行':engine.installed?'按需启动':'未配置 / 目录不存在'),el('p','',engine.note),open);
      if(engine.kind==='comfy'&&engine.ready)card.append(button('停止空闲引擎',async()=>{await api('/api/engines/stop',{method:'POST',body:JSON.stringify({id:engine.id})});loadEngines();},'text-button'));
      grid.append(card);
    }
  }
  async function openEngine(engine){$("#advancedEditor").classList.remove("hidden");$("#advancedTitle").textContent=engine.name;$("#advancedState").textContent="正在启动；首次加载组件可能需要1–3分钟…";$("#advancedFrame").removeAttribute("src");await api("/api/engines/start",{method:"POST",body:JSON.stringify({id:engine.id})});for(let i=0;i<90;i++){const {engines}=await api("/api/engines");if(engines.find(e=>e.id===engine.id)?.ready){$("#advancedFrame").src=engine.url;$("#advancedState").textContent="完整工具已经连接。生成前请确认其他引擎没有正在占用显卡。";loadEngines();return;}await new Promise(r=>setTimeout(r,2000));}$("#advancedState").textContent="引擎仍未就绪，请检查工作室 logs 目录中的对应引擎日志。";}
  async function prepareGraph(){const result=await api("/api/prepare",{method:"POST",body:JSON.stringify(collectForm())});$("#mediaTitle").textContent="实际提交给本地引擎的节点方案";$("#mediaContent").replaceChildren(el("pre","",JSON.stringify(result,null,2)));$("#mediaTools").replaceChildren(button("导出 ComfyUI API 工作流 JSON",()=>download("ComfyUI_API工作流.json",result.prompt)),button("导出完整生成方案",()=>download("生成方案.json",result)));$("#toolResult").textContent="API 工作流可通过 ComfyUI API 提交；它与可视化界面的节点布局文件格式不同。";$("#mediaDialog").showModal();}
  function bind(){
    document.querySelectorAll("[data-folder]").forEach(n=>n.onclick=()=>api("/api/open-folder",{method:"POST",body:JSON.stringify({folder:n.dataset.folder})}).catch(e=>toast(e.message)));
    $("#newProject").onclick=()=>createProject().catch(e=>toast(e.message));
    $("#saveProject").onclick=()=>persist().catch(e=>toast(e.message));
    $("#projectName").oninput=()=>{if(hubState.project){hubState.project.name=$("#projectName").value;saveSoon();}};
    $("#projectNotes").oninput=()=>{if(hubState.project){hubState.project.notes=$("#projectNotes").value;saveSoon();}};
    $("#addCurrentShot").onclick=()=>addCurrent().catch(e=>toast(e.message));
    $("#addShot").onclick=async()=>{if(!hubState.project)await createProject();hubState.project.shots.push(newShot({title:`镜头 ${hubState.project.shots.length+1}`}));renderProject();await persist();};
    $("#shotTemplate").onclick=async()=>{if(!hubState.project)await createProject();for(const title of ["建立空间","关键动作","情绪反应"])hubState.project.shots.push(newShot({title}));renderProject();await persist();};
    $("#runProject").onclick=async()=>{try{if(!hubState.project)return toast("先新建一个项目");await persist();hubState.project=await api("/api/projects/run",{method:"POST",body:JSON.stringify({id:hubState.project.id})});await refreshShotTasks();renderProject();toast("全部镜头已进入顺序生成队列");}catch(e){toast(e.message);}};
    $("#exportProject").onclick=()=>{if(hubState.project)download(hubState.project.name+".json",hubState.project);};
    $("#importProject").onclick=()=>$("#projectFile").click();
    $("#projectFile").onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>1024**2)throw Error("项目文件过大");const data=JSON.parse(await file.text());if(!Array.isArray(data.shots))throw Error("请选择映序导出的项目文件");await createProject(data.shots.map(s=>newShot({...s,id:id(),task_id:undefined})));hubState.project.name=data.name||"导入项目";hubState.project.notes=data.notes||"";await persist();renderProject();}catch(error){toast(error.message);}};
    $("#refreshLibrary").onclick=()=>loadLibrary().catch(e=>toast(e.message));$("#libraryKind").onchange=()=>loadLibrary();$("#libraryFrames").onchange=()=>loadLibrary();$("#librarySearch").oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(loadLibrary,300);};
    $("#refreshEngines").onclick=()=>loadEngines().catch(e=>toast(e.message));
    $("#closeAdvanced").onclick=()=>{$("#advancedEditor").classList.add("hidden");$("#advancedFrame").removeAttribute("src");};
    $("#closeMedia").onclick=()=>$("#mediaDialog").close();$("#mediaDialog").addEventListener("close",()=>{$("#mediaContent video")?.pause();$("#mediaContent audio")?.pause();});
    $("#prepareGraph").onclick=()=>prepareGraph().catch(e=>toast(e.message));
    $("#uploadReference").onclick=()=>$("#referenceInput").click();$("#referenceInput").onchange=async e=>{const file=e.target.files[0];if(!file)return;if(file.size>1024**3)return toast("视频不能超过1GB");$("#uploadReference").disabled=true;$("#uploadReference").textContent="正在导入…";try{const response=await fetch("/api/upload-video?name="+encodeURIComponent(file.name),{method:"POST",body:file});const result=await response.json();if(!response.ok)throw Error(result.error);await loadLibrary();toast("参考视频已导入，点击视频可以自动拆镜");}catch(error){toast(error.message);}finally{$("#uploadReference").disabled=false;$("#uploadReference").textContent="导入参考视频";}};
    window.addEventListener("studio-tab",e=>{if(e.detail==="workflow"){loadProjectList();refreshShotTasks();}if(e.detail==="library")loadLibrary().catch(error=>toast(error.message));if(e.detail==="engines")loadEngines().catch(error=>toast(error.message));if(e.detail!=="create")$("#resultVideo").pause();});
  }
  async function initHub(){bind();await loadProjectList();hubState.project=hubState.projects.find(p=>p.id===localStorage.getItem("yingxu-project"))||hubState.projects[0]||null;renderProject();await refreshShotTasks();setInterval(refreshShotTasks,7000);}
  initHub().catch(e=>toast(e.message));
})();
