"""Local MMAudio ambience and CPU-only, non-destructive soundtrack mixing."""
import json
import math
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path
import studio_hub as hub
from studio_directing import AMBIENCES
import studio_config as config

GPU_LOCK = threading.Lock()  # replaced with the studio render lock by studio.py
FFMPEG = Path(config.FFMPEG)
AUDIO_EXT = {".wav", ".mp3", ".flac", ".m4a", ".ogg", ".aac"}


def request(path, data=None):
    body = None if data is None else json.dumps(data).encode()
    req = urllib.request.Request(config.comfy_url() + path, body, {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as response:
        raw = response.read()
        return json.loads(raw) if raw.strip() else {}


def graph(duration, prompt, prefix, seed=1701):
    return {
        "1": {"class_type": "MMAudioModelLoader", "inputs": {"mmaudio_model": "mmaudio_large_44k_v2_fp16.safetensors", "base_precision": "fp16"}},
        "2": {"class_type": "MMAudioFeatureUtilsLoader", "inputs": {"vae_model": "mmaudio_vae_44k_fp16.safetensors", "synchformer_model": "mmaudio_synchformer_fp16.safetensors", "clip_model": "apple_DFN5B-CLIP-ViT-H-14-384_fp16.safetensors", "mode": "44k", "precision": "fp16"}},
        "3": {"class_type": "MMAudioSampler", "inputs": {"mmaudio_model": ["1", 0], "feature_utils": ["2", 0], "duration": duration, "steps": 25, "cfg": 4.5, "seed": seed, "prompt": prompt, "negative_prompt": "music, narration, intelligible speech, distortion, harsh clipping", "mask_away_clip": False, "force_offload": True}},
        "4": {"class_type": "SaveAudio", "inputs": {"audio": ["3", 0], "filename_prefix": prefix}},
    }


def generate(source, data, folder, duration, update):
    if not config.feature('mmaudio'):
        raise ValueError('本地环境音生成为可选功能，尚未配置MMAudio；可先导入现有音频混音')
    if not 1 <= duration <= 10.5:
        raise ValueError("环境音补配目前只验收1–10秒视频（允许帧数对齐的小幅偏差）")
    preset = str(data.get("ambience") or "night_street")
    if preset not in AMBIENCES or preset == "none":
        raise ValueError("请选择一个环境声预设")
    prompt = str(data.get("audio_prompt") or AMBIENCES[preset][2]).strip()
    if not prompt or len(prompt) > 2000:
        raise ValueError("声音提示词长度必须为1–2000字符")
    prefix = (folder.relative_to(hub.MEDIA_ROOTS["h3"]) / "AMB_环境音床").as_posix()
    with GPU_LOCK:
        update("等待本地环境音引擎；不与视频推理同时占显存…")
        hub.start_engine("comfy_stable")
        deadline = time.monotonic() + 180
        while not hub.engine_ready("comfy_stable"):
            if time.monotonic() > deadline:
                raise RuntimeError("环境音引擎启动超时")
            time.sleep(2)
        queue = request("/queue")
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise ValueError("ComfyUI中仍有其他任务，请完成后再补环境音")
        request("/free", {"unload_models": True, "free_memory": True})
        prompt_graph = graph(duration, prompt, prefix)
        (folder / "环境音生成方案.json").write_text(json.dumps({"prompt": prompt_graph, "note": "仅文字生成环境音床，不识别或自动同步画面动作"}, ensure_ascii=False, indent=2), encoding="utf-8")
        submitted = request("/prompt", {"prompt": prompt_graph})
        pid = submitted.get("prompt_id")
        if not pid:
            raise RuntimeError("环境音节点校验失败：" + str(submitted.get("node_errors", submitted)))
        update("MMAudio正在生成独立环境音床；不保证精确动作同步…")
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            item = request("/history/" + pid).get(pid)
            if item:
                status = item.get("status", {})
                if status.get("status_str") == "error":
                    errors = [v.get("exception_message", "") for k, v in status.get("messages", []) if k == "execution_error"]
                    raise RuntimeError("环境音生成失败：" + "; ".join(errors))
                if status.get("completed"):
                    for block in item.get("outputs", {}).values():
                        for value in block.get("audio", []):
                            output = (hub.MEDIA_ROOTS["h3"] / value.get("subfolder", "") / value["filename"]).resolve()
                            output.relative_to(hub.MEDIA_ROOTS["h3"].resolve())
                            if output.is_file():
                                return output
                    raise RuntimeError("引擎完成但没有返回环境音文件")
            time.sleep(3)
        running = request("/queue").get("queue_running", [])
        if any(row[1] == pid for row in running):
            request("/interrupt", {})
        else:
            request("/queue", {"delete": [pid]})
        raise TimeoutError("环境音超过20分钟安全时限，已请求取消本次任务")


def mix(source, target, audio, duration, *, gain_db=-12, offset=0, keep_original=True, original_gain_db=0):
    values = [float(gain_db), float(offset), float(original_gain_db), float(duration)]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("混音参数必须为有限数字")
    gain, start, original_gain, length = values
    if not -60 <= gain <= 6 or not -60 <= original_gain <= 6 or not 0 <= start < length:
        raise ValueError("混音增益或入点超出范围")
    delay = round(start * 1000)
    chain = f"[1:a:0]aresample=48000,volume={gain}dB,afade=t=in:d=0.08,adelay={delay}|{delay},apad,atrim=duration={length},afade=t=out:st={max(0,length-.12)}:d=0.12[amb]"
    if keep_original:
        chain += f";[0:a:0]aresample=48000,volume={original_gain}dB[orig];[orig][amb]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.89:level=0:latency=1[a]"
    else:
        chain += ";[amb]alimiter=limit=0.89:level=0:latency=1[a]"
    cmd = [str(FFMPEG), "-v", "error", "-y", "-i", str(source), "-i", str(audio), "-filter_complex", chain,
           "-map", "0:v:0", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-t", str(length), str(target)]
    completed = subprocess.run(cmd, capture_output=True, timeout=180, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if completed.returncode:
        raise RuntimeError("音轨混合失败：" + completed.stderr.decode("utf-8", "replace")[-500:])
