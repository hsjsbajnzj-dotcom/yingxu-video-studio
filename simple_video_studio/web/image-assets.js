// Shared simple-form / shot-board editor. All images stay in the local upload store.
window.renderExtraImages = function(container, data, changed, enabled=true) {
  container.replaceChildren();
  data.reference_assets ??= [];
  const node = (tag,text) => {const n=document.createElement(tag);if(text)n.textContent=text;return n;};
  const url = path => '/media/input/'+path.split('/').map(encodeURIComponent).join('/');
  const rerender = () => {renderExtraImages(container,data,changed,enabled);changed();};
  const action = (label,fn) => {const b=node('button',label);b.type='button';b.className='text-button';b.onclick=fn;return b;};
  const hint=node('p',enabled?'本地H3：首帧可选，尾帧规定结尾；参考图提供人物/场景，不按图片顺序播放。多图更耗时，建议先用2–3张。':'当前模型只接通单首帧。附加图片不会被悄悄忽略，请切换本地H3或移除附加图。');
  hint.className='field-hint';container.append(hint);
  const grid=node('div');grid.className='image-assets-grid';container.append(grid);
  const preview=(asset,title,remove,kind='image')=>{const card=node('div');card.className='asset-tile';const img=node(kind==='video'?'video':'img');img.src=url(asset);if(kind==='video'){img.controls=true;img.preload='metadata';img.style.maxWidth='100%';}else img.alt=title;card.append(img,node('strong',title),action('移除',remove));grid.append(card);return card;};
  if(data.end_asset)preview(data.end_asset,'尾帧 · 镜头结束画面',()=>{data.end_asset='';rerender();});
  data.reference_assets.forEach((ref,index)=>{
    const card=preview(ref.input_asset,ref.kind==='video'?'3D预演 · 运动参考':`参考 ${index+1}`,()=>{data.reference_assets.splice(index,1);rerender();},ref.kind);
    const select=node('select');select.setAttribute('aria-label',`参考${index+1}用途`);
    for(const [value,label] of (ref.kind==='video'?[['motion','动作轨迹与节奏'],['camera','摄影机运动'],['full','整体视频参考']]:[['full','整体参考'],['person','人物身份'],['scene','场景环境'],['object','物品道具'],['style','画风色调']])){const op=node('option',label);op.value=value;select.append(op);}
    select.value=ref.takes||'full';select.onchange=()=>{ref.takes=select.value;changed();};card.append(select);
    if(index)card.append(action('前移',()=>{[data.reference_assets[index-1],data.reference_assets[index]]=[ref,data.reference_assets[index-1]];rerender();}));
  });
  async function upload(file){
    if(file.size>20*1024**2)throw Error('单张图片不能超过20MB');
    const content=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(reader.result);reader.onerror=reject;reader.readAsDataURL(file);});
    return api('/api/upload',{method:'POST',body:JSON.stringify({name:file.name,data:content})});
  }
  function picker(label,multiple,save){
    const input=node('input');input.type='file';input.accept='image/png,image/jpeg,image/webp,image/bmp';input.multiple=multiple;input.hidden=true;
    const b=action(label,()=>input.click());b.disabled=!enabled;
    input.onchange=async()=>{b.disabled=true;try{const files=[...input.files];if(multiple&&data.reference_assets.length+files.length>6)throw Error('工作室最多6张参考图，请减少选择');for(const file of files){save(await upload(file));changed();}rerender();}catch(e){toast(e.message);rerender();}finally{b.disabled=!enabled;}};
    container.append(input,b);
  }
  const motionHint=node('p','3D预演路径：基础建模与动画 → 渲染5–10秒MP4 → 上传运动参考 → H3生成。另加角色/场景图片约束外观；不直接读取.blend/.fbx/.glb，不保证逐帧遵循。');motionHint.className='field-hint';container.append(motionHint);
  const motionInput=node('input');motionInput.type='file';motionInput.accept='video/mp4,video/webm,video/quicktime,.mkv';motionInput.hidden=true;
  const motionButton=action('＋ 添加3D预演／运动参考视频',()=>motionInput.click());motionButton.disabled=!enabled;
  motionInput.onchange=async()=>{const file=motionInput.files[0];if(!file)return;motionButton.disabled=true;try{if(data.reference_assets.length>=6)throw Error('参考素材总数最多6个');if(data.reference_assets.some(r=>r.kind==='video'))throw Error('一次最多一条运动参考视频');if(file.size>100*1024**2)throw Error('预演视频不能超过100MB');const result=await api('/api/upload-motion?name='+encodeURIComponent(file.name),{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});data.reference_assets.push({input_asset:result.input_asset,kind:'video',takes:'motion'});rerender();}catch(e){toast(e.message);}finally{motionButton.disabled=!enabled;motionInput.value='';}};
  container.append(motionInput,motionButton);
  picker(data.end_asset?'替换尾帧':'＋ 添加尾帧',false,a=>{data.end_asset=a.input_asset;});
  picker('＋ 批量添加参考图（最多6张）',true,a=>{data.reference_assets.push({input_asset:a.input_asset,takes:'full'});});
};
