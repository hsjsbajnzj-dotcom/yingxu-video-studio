"""Reuse the installed native ComfyUI SeedVR2 workflow. Preview only until longer clips are verified."""
import copy
import json
import subprocess
import time
import urllib.request
from pathlib import Path
import studio_hub as hub
import studio_config as config

ROOT = config.MODELS
MODEL = ROOT / 'diffusion_models/seedvr2_3b_int8_convrot.safetensors'
VAE = ROOT / 'vae/seedvr2_ema_vae_fp16.safetensors'
TEMPLATE = config.path('seedvr_template', config.STATE / 'unconfigured/seedvr-template.json')


def available():
    return config.feature('seedvr2') and all(p.is_file() for p in (MODEL, VAE, TEMPLATE))


def request(route, payload=None):
    req = urllib.request.Request(config.comfy_url() + route, None if payload is None else json.dumps(payload).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw.strip() else {}


def run(source, folder, config, info, update):
    if not available():
        raise ValueError('没有找到原有SeedVR2模型、VAE或历史工作流')
    if not config['preview']:
        raise ValueError('SeedVR2接入第一版仅开放前1秒试验；未验收完整短片')
    hub.start_engine('comfy_stable')
    deadline = time.monotonic() + 180
    update('等待原有SeedVR2引擎启动；不下载新模型…')
    while not hub.engine_ready('comfy_stable'):
        if time.monotonic() > deadline:
            raise TimeoutError('SeedVR2引擎启动超时')
        time.sleep(2)
    queue = request('/queue')
    if queue.get('queue_running') or queue.get('queue_pending'):
        raise ValueError('ComfyUI有其他任务，未提交SeedVR2试验')
    request('/free', {'unload_models': True, 'free_memory': True})
    from fractions import Fraction
    rate = Fraction(info['frame_rate'])
    count = round(float(rate) * config['seconds'])
    if count < 1 or count > 60:
        raise ValueError('SeedVR2仅验收前1秒、最多60帧')
    sequence = folder / 'seedvr_frames'
    sequence.mkdir(exist_ok=True)
    template = json.loads(TEMPLATE.read_text(encoding='utf-8'))['prompt']
    from PIL import Image
    started = time.monotonic()
    outputs = []
    for start in range(0, count, 9):
        chunk_count = min(9, count - start)
        graph = copy.deepcopy(template)
        graph['1']['inputs'].update(video=str(source), frame_load_cap=chunk_count, skip_first_frames=start)
        graph['2']['inputs'].update(width=config['width'], height=config['height'])
        graph['11']['inputs']['blend_factor'] = config['strength']
        graph['12']['inputs']['filename_prefix'] = (folder.relative_to(hub.MEDIA_ROOTS['h3']) / f'raw_chunk_{start:03d}/frame').as_posix()
        (folder / f'graph_{start:03d}.json').write_text(json.dumps(graph, ensure_ascii=False, indent=2), encoding='utf-8')
        response = request('/prompt', {'prompt': graph})
        pid = response.get('prompt_id')
        if not pid:
            raise RuntimeError('SeedVR2节点校验失败：' + str(response.get('node_errors', response)))
        deadline = time.monotonic() + 600
        try:
            while True:
                update(f'SeedVR2时序试验：第{start+1}–{start+chunk_count}帧；已用{time.monotonic()-started:.0f}秒')
                history = request('/history/' + pid).get(pid)
                if history:
                    status = history.get('status', {})
                    if status.get('status_str') == 'error':
                        raise RuntimeError('SeedVR2推理失败：' + str(status.get('messages', []))[-600:])
                    if status.get('completed'):
                        images = history.get('outputs', {}).get('12', {}).get('images', [])
                        if len(images) < chunk_count:
                            raise RuntimeError('SeedVR2返回的帧数少于原片')
                        for value in images[:chunk_count]:
                            path = (hub.MEDIA_ROOTS['h3'] / value.get('subfolder', '') / value['filename']).resolve()
                            path.relative_to(hub.MEDIA_ROOTS['h3'].resolve())
                            with Image.open(path) as image:
                                image.save(sequence / f'frame_{len(outputs):05d}.png')
                            outputs.append(path)
                        break
                if time.monotonic() > deadline:
                    raise TimeoutError('SeedVR2单段超过10分钟；原片保留')
                time.sleep(3)
        except Exception:
            queue = request('/queue')
            if any(row[1] == pid for row in queue.get('queue_running', [])):
                request('/interrupt', {})
            else:
                request('/queue', {'delete': [pid]})
            raise
    from studio_tools import FFMPEG
    target = Path(config['output'])
    duration = len(outputs) / float(rate)
    subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-framerate', str(rate), '-i', str(sequence / 'frame_%05d.png'), '-i', str(source), '-map', '0:v:0', '-map', '1:a?', '-t', str(duration), '-vf', 'setsar=1', '-c:v', 'libx264', '-crf', '17', '-preset', 'fast', '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags', '+faststart', str(target)], check=True, capture_output=True)
    subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-i', str(source), '-t', str(duration), '-vf', f"scale={config['width']}:{config['height']}:flags=lanczos,setsar=1", '-c:v', 'libx264', '-crf', '17', '-preset', 'fast', '-c:a', 'copy', str(folder / '普通等比放大_对照.mp4')], check=True, capture_output=True)
    (folder / '增强检验.json').write_text(json.dumps({'frames': len(outputs), 'frame_rate': str(rate), 'elapsed_seconds': round(time.monotonic()-started, 2), 'model': str(MODEL), 'preview_only': True, 'warning': '9帧分段时序修复，段落边界无重叠融合；必须检查纹理跳变，未验收完整短片。'}, ensure_ascii=False, indent=2), encoding='utf-8')
    request('/free', {'unload_models': True, 'free_memory': True})
    return target
