"""Streaming tiled RRDB inference using existing PyTorch/spandrel. Never execute model pickle."""
import hashlib
import json
import math
import subprocess
import sys
from fractions import Fraction
from pathlib import Path
import time

import cv2
import numpy as np
import studio_config as config

FF = config.FFMPEG
FP = config.FFPROBE


def tiled(model, image, tile, padding, device, dtype):
    import torch
    h, w = image.shape[:2]
    scale = model.scale
    output = np.empty((h * scale, w * scale, 3), dtype=np.uint8)
    # Halo pixels provide context. Only tile interiors are copied to avoid seams.
    for y in range(0, h, tile):
        for x in range(0, w, tile):
            right, bottom = min(x + tile, w), min(y + tile, h)
            left_p, top_p = max(0, x - padding), max(0, y - padding)
            right_p, bottom_p = min(w, right + padding), min(h, bottom + padding)
            patch = np.ascontiguousarray(image[top_p:bottom_p, left_p:right_p, ::-1])
            tensor = torch.from_numpy(patch).permute(2, 0, 1).unsqueeze(0).to(device=device, dtype=dtype) / 255.0
            with torch.inference_mode():
                restored = model(tensor).clamp_(0, 1)[0].permute(1, 2, 0).float().cpu().numpy()
            restored = np.rint(restored[:, :, ::-1] * 255).astype(np.uint8)
            output[y*scale:bottom*scale, x*scale:right*scale] = restored[(y-top_p)*scale:(bottom-top_p)*scale, (x-left_p)*scale:(right-left_p)*scale]
    return output


def main(spec):
    config = json.loads(Path(spec).read_text(encoding='utf-8'))
    folder = Path(spec).parent
    source = config['source']
    def progress(message):
        temp = folder / 'progress.tmp'
        temp.write_text(json.dumps({'message': message}, ensure_ascii=False), encoding='utf-8')
        # Windows readers/endpoint scanners can briefly deny replacement.
        # Progress reporting must never abort a completed inference frame.
        for _ in range(10):
            try:
                temp.replace(folder / 'progress.json')
                break
            except PermissionError:
                time.sleep(0.02)
    started = time.monotonic()
    raw = json.loads(subprocess.check_output([FP, '-v', 'error', '-show_streams', '-of', 'json', source]))
    stream = next(s for s in raw['streams'] if s['codec_type'] == 'video')
    rate = Fraction(stream['avg_frame_rate'])
    if not 1 <= float(rate) <= 60:
        raise ValueError('只验收1–60fps恒定帧率短视频')
    if abs(float(rate) - float(Fraction(stream.get('r_frame_rate', str(rate))))) > 0.01:
        raise ValueError('检测到可能的可变帧率，暂不自动改动动作时间；请先规范为恒定帧率底片')
    frames = max(1, math.ceil(config['seconds'] * float(rate) - 1e-3))
    model = None
    if config['mode'] == 'realesrgan':
        progress('加载已验证的Real-ESRGAN x2；不做人脸修复…')
        import torch
        from spandrel import ModelLoader, ImageModelDescriptor
        from studio_enhance import MODEL, PROVENANCE
        record = json.loads(PROVENANCE.read_text(encoding='utf-8'))
        digest = hashlib.sha256(MODEL.read_bytes()).hexdigest()
        if digest != record['sha256']:
            raise ValueError('增强模型校验不符，请重新核验模型来源')
        if not torch.cuda.is_available():
            raise ValueError('CUDA不可用，未自动改用耗时更长的CPU推理')
        free, _ = torch.cuda.mem_get_info()
        if free < 2500 * 1024**2:
            raise ValueError('可用显存不足2.5GB，请先在模型工具页释放空闲引擎')
        torch.set_num_threads(4)
        state = torch.load(MODEL, map_location='cpu', weights_only=True)
        model = ModelLoader().load_from_state_dict(state.get('params_ema', state.get('params', state)))
        if not isinstance(model, ImageModelDescriptor) or model.scale != 2:
            raise ValueError('增强模型架构或倍率与已验证方案不符')
        dtype = torch.float16 if model.supports_half else torch.float32
        model = model.to(device='cuda', dtype=dtype).eval()
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise ValueError('不能解码视频')
    target = Path(config['output'])
    silent = folder / '增强视频流.mp4'
    size = (config['width'], config['height'])
    log = (folder / 'encoder.log').open('wb')
    encoder = subprocess.Popen([FF, '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-s', f'{size[0]}x{size[1]}', '-r', str(rate), '-i', 'pipe:0', '-an', '-c:v', 'libx264', '-preset', 'fast', '-crf', '17', '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(silent)], stdin=subprocess.PIPE, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    count = 0
    try:
        for i in range(frames):
            valid, image = cap.read()
            if not valid:
                break
            base = cv2.resize(image, size, interpolation=cv2.INTER_LANCZOS4)
            if model is not None:
                restored = tiled(model, image, config['tile'], config['overlap'], 'cuda', dtype)
                restored = cv2.resize(restored, size, interpolation=cv2.INTER_AREA)
                # Mix against the same source frame, not neighboring frames (no ghost trails).
                final = cv2.addWeighted(restored, config['strength'], base, 1 - config['strength'], 0)
            else:
                final = base
            encoder.stdin.write(final.tobytes())
            count += 1
            progress(f'逐帧增强 {count}/{frames}；保留原动作与帧率，已用 {time.monotonic()-started:.0f} 秒')
        encoder.stdin.close()
        encoder.wait(timeout=120)
        if encoder.returncode or not count:
            raise RuntimeError('增强编码失败')
    finally:
        cap.release()
        if encoder.poll() is None:
            encoder.kill()
            encoder.wait()
        log.close()
    # Keep original audio without adding or generating any sound.
    mux = [FF, '-v', 'error', '-y', '-i', str(silent), '-i', source, '-map', '0:v:0', '-map', '1:a?', '-c:v', 'copy', '-c:a', 'copy', '-t', str(count / float(rate)), '-movflags', '+faststart', str(target)]
    subprocess.run(mux, check=True, capture_output=True)
    # Identical-size no-AI baseline for judging real improvement, not merely pixel dimensions.
    baseline = folder / '普通等比放大_对照.mp4'
    subprocess.run([FF, '-v', 'error', '-y', '-i', source, '-t', str(count / float(rate)), '-vf', f'scale={size[0]}:{size[1]}:flags=lanczos,setsar=1', '-c:v', 'libx264', '-preset', 'fast', '-crf', '17', '-c:a', 'copy', '-movflags', '+faststart', str(baseline)], check=True, capture_output=True)
    (folder / '增强检验.json').write_text(json.dumps({'frames': count, 'frame_rate': str(rate), 'width': size[0], 'height': size[1], 'elapsed_seconds': round(time.monotonic()-started, 2), 'model_sha256': digest if model else None, 'no_face_restore': True, 'no_interpolation': True, 'warning': '逐帧模型不能保证时序无闪烁或细节绝对不变；应与普通放大对照逐镜验收。'}, ensure_ascii=False, indent=2), encoding='utf-8')
    progress('增强与普通放大对照已完成，原片未改动')


if __name__ == '__main__':
    main(sys.argv[1])
