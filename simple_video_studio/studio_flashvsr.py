"""Isolated FlashVSR/FlashVSR+ one-second trials. Stable generation dependencies are untouched."""
import json
import math
import os
from fractions import Fraction
import subprocess
import time
from pathlib import Path
import studio_hub as hub
import studio_config as config

LAB = config.path('flashvsr_root', config.STATE / 'unconfigured/flashvsr')
PYTHON = Path(config.executable('flashvsr_python', 'python'))
ENTRY = config.path('flashvsr_entry', config.STATE / 'unconfigured/flashvsr-entry.py')


def available(mode):
    if not config.feature('flashvsr'):return False
    try:
        records = json.loads((LAB / 'weight_provenance.json').read_text(encoding='utf-8'))
        needed = {'turbo/dit.safetensors', 'turbo/lq_proj_in.safetensors', 'TCDecoder.ckpt'} if mode == 'turbo' else {'diffusion_pytorch_model_streaming_dmd.safetensors', 'LQ_proj_in.ckpt', 'TCDecoder.ckpt'}
        found = {r['file'] for r in records if r.get('verified_upstream_hash') and Path(r['target']).is_file() and Path(r['target']).stat().st_size == r['size']}
        return needed <= found and PYTHON.is_file() and ENTRY.is_file()
    except (OSError, ValueError, KeyError):
        return False


def canvas(info, target):
    edge = 1024 if target == 1080 else 768
    w, h = info['width'], info['height']
    while True:
        ratio = edge / min(w, h)
        nw, nh = max(128, round(w*ratio/128)*128), max(128, round(h*ratio/128)*128)
        if nw*nh <= 2000000 and max(nw, nh) <= 1920:
            return nw, nh
        edge -= 128


def run(source, folder, config, info, update):
    mode = 'turbo' if config['mode'] == 'flashvsr_plus_preview' else 'v1'
    if not config['preview']:
        raise ValueError('FlashVSR系列目前只开放前1秒试验，完整短片尚未验收')
    if abs(float(Fraction(info['frame_rate'])) - 24) > 0.001:
        raise ValueError('FlashVSR隔离入口目前只验收24fps底片，不自动改动动作帧率')
    if not available(mode):
        raise ValueError('隔离实验室的官方模型尚未下载并校验完成')
    nw, nh = canvas(info, config['height'] if info['height'] <= info['width'] else config['width'])
    if mode == 'v1':
        nw, nh = canvas(info, 720)  # first integration only exposes the tested 768-short-edge route
    raw = folder / 'Flash原始增强.mp4'
    config['native_canvas'] = [nw, nh]
    update(f'隔离FlashVSR {mode}正在增强前1秒；模型画布{nw}×{nh}，不改变稳定环境…')
    env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    env['PATH'] = str(Path(hub.config.FFMPEG).parent) + os.pathsep + env.get('PATH', '')
    started = time.monotonic()
    with (folder / 'flashvsr.log').open('wb') as log:
        proc = subprocess.Popen([str(PYTHON), str(ENTRY), '--mode', mode, '--height', str(nh), '--width', str(nw), '--frames', '24', '--input', str(source), '--output', str(raw)], env=env, stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        reason = None
        last_temperature = 0
        hot = 0
        try:
            while proc.poll() is None:
                elapsed = time.monotonic()-started
                update(f'隔离FlashVSR {mode}试验已用{elapsed:.0f}秒；请勿同时在其他窗口生成')
                if elapsed > 1200:
                    reason = '超过20分钟试验时限'
                    break
                if elapsed-last_temperature >= 15:
                    import psutil
                    if psutil.swap_memory().free < 1024**3:
                        reason = '分页空间余量不足1GB'
                        break
                    sample = subprocess.run(['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=5, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    if sample.returncode == 0:
                        hot = hot + 1 if int(sample.stdout.strip().splitlines()[0]) >= 88 else 0
                        if hot >= 2:
                            reason = '达到本次试验的保守温度停止条件'
                            break
                    last_temperature = elapsed
                time.sleep(2)
        finally:
            if proc.poll() is None:
                import psutil
                parent = psutil.Process(proc.pid)
                for child in parent.children(recursive=True):
                    child.terminate()
                parent.terminate()
                proc.wait(timeout=10)
    if proc.returncode:
        error = (folder / 'flashvsr.log').read_text(encoding='utf-8', errors='replace')
        raise RuntimeError((reason or 'FlashVSR试验失败') + '；原片保留。' + error[-500:])
    from studio_tools import FFMPEG, probe
    raw_info = probe(raw)
    # Reconstruct the same padding geometry used by the lab entry point, then
    # remove only added borders. Do not crop any original scene content.
    w, h = info['width'], info['height']
    divisor = math.gcd(nw, nh)
    uw, uh = nw//divisor, nh//divisor
    multiplier = math.ceil(max(w/uw, h/uh)/2)*2
    pw, ph = uw*multiplier, uh*multiplier
    cx = int(((pw-w)/2)*nw/pw)//2*2
    cy = int(((ph-h)/2)*nh/ph)//2*2
    right = min(nw, math.ceil(((pw+w)/2)*nw/pw/2)*2)
    bottom = min(nh, math.ceil(((ph+h)/2)*nh/ph/2)*2)
    cw, ch = right-cx, bottom-cy
    size = f"{config['width']}:{config['height']}"
    strength = config['strength']
    duration = min(1.0, raw_info['duration'])
    chain = f"[0:v]crop={cw}:{ch}:{cx}:{cy},scale={size}:flags=lanczos,setsar=1[a];[1:v]scale={size}:flags=lanczos,setsar=1[b];[a][b]blend=all_expr='A*{strength}+B*{1-strength}':shortest=1[v]"
    target = Path(config['output'])
    subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-i', str(raw), '-i', str(source), '-filter_complex', chain, '-map', '[v]', '-map', '1:a?', '-t', str(duration), '-c:v', 'libx264', '-preset', 'fast', '-crf', '17', '-pix_fmt', 'yuv420p', '-c:a', 'copy', '-movflags', '+faststart', str(target)], check=True, capture_output=True)
    subprocess.run([str(FFMPEG), '-v', 'error', '-y', '-i', str(source), '-t', str(duration), '-vf', f'scale={size}:flags=lanczos,setsar=1', '-c:v', 'libx264', '-preset', 'fast', '-crf', '17', '-c:a', 'copy', str(folder / '普通等比放大_对照.mp4')], check=True, capture_output=True)
    (folder / '增强检验.json').write_text(json.dumps({'mode': mode, 'native_canvas': [nw, nh], 'source_padding': [pw, ph], 'crop_of_padding_only': [cw, ch, cx, cy], 'info_after': probe(target), 'elapsed_seconds': round(time.monotonic()-started, 2), 'preview_only': True, 'warning': '扩散细节可能重建；仅1秒试验，未验收完整片段或严格五官保真。'}, ensure_ascii=False, indent=2), encoding='utf-8')
    return target
