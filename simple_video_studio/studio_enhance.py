"""Conservative, frame-preserving enhancement; no diffusion, face repair or interpolation."""
import hashlib
import json
import math
import os
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

import studio_hub as hub
import studio_config as config

GPU_LOCK = threading.Lock()  # studio.py replaces this with the shared local render lock
MODEL = config.path('realesrgan_model', config.MODELS / 'upscale_models/RealESRGAN_x2plus.pth')
PROVENANCE = MODEL.with_name('yingxu_upscale_provenance.json')
PYTHON = Path(config.executable('enhance_python', sys.executable))


def model_status():
    import studio_seedvr
    import studio_flashvsr
    return {'available': config.feature('realesrgan') and MODEL.is_file() and PROVENANCE.is_file(), 'model': MODEL.name,
            'seedvr_existing': studio_seedvr.available(),
            'flashvsr_plus_available': studio_flashvsr.available('turbo'),
            'flashvsr_v1_available': studio_flashvsr.available('v1'),
            'note': '逐帧 Real-ESRGAN x2 + 原片混合；不是时序扩散超分，需检查闪烁。'}


def settings(data, info):
    mode = str(data.get('enhance_mode', 'realesrgan'))
    if mode not in {'realesrgan', 'resize', 'seedvr2_preview', 'flashvsr_plus_preview', 'flashvsr_v1_preview'}:
        raise ValueError('请选择已验证的增强引擎')
    height = int(data.get('target_height', 1080))
    strength = float(data.get('enhance_strength', 0.35))
    preview = data.get('preview_only', True)
    if not isinstance(preview, bool):
        raise ValueError('试片选项必须为布尔值')
    if mode.endswith('_preview') and not preview:
        raise ValueError('进阶模型仅开放前1秒试验，完整短片尚未验收')
    if height not in {720, 1080} or not math.isfinite(strength) or not 0 <= strength <= 0.6:
        raise ValueError('当前支持720/1080短边，增强强度0–0.6')
    w, h = int(info.get('width') or 0), int(info.get('height') or 0)
    if not w or not h or min(w, h) > 1080 or w * h > 2200000:
        raise ValueError('第一版只验收短边不超过1080的视频底片')
    if not 0 < info['duration'] <= 15.5:
        raise ValueError('第一版只验收15秒以内的短视频，请先截取片段')
    if min(w, h) >= height:
        raise ValueError('目标短边需要大于原片短边，避免反复增强已放大的视频')
    ratio = height / min(w, h)
    width, out_height = round(w * ratio / 2) * 2, round(h * ratio / 2) * 2
    if mode != 'resize' and ratio > 2.2:
        raise ValueError('保守AI增强最多放大约2倍；请先选择720或使用更清楚的底片')
    return {'mode': mode, 'width': width, 'height': out_height, 'strength': strength,
            'preview': preview, 'seconds': min(1.0, info['duration']) if preview else info['duration'],
            'tile': 192, 'overlap': 24}


def release_idle_comfy():
    # Never interrupt or stop user jobs. Check all reachable Comfy queues first.
    ready = []
    for name in ('comfy_stable', 'comfy_latest'):
        if not hub.engine_ready(name):
            continue
        url = hub.engine_info(name)['url']
        with urllib.request.urlopen(url + '/queue', timeout=5) as response:
            queue = json.load(response)
        if queue.get('queue_running') or queue.get('queue_pending'):
            raise ValueError('ComfyUI有未完成任务，请完成后再增强；不会自动中断任务')
        ready.append(url)
    for url in ready:
        req = urllib.request.Request(url + '/free', json.dumps({'unload_models': True, 'free_memory': True}).encode(), {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=15) as response:
            response.read()


def enhance(source, folder, data, info, update):
    config = settings(data, info)
    if config['mode'] == 'realesrgan' and not model_status()['available']:
        raise ValueError('已验证的增强模型尚未准备好；不自动下载或替换模型')
    config.update(source=str(source), output=str(folder / ('试片_1秒.mp4' if config['preview'] else '画质增强_保守版.mp4')))
    spec = folder / '增强方案.json'
    spec.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    update('等待本地增强任务；与视频生成错开显存占用…')
    # Use an isolated process so GPU/CPU model memory is always released on completion.
    with GPU_LOCK:
        if config['mode'].startswith('flashvsr_'):
            import studio_flashvsr
            release_idle_comfy()
            return studio_flashvsr.run(source, folder, config, info, update), config
        if config['mode'] == 'seedvr2_preview':
            import studio_seedvr
            return studio_seedvr.run(source, folder, config, info, update), config
        if config['mode'] == 'realesrgan':
            release_idle_comfy()
        worker = hub.APP / 'enhance_worker.py'
        with (folder / 'worker_error.log').open('wb') as errors:
            proc = subprocess.Popen([str(PYTHON), '-u', str(worker), str(spec)], env=dict(os.environ, PYTHONUTF8='1'), stdout=subprocess.PIPE,
                                    stderr=errors, text=True, encoding='utf-8',
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            try:
                import time
                deadline = time.monotonic() + 1800
                while proc.poll() is None:
                    progress = folder / 'progress.json'
                    if progress.is_file():
                        try:
                            p = json.loads(progress.read_text(encoding='utf-8'))
                            update(p['message'])
                        except (ValueError, OSError):
                            pass
                    if time.monotonic() > deadline:
                        proc.kill()
                        raise TimeoutError('增强超过30分钟安全时限，原片未修改')
                    time.sleep(1)
                proc.wait()
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.stdout.close()
        if proc.returncode:
            error = (folder / 'worker_error.log').read_text(encoding='utf-8', errors='replace')
            raise RuntimeError('增强失败，原片未修改。' + error[-700:])
    return Path(config['output']), config
