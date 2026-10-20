(() => {
  let source = null, media = [], currentJob = null, sequence = 0, busy = false;
  const byId = id => document.getElementById(id);
  const node = (tag, text) => { const n = document.createElement(tag); if(text !== undefined) n.textContent=text; return n; };
  const message = text => { byId('enhanceProgress').textContent=text; };
  function buttons() { byId('enhancePreview').disabled=busy;byId('enhanceFull').disabled=busy||byId('enhanceMode').value.endsWith('_preview'); }
  async function select(item) {
    const request = ++sequence;
    source = item;
    byId('enhanceAccepted').checked=false;
    byId('enhanceSourceInfo').textContent='正在读取底片信息…';
    const info = await api('/api/tools/probe', {method:'POST', body:JSON.stringify(item)});
    if(request !== sequence) return;
    byId('enhanceSourceInfo').textContent=`${item.name} · ${info.width}×${info.height} · ${info.duration.toFixed(2)}秒 · ${info.has_audio?'保留原音轨':'保持静音'}。原片不会覆盖。`;
    const results=byId('enhanceResults');results.replaceChildren();
    results.append(player('原片预览', item.url));
  }
  function player(title, url) {
    const box=node('div');box.className='enhance-player';box.append(node('h4', title));
    const video=node('video');video.src=url;video.controls=true;video.preload='metadata';video.playsInline=true;
    const link=node('a','保存文件');link.href=url;link.download='';link.className='text-button';box.append(video, link);return box;
  }
  async function refresh() {
    const result=await api('/api/library?kind=video');media=result.items;
    const picker=byId('enhanceSource');picker.replaceChildren();
    const empty=node('option','请选择视频底片');empty.value='';picker.append(empty);
    media.forEach((item,index)=>{const option=node('option',item.name);option.value=String(index);picker.append(option);});
  }
  window.selectEnhanceSource = async item => {
    document.querySelectorAll('#mediaContent video,#mediaContent audio').forEach(v=>v.pause());
    document.getElementById('mediaDialog').close();setTab('enhance');await select(item);
  };
  async function poll(id) {
    const job=await api('/api/tools/jobs/'+id);if(currentJob!==id)return;
    message(job.message);
    if(['queued','running'].includes(job.status)){setTimeout(()=>poll(id).catch(e=>message(e.message)),1500);return;}
    busy=false;buttons();
    if(job.status!=='completed')return;
    const results=byId('enhanceResults');results.replaceChildren();
    const grid=node('div');grid.className='enhance-compare';
    grid.append(player('原片（未改动）',job.source_url),player('普通放大（无AI对照）',job.baseline_url),player('本次处理结果',job.output_url));results.append(grid);
    const info=job.info_after;
    results.append(node('p',`${info.width}×${info.height} · ${info.duration.toFixed(2)}秒 · ${info.has_audio?'保留音轨':'无音轨'}。${job.analysis_note}`));
  }
  async function run(preview) {
    if(!source)throw Error('请先导入或选择视频底片');
    if(!byId('enhanceAccepted').checked)throw Error('请先检查底片，并勾选没有明显变形');
    if(currentJob){const old=await api('/api/tools/jobs/'+currentJob);if(['queued','running'].includes(old.status))throw Error('已有增强任务，请等待完成');}
    const job=await api('/api/tools/run',{method:'POST',body:JSON.stringify({...source,action:'enhance',enhance_mode:byId('enhanceMode').value,target_height:Number(byId('enhanceTarget').value),enhance_strength:Number(byId('enhanceStrength').value)/100,preview_only:preview})});
    currentJob=job.id;localStorage.setItem('yingxu-enhance-job',job.id);busy=true;buttons();message('任务已加入队列；原片保留。');await poll(job.id);
  }
  async function status() {
    const s=await api('/api/enhance/status');byId('enhanceModelStatus').textContent=(s.available?'模型已准备：':'模型未准备：')+s.model+'。'+s.note+(s.seedvr_existing?' SeedVR2已有。':'')+(s.flashvsr_plus_available?' FlashVSR+已校验。':'')+(s.flashvsr_v1_available?' FlashVSR原版已校验。':'');
    byId('enhanceMode').querySelector('[value="flashvsr_plus_preview"]').disabled=!s.flashvsr_plus_available;
    byId('enhanceMode').querySelector('[value="flashvsr_v1_preview"]').disabled=!s.flashvsr_v1_available;
    byId('enhanceMode').querySelector('[value="seedvr2_preview"]').disabled=!s.seedvr_existing;
    byId('enhanceMode').querySelector('[value="realesrgan"]').disabled=!s.available;
    if(byId('enhanceMode').selectedOptions[0]?.disabled)byId('enhanceMode').value='resize';
  }
  const safe=fn=>Promise.resolve().then(fn).catch(e=>{message(e.message);toast(e.message);});
  byId('enhanceSource').onchange=e=>{if(e.target.value!=='')safe(()=>select(media[Number(e.target.value)]));else source=null;};
  byId('enhanceRefresh').onclick=()=>safe(refresh);
  byId('enhanceMode').onchange=buttons;
  byId('enhanceStrength').oninput=e=>byId('enhanceStrengthValue').textContent=e.target.value+'%';
  byId('enhancePreview').onclick=()=>safe(()=>run(true));byId('enhanceFull').onclick=()=>safe(()=>run(false));
  byId('enhanceUpload').onclick=()=>byId('enhanceFile').click();
  byId('enhanceFile').onchange=()=>safe(async()=>{
    const file=byId('enhanceFile').files[0];if(!file)return;if(file.size>1024**3)throw Error('请选择不超过1GB的视频');
    message('正在导入视频…');const r=await fetch('/api/upload-video?name='+encodeURIComponent(file.name),{method:'POST',body:file});const item=await r.json();if(!r.ok)throw Error(item.error);
    await refresh();await select(item);message('视频已导入，请检查底片后先试1秒。');
  });
  window.addEventListener('studio-tab',e=>{
    if(e.detail==='enhance')safe(async()=>{await refresh();await status();});
    else document.querySelectorAll('#tab-enhance video').forEach(v=>v.pause());
  });
  const linked=new URLSearchParams(location.search).get('enhance_job');
  const last=linked||localStorage.getItem('yingxu-enhance-job');if(last&&/^[a-f0-9]{16}$/.test(last)){currentJob=last;if(linked){localStorage.setItem('yingxu-enhance-job',last);setTab('enhance');}safe(()=>poll(last));}
})();
