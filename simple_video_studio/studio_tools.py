"""CPU video utilities; jobs do not load a diffusion model."""
import json
import secrets
import subprocess
import sys
import threading
import urllib.parse
from pathlib import Path

import studio_hub as hub
import studio_audio
import studio_enhance
import studio_config as config

FFMPEG = Path(config.FFMPEG)
FFPROBE = Path(config.FFPROBE)
JOBS = config.STATE / "data" / "tool_jobs"
TOOL_LOCK = threading.Lock()
JOB_LOCK = threading.RLock()


def silent_outputs(outputs, root):
    result = []
    for item in outputs:
        item = dict(item)
        if item.get("kind") == "video":
            source = (root / item["relative_path"]).resolve()
            source.relative_to(root.resolve())
            if probe(source)["has_audio"]:
                target = source.with_name(source.stem + "_silent.mp4")
                done = subprocess.run([str(FFMPEG), "-v", "error", "-y", "-i", str(source), "-map", "0:v:0", "-c:v", "copy", "-an", str(target)], capture_output=True, timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if done.returncode or probe(target)["has_audio"]:
                    raise RuntimeError("静音导出失败，原片已保留")
                relative = target.relative_to(root.resolve()).as_posix()
                item.update(name=target.name, relative_path=relative, media_url="/media/output/" + urllib.parse.quote(relative, safe="/"))
        result.append(item)
    return result


def probe(path):
    try:
        result = subprocess.run([str(FFPROBE), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)], capture_output=True, timeout=35, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except FileNotFoundError as exc:
        raise ValueError('未找到FFprobe，请安装FFmpeg工具并在config.local.json填写tools.ffprobe') from exc
    if result.returncode:
        raise ValueError("无法读取视频信息，请检查文件格式")
    raw = json.loads(result.stdout)
    video = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), {})
    return {"width": video.get("width"), "height": video.get("height"), "codec": video.get("codec_name"), "frame_rate": video.get("avg_frame_rate"), "duration": float(raw.get("format", {}).get("duration", 0)), "bit_rate": raw.get("format", {}).get("bit_rate"), "has_audio": any(s.get("codec_type") == "audio" for s in raw.get("streams", []))}


def job_path(jid):
    return JOBS / (hub.project_id(jid) + ".json")


def save_job(data):
    with JOB_LOCK:
        JOBS.mkdir(parents=True, exist_ok=True)
        path = job_path(data["id"])
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        temp.replace(path)


def load_job(jid):
    with JOB_LOCK:
        return json.loads(job_path(jid).read_text(encoding="utf-8"))


def begin(data):
    source = hub.media_path(str(data.get("root")), str(data.get("path")))
    if source.suffix.lower() not in hub.VIDEO_EXT:
        raise ValueError("请选择一个视频")
    action = data.get("action", "analyze")
    if action not in {"analyze", "trim", "audio", "ambience", "mix", "enhance"}:
        raise ValueError("未知视频工具")
    job = {"id": secrets.token_hex(8), "status": "queued", "message": "等待视频工具", "source": source.name, "action": action}
    save_job(job)
    threading.Thread(target=run, args=(job, source, data), daemon=True).start()
    return job


def run(job, source, data):
    with TOOL_LOCK:
        try:
            job.update(status="running", message="正在读取视频…")
            save_job(job)
            info = probe(source)
            folder = hub.MEDIA_ROOTS["h3"] / "工作室视频工具" / job["id"]
            folder.mkdir(parents=True, exist_ok=True)
            if job["action"] == "enhance":
                def update(message):
                    job.update(message=message)
                    save_job(job)
                target, config = studio_enhance.enhance(source, folder, data, info, update)
                method_note = ('FlashVSR系列隔离试验；模型画布' + '×'.join(map(str, config.get('native_canvas', []))) + '，交付尺寸经适配；不是原生1080摄影。' if config['mode'].startswith('flashvsr_') else 'SeedVR2 1秒分段时序试验；完整短片尚未验收。' if config['mode'] == 'seedvr2_preview' else '普通等比放大，未运行AI细节增强；' if config['mode'] == 'resize' else '保守逐帧增强；')
                def media_url(path):
                    return '/media/library/h3/' + urllib.parse.quote(path.relative_to(hub.MEDIA_ROOTS['h3']).as_posix(), safe='/')
                job.update(output_url=media_url(target), source_url=media_url(source) if source.is_relative_to(hub.MEDIA_ROOTS['h3']) else '/media/library/' + str(data['root']) + '/' + urllib.parse.quote(data['path'], safe='/'), baseline_url=media_url(folder / '普通等比放大_对照.mp4'), info_after=probe(target), config=config,
                           analysis_note=method_note + '原片未修改，无补帧、换脸或新声音。普通放大对照不含AI；请检查毛发、树叶、衣褶与文字闪烁。')
            elif job["action"] in {"ambience", "mix"}:
                if job["action"] == "ambience":
                    def update(message):
                        job.update(message=message)
                        save_job(job)
                    audio = studio_audio.generate(source, data, folder, info["duration"], update)
                else:
                    audio = hub.media_path(str(data.get("audio_root")), str(data.get("audio_path")))
                    if audio.suffix.lower() not in studio_audio.AUDIO_EXT:
                        raise ValueError("请选择音频素材")
                target = folder / "环境声混音.mp4"
                studio_audio.mix(source, target, audio, info["duration"], gain_db=data.get("gain_db", -12), offset=data.get("offset", 0), keep_original=bool(data.get("keep_original", True)) and info["has_audio"])
                asset_root = "h3" if job["action"] == "ambience" else str(data["audio_root"])
                job["audio_asset"] = {"root": asset_root, "path": audio.relative_to(hub.MEDIA_ROOTS[asset_root]).as_posix()}
                job["audio_url"] = "/media/library/" + asset_root + "/" + urllib.parse.quote(job["audio_asset"]["path"], safe="/")
                job["output_url"] = "/media/library/h3/" + urllib.parse.quote(target.relative_to(hub.MEDIA_ROOTS["h3"]).as_posix(), safe="/")
                job["info_after"] = probe(target)
                job["analysis_note"] = "独立环境音床已保留；不是逐帧拟音或可辨认对白，需试听和校准。视频流未重编码。"
            elif job["action"] == "analyze":
                try:
                    from scenedetect import detect, ContentDetector
                except ImportError as exc:
                    raise ValueError('拆镜组件未安装，请在网页环境安装requirements-media.txt；无需复制vendor目录') from exc
                job.update(message="正在检测前 3 分钟的镜头切点…")
                save_job(job)
                stop = min(info["duration"], 180.0)
                detected = detect(str(source), ContentDetector(threshold=27.0), start_in_scene=True, end_time=stop)
                scenes = [(a.seconds, b.seconds) for a, b in detected][:24]
                if not scenes:
                    scenes = [(0, stop)]
                shots = []
                for i, (start, end) in enumerate(scenes):
                    frame = folder / f"镜头_{i+1:02d}.png"
                    cmd = [str(FFMPEG), "-y", "-ss", str(min(start + 0.1, end)), "-i", str(source), "-frames:v", "1", "-vf", "scale='min(960,iw)':-2", str(frame)]
                    result = subprocess.run(cmd, capture_output=True, timeout=40, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    if result.returncode:
                        raise RuntimeError("参考帧提取失败")
                    relative = frame.relative_to(hub.MEDIA_ROOTS["h3"]).as_posix()
                    asset = hub.use_asset({"root": "h3", "path": relative})
                    shots.append({"index": i+1, "start": round(start, 3), "end": round(end, 3), "duration": round(end-start, 3), "frame_url": "/media/library/h3/" + relative, "input_asset": asset["input_asset"]})
                    job["message"] = f"正在提取独立参考图 {i+1}/{len(scenes)}"
                    save_job(job)
                job["shots"] = shots
                job["analysis_note"] = "分析前3分钟，最多24个镜头；只检测剪切与提取画面，不会自动识别剧情。"
                (folder / "分镜时间表.json").write_text(json.dumps(shots, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                if job["action"] == "trim":
                    start = max(0, float(data.get("start", 0)))
                    duration = max(0.1, min(float(data.get("duration", 5)), info["duration"] - start))
                    if start >= info["duration"]:
                        raise ValueError("起始时间超出了视频长度")
                    target = folder / "剪取片段.mp4"
                    cmd = [str(FFMPEG), "-y", "-ss", str(start), "-i", str(source), "-t", str(duration), "-c:v", "libx264", "-preset", "fast", "-crf", "18", "-c:a", "aac", str(target)]
                else:
                    if not info["has_audio"]:
                        raise ValueError("这个视频没有音轨")
                    target = folder / "原片声音.wav"
                    cmd = [str(FFMPEG), "-y", "-i", str(source), "-vn", "-c:a", "pcm_s16le", str(target)]
                result = subprocess.run(cmd, capture_output=True, timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode:
                    raise RuntimeError("视频工具处理失败")
                job["output_url"] = "/media/library/h3/" + target.relative_to(hub.MEDIA_ROOTS["h3"]).as_posix()
            job.update(status="completed", message="处理完成", info=info)
            hub._media_cache = (0, [])
        except Exception as exc:
            job.update(status="failed", message=str(exc))
        save_job(job)
