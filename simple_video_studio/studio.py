from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import re
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
import studio_hub as hub
from studio_models import wan_graph
import studio_tools as video_tools
import studio_directing as directing
from studio_images import image_assets
import studio_config as config


APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"
DATA_DIR = config.STATE / "data"
TASK_DIR = DATA_DIR / "tasks"
LOG_DIR = config.LOGS

H3_ROOT = config.H3
COMFY_ROOT = Path(hub.ENGINES['comfy_stable']['root'])
COMFY_PYTHON = hub.ENGINES['comfy_stable']['python']
COMFY_URL = config.comfy_url()
INPUT_ROOT = config.INPUT
OUTPUT_ROOT = hub.MEDIA_ROOTS["h3"]
UPLOAD_SUBDIR = Path("simple_video_studio") / "uploads"
OUTPUT_SUBDIR = Path("简易视频工作室")

ARK_BASE_URL = os.environ.get(
    "SEEDANCE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
).rstrip("/")

MODEL_DEFAULTS = {
    "fl2va": "minimax_h3_fl2va_pruned_int8_convrot.safetensors",
    "ref2va": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
    "clip": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
    "vae": "minimax_h3_video_vae_fp16.safetensors",
    "audio_vae": "minimax_h3_audio_vae_fp32.safetensors",
    "sam3": "sam3.1_multiplex_fp16.safetensors",
}

LOCAL_PRESETS = {
    "draft": {
        "label": "快速草稿",
        "steps": 4,
        "short_edge": 384,
        "realism": 0.25,
        "note": "先检查动作和构图，速度最快，细节较少。",
    },
    "balanced": {
        "label": "均衡预览",
        "steps": 12,
        "short_edge": 512,
        "realism": 0.32,
        "note": "检查人物、镜头和节奏，适合大多数迭代。",
    },
    "final": {
        "label": "高质量成片",
        "steps": 20,
        "short_edge": 512,
        "realism": 0.35,
        "note": "质量优先。12 秒在本机实测可能需要约两小时。",
    },
}

PROVIDERS = [
    {
        "id": "local_wan5b", "name": "本地 Wan 2.2 · 5B", "group": "本地模型",
        "description": "使用本机已有权重；支持中文文生视频和首帧图生视频。原生不生成声音，适合动作、构图和短镜头试验。",
        "needs_key": False, "modes": ["text", "image"],
        "duration": {"min": 1, "max": 15}, "resolutions": ["本地原生"],
    },
    {
        "id": "local_h3",
        "name": "本地 MiniMax H3",
        "group": "本地模型",
        "description": "不消耗云端额度；支持中文文生视频、首尾帧、多图参考和本地音画生成。多图参考会使用Ref2VA权重，等待时间与内存占用可能增加。",
        "needs_key": False,
        "modes": ["text", "image"],
        "duration": {"min": 1, "max": 15, "recommended_min": 5},
        "resolutions": ["本地原生"],
    },
    {
        "id": "seedance_standard",
        "name": "Seedance 2.0 标准",
        "group": "云端模型",
        "description": "质量优先；需要火山方舟 API Key，API 额度与豆包免费额度分开。",
        "needs_key": True,
        "model_id": "doubao-seedance-2-0-260128",
        "modes": ["text", "image"],
        "duration": {"min": 4, "max": 15},
        "resolutions": ["480p", "720p", "1080p"],
    },
    {
        "id": "seedance_fast",
        "name": "Seedance 2.0 Fast",
        "group": "云端模型",
        "description": "速度和成本优先；需要火山方舟 API Key。",
        "needs_key": True,
        "model_id": "doubao-seedance-2-0-fast-260128",
        "modes": ["text", "image"],
        "duration": {"min": 4, "max": 15},
        "resolutions": ["480p", "720p"],
    },
    {
        "id": "seedance_mini",
        "name": "Seedance 2.0 Mini",
        "group": "云端模型",
        "description": "低成本试错；是否已获得 API 权限以火山方舟控制台为准。",
        "needs_key": True,
        "model_id": "doubao-seedance-2-0-mini-260615",
        "modes": ["text", "image"],
        "duration": {"min": 4, "max": 15},
        "resolutions": ["480p", "720p"],
    },
    {
        "id": "seedance_custom",
        "name": "Seedance 自定义模型 ID",
        "group": "云端模型",
        "description": "用于今后新版本或你自己的火山方舟 Endpoint。",
        "needs_key": True,
        "model_id": "",
        "modes": ["text", "image"],
        "duration": {"min": 4, "max": 15},
        "resolutions": ["480p", "720p", "1080p"],
    },
]

TASK_LOCK = threading.RLock()
LOCAL_RENDER_LOCK = threading.Lock()
video_tools.studio_audio.GPU_LOCK = LOCAL_RENDER_LOCK
video_tools.studio_enhance.GPU_LOCK = LOCAL_RENDER_LOCK
WORKFLOW_LOCK = threading.Lock()


def local_profile(data: dict[str, Any] | None = None) -> str:
    profile = (data or {}).get("engine_profile", "comfy_stable")
    if profile not in {"comfy_stable", "comfy_latest"}:
        raise ValueError("请选择稳定版或新版 H3 引擎")
    return profile


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def safe_name(value: str, fallback: str = "video") -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]", "_", str(value or "").strip())
    value = re.sub(r"\s+", "_", value).strip("._ ")
    return value[:72] or fallback


def task_path(task_id: str) -> Path:
    return TASK_DIR / f"{safe_name(task_id)}.json"


def save_task(task: dict[str, Any]) -> None:
    with TASK_LOCK:
        TASK_DIR.mkdir(parents=True, exist_ok=True)
        task["updated_at"] = now_iso()
        temp = task_path(task["id"]).with_suffix(".tmp")
        temp.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(task_path(task["id"]))


def load_task(task_id: str) -> dict[str, Any] | None:
    path = task_path(task_id)
    if not path.exists():
        return None
    try:
        with TASK_LOCK:
            return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def list_tasks() -> list[dict[str, Any]]:
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    tasks = []
    for path in TASK_DIR.glob("*.json"):
        try:
            with TASK_LOCK:
                item = json.loads(path.read_text(encoding="utf-8"))
            if "id" in item and "status" in item:
                tasks.append(item)
        except (OSError, json.JSONDecodeError):
            continue
    return sorted(tasks, key=lambda item: item.get("created_at", ""), reverse=True)


def update_task(task_id: str, **changes: Any) -> dict[str, Any] | None:
    with TASK_LOCK:
        task = load_task(task_id)
        if not task:
            return None
        task.update(changes)
        save_task(task)
        return task


def http_json(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    body = None
    request_headers = {"Accept": "application/json"}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json; charset=utf-8"
    if headers:
        request_headers.update(headers)
    request = urllib.request.Request(url, data=body, method=method, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {detail[:1200]}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(str(exc.reason)) from exc
    if not raw:
        return {}
    return json.loads(raw)


def comfy_is_ready(profile: str = "comfy_stable") -> bool:
    return hub.engine_ready(profile)


def start_comfyui(profile: str = "comfy_stable") -> bool:
    return hub.start_engine(profile)


def wait_for_comfyui(timeout: float = 180, profile: str = "comfy_stable") -> bool:
    start_comfyui(profile)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if comfy_is_ready(profile):
            return True
        time.sleep(2)
    return False


def provider_by_id(provider_id: str) -> dict[str, Any]:
    for provider in PROVIDERS:
        if provider["id"] == provider_id:
            return provider
    raise ValueError("未知生成引擎")


def create_task_record(request_data: dict[str, Any]) -> dict[str, Any]:
    task_id = f"{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}"
    public_request = dict(request_data)
    public_request.pop("api_key", None)
    task = {
        "id": task_id,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "status": "queued",
        "progress": 0,
        "message": "任务已创建",
        "provider": request_data.get("provider", "local_h3"),
        "request": public_request,
        "outputs": [],
    }
    save_task(task)
    return task


def build_h3_prompt(data: dict[str, Any]) -> tuple[str, str]:
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("请先用中文描述你想生成的画面和动作")
    mode = data.get("mode", "text")
    continuity = (
        "从上传的首帧准确开始，人物身份、五官比例、发型、服装、道具、空间关系和光线连续稳定。"
        if mode == "image" and data.get("input_asset")
        else "保持主体身份、场景空间、服装和光线在整个镜头中连续稳定。"
    )
    compiled = f"{continuity}\n用户的中文导演指令：{prompt}\n动作衔接和空间关系稳定，运动符合场景的物理规则。"
    if data.get("end_asset"):
        compiled += "\n镜头结束时到达上传尾帧的构图和人物姿态，连续自然地衔接，不把尾帧当普通风格参考。"
    beat = directing.performance(data)
    if any(r.get('kind') == 'video' for r in data.get('reference_assets', []) if isinstance(r, dict)):
        compiled += '\n预演视频仅参考动作轨迹、接触关系、节奏和摄影机运动；外貌、材质与画风采用图片和文字，不采用灰模材质。此能力为实验性引导，不保证逐帧遵循。'
    if beat:
        compiled += "\n可选表演节拍（不覆盖用户指令）：" + beat
    if data.get("realism", True):
        compiled += "人物表情与眼神自然，皮肤和头发保持真实材质；避免蜡像皮肤、油腻HDR、五官漂移和背景融化。"
        global_prompt = "电影写实摄影，人物、光线、材质和环境运动真实自然。用户明确要求的镜头运动、动作和风格优先。"
    else:
        global_prompt = "严格遵循用户指定的画风、主体和镜头语言，保持角色与场景连续性，不擅自改为真人风格。"
    return global_prompt, compiled


def build_h3_creator_data(data: dict[str, Any], task_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    preset_key = str(data.get("quality") or "balanced")
    preset = LOCAL_PRESETS.get(preset_key, LOCAL_PRESETS["balanced"])
    preset = dict(preset)
    if data.get("steps") is not None:
        preset["steps"] = max(4, min(40, int(data["steps"])))
    if data.get("short_edge") is not None:
        preset["short_edge"] = max(256, min(768, int(data["short_edge"]))) // 32 * 32
    duration = max(1, min(15, int(data.get("duration") or 5)))
    aspect = str(data.get("aspect") or "16:9")
    mode = str(data.get("mode") or "text")
    global_prompt, segment_prompt = build_h3_prompt(data)

    assets = image_assets(data)

    realism_enabled = bool(data.get("realism", True))
    loras = []
    strength = float(data.get("realism_strength") if data.get("realism_strength") is not None else preset["realism"])
    if not 0 <= strength <= 0.6:
        raise ValueError("写实 LoRA 强度必须在 0–0.6 之间")
    if realism_enabled and strength > 0:
        loras.append(
            {
                "name": "h3-realism-people-t2v-i2v-r2v.safetensors",
                "strength": strength,
                "triggers": ["r34l1sm"],
            }
        )

    date_folder = datetime.now().strftime("%Y-%m-%d")
    title = safe_name(data.get("title") or prompt_title(data.get("prompt", "")))
    output_prefix = (OUTPUT_SUBDIR / date_folder / f"{task_id}_{title}").as_posix()
    soundscape = directing.soundscape(data)
    generate_audio = bool(data.get("generate_audio", True))
    if generate_audio and not soundscape:
        soundscape = "与画面同步的自然现场声、细微环境声和真实动作声；不要预告片音效。"
    if not generate_audio:
        soundscape = "N/A"

    creator: dict[str, Any] = {
        "version": 2,
        "render": "chained",
        "prompt": global_prompt,
        "aspect": aspect,
        "short_edge": int(preset["short_edge"]),
        "upscale": "direct",
        "sample_edge": int(preset["short_edge"]),
        "refine_denoise": 0.12,
        "face": {"on": False, "canvas": int(preset["short_edge"]), "denoise": 0.16},
        "loras": loras,
        "audio_tail_s": 0.5 if generate_audio else 0.0,
        "output_prefix": output_prefix,
        "models": MODEL_DEFAULTS,
        "segments": [
            {
                "prompt": segment_prompt,
                "soundscape": soundscape,
                "music": "由模型根据情绪生成克制配乐" if generate_audio and data.get("music") else "N/A",
                "assets": assets,
                "loras": [],
                "duration_s": duration,
                "checkpoint": "ref2va" if data.get("reference_assets") else "fl2va",
            }
        ],
    }
    if assets:
        creator["aspect_source"] = "img-1" if aspect == "adaptive" else None
        if creator.get("aspect_source") is None:
            creator.pop("aspect_source", None)

    seed = data.get("seed")
    if seed in (None, "", -1, "-1"):
        seed = secrets.randbelow(2**31 - 1)
    node_payload = {
        "creator_data": json.dumps(creator, ensure_ascii=False, indent=2),
        "seed": int(seed),
        "steps": int(preset["steps"]),
        "cfg": 1.0,
        "sampler_name": "res_multistep",
        "scheduler": "beta",
        "shift_video": 12.0,
        "shift_audio": 3.0,
        "block_cache": "off",
        "spectrum": False,
        "spectrum_blend": 0.5,
        "sage": False,
        "attention": "kitchen",
        "chunk_ffn": True,
        "fp16_accumulation": False,
    }
    return creator, node_payload


def prompt_title(prompt: str) -> str:
    text = re.sub(r"\s+", "", str(prompt or ""))
    return text[:18] or "未命名视频"


def extract_comfy_outputs(history_item: dict[str, Any]) -> list[dict[str, Any]]:
    found = []
    for block in (history_item.get("outputs") or {}).values():
        for key in ("mmc_video", "videos", "gifs", "images"):
            for item in block.get(key, []) or []:
                filename = item.get("filename")
                if not filename:
                    continue
                subfolder = item.get("subfolder") or ""
                path = (OUTPUT_ROOT / subfolder / filename).resolve()
                try:
                    relative = path.relative_to(OUTPUT_ROOT.resolve()).as_posix()
                except ValueError:
                    continue
                found.append(
                    {
                        "kind": "video" if path.suffix.lower() in {".mp4", ".webm", ".mov"} else "image",
                        "name": filename,
                        "relative_path": relative,
                        "media_url": "/media/output/" + urllib.parse.quote(relative, safe="/"),
                    }
                )
    return found


def run_local_h3(task_id: str, data: dict[str, Any]) -> None:
    update_task(task_id, message="等待本地显卡；工作室一次只生成一个任务", progress=0)
    with LOCAL_RENDER_LOCK:
        if (load_task(task_id) or {}).get("status") != "cancelled":
            _run_local_h3(task_id, data)


def _run_local_h3(task_id: str, data: dict[str, Any]) -> None:
    started = time.time()
    try:
        profile = local_profile(data)
        comfy_url = hub.engine_info(profile)["url"]
        update_task(task_id, status="starting", progress=3, message="正在启动本地视频引擎…")
        if not wait_for_comfyui(profile=profile):
            raise RuntimeError("本地引擎没有在三分钟内启动，请在模型与工具中检查日志")
        if (load_task(task_id) or {}).get("status") == "cancelled":
            return
        creator, node_inputs = build_h3_creator_data(data, task_id)
        graph = {
            "1": {
                "inputs": node_inputs,
                "class_type": "MiniMaxH3Creator",
                "_meta": {"title": "简易视频工作室 · MiniMax H3"},
            }
        }
        if data.get("provider") == "local_wan5b":
            graph = wan_graph(data, task_id)
        debug_path = TASK_DIR / f"{task_id}_h3_request.json"
        debug_path.write_text(
            json.dumps({"creator": creator, "prompt": graph}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        with TASK_LOCK:
            if (load_task(task_id) or {}).get("status") == "cancelled":
                return
            result = http_json(f"{comfy_url}/prompt", method="POST", payload={"prompt": graph}, timeout=30)
            prompt_id = result.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI 没有返回任务编号：{result}")
            update_task(
                task_id, status="running", progress=10,
                message="本地模型正在生成。可以离开页面，任务不会中断。",
                engine_task_id=prompt_id,
                compiled_prompt=data["prompt"] if data.get("provider") == "local_wan5b" else creator["segments"][0]["prompt"],
            )
        while True:
            if (load_task(task_id) or {}).get("status") == "cancelled":
                return
            history = http_json(f"{comfy_url}/history/{prompt_id}", timeout=15)
            item = history.get(prompt_id)
            if item:
                status = item.get("status") or {}
                if status.get("completed") or status.get("status_str") == "error":
                    outputs = extract_comfy_outputs(item)
                    if not outputs and status.get("status_str") == "success":
                        raise RuntimeError("引擎结束但没有返回成片，请检查引擎日志")
                    if status.get("status_str") != "success":
                        errors = [m[1].get("exception_message", "") for m in status.get("messages", []) if m[0] == "execution_error"]
                        raise RuntimeError("本地生成失败：" + ("；".join(errors) or str(status.get("status_str"))))
                    if not data.get("generate_audio", True):
                        outputs = video_tools.silent_outputs(outputs, OUTPUT_ROOT)
                    update_task(
                        task_id,
                        status="completed",
                        progress=100,
                        message="生成完成",
                        outputs=outputs,
                        elapsed_seconds=round(time.time() - started, 1),
                    )
                    return
            elapsed = time.time() - started
            update_task(task_id, progress=10, elapsed_seconds=round(elapsed, 1), message=f"正在生成，已等待 {int(elapsed // 60)} 分钟；引擎未报告总进度")
            time.sleep(5)
    except Exception as exc:
        if (load_task(task_id) or {}).get("status") == "cancelled":
            return
        update_task(
            task_id,
            status="failed",
            progress=100,
            message=str(exc),
            elapsed_seconds=round(time.time() - started, 1),
        )


def image_data_uri(input_asset: str) -> str:
    path = (INPUT_ROOT / input_asset).resolve()
    path.relative_to(INPUT_ROOT.resolve())
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def build_seedance_request(data: dict[str, Any]) -> dict[str, Any]:
    provider = provider_by_id(str(data.get("provider")))
    model = str(data.get("custom_model_id") or provider.get("model_id") or "").strip()
    if not model:
        raise ValueError("请填写火山方舟模型 ID 或 Endpoint ID")
    prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("请先填写中文视频提示词")
    duration = max(4, min(15, int(data.get("duration") or 5)))
    resolution = str(data.get("resolution") or "720p")
    if provider["id"] in {"seedance_fast", "seedance_mini"} and resolution == "1080p":
        resolution = "720p"
    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    if data.get("mode") == "image":
        input_asset = str(data.get("input_asset") or "").strip()
        if not input_asset:
            raise ValueError("图生视频模式需要先上传一张首帧图片")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": image_data_uri(input_asset)},
                "role": "first_frame",
            }
        )
    payload: dict[str, Any] = {
        "model": model,
        "content": content,
        "ratio": str(data.get("aspect") or "16:9"),
        "resolution": resolution,
        "duration": duration,
        "generate_audio": bool(data.get("generate_audio", True)),
        "watermark": False,
    }
    seed = data.get("seed")
    if seed not in (None, "", -1, "-1"):
        payload["seed"] = int(seed)
    return payload


def run_seedance(task_id: str, data: dict[str, Any], api_key: str) -> None:
    started = time.time()
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        update_task(task_id, status="starting", progress=5, message="正在提交 Seedance 云端任务…")
        payload = build_seedance_request(data)
        result = http_json(
            f"{ARK_BASE_URL}/contents/generations/tasks",
            method="POST",
            payload=payload,
            headers=headers,
            timeout=90,
        )
        engine_id = result.get("id")
        if not engine_id:
            raise RuntimeError(f"Seedance 没有返回任务编号：{result}")
        update_task(
            task_id,
            status="running",
            progress=12,
            message="Seedance 正在生成，关闭页面也不会中断。",
            engine_task_id=engine_id,
            model_id=payload["model"],
        )
        while True:
            status_result = http_json(
                f"{ARK_BASE_URL}/contents/generations/tasks/{urllib.parse.quote(engine_id)}",
                headers=headers,
                timeout=60,
            )
            status = str(status_result.get("status") or "").lower()
            if status == "succeeded":
                content = status_result.get("content") or {}
                video_url = content.get("video_url")
                if not video_url:
                    raise RuntimeError("Seedance 任务成功，但没有返回视频地址")
                date_folder = datetime.now().strftime("%Y-%m-%d")
                output_dir = OUTPUT_ROOT / OUTPUT_SUBDIR / date_folder
                output_dir.mkdir(parents=True, exist_ok=True)
                title = safe_name(data.get("title") or prompt_title(data.get("prompt", "")))
                output_path = output_dir / f"{task_id}_{title}_Seedance.mp4"
                request = urllib.request.Request(video_url, headers={"User-Agent": "SimpleVideoStudio/1.0"})
                with urllib.request.urlopen(request, timeout=300) as response, output_path.open("wb") as target:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
                relative = output_path.relative_to(OUTPUT_ROOT).as_posix()
                outputs = [
                    {
                        "kind": "video",
                        "name": output_path.name,
                        "relative_path": relative,
                        "media_url": "/media/output/" + urllib.parse.quote(relative, safe="/"),
                    }
                ]
                update_task(
                    task_id,
                    status="completed",
                    progress=100,
                    message="Seedance 生成并保存完成",
                    outputs=outputs,
                    elapsed_seconds=round(time.time() - started, 1),
                )
                return
            if status in {"failed", "cancelled", "expired"}:
                error = status_result.get("error") or {}
                raise RuntimeError(error.get("message") or f"Seedance 任务状态：{status}")
            elapsed = time.time() - started
            update_task(
                task_id,
                progress=min(92, 12 + int(elapsed / 20)),
                message=f"Seedance 状态：{status or '等待中'}",
                elapsed_seconds=round(elapsed, 1),
            )
            time.sleep(10)
    except Exception as exc:
        update_task(
            task_id,
            status="failed",
            progress=100,
            message=str(exc),
            elapsed_seconds=round(time.time() - started, 1),
        )


def validate_request(data):
    provider = provider_by_id(str(data.get("provider") or "local_h3"))
    if not str(data.get("prompt") or "").strip():
        raise ValueError("请填写镜头描述")
    if data.get("mode", "text") not in provider["modes"]:
        raise ValueError("模型不支持当前模式")
    duration = int(data.get("duration") or 5)
    if not provider["duration"]["min"] <= duration <= provider["duration"]["max"]:
        raise ValueError(f"这个模型的时长范围是 {provider['duration']['min']}–{provider['duration']['max']} 秒")
    if provider["needs_key"] and not str(data.get("custom_model_id") or "").strip():
        raise ValueError("请填写火山方舟控制台中实际可用的模型或 Endpoint ID")
    image_assets(data, INPUT_ROOT)
    if provider["id"].startswith("local_"):
        local_profile(data)
        build_h3_creator_data(data, "preflight")
        if provider["id"] == "local_wan5b":
            wan_graph(data, "preflight")
    return provider


def run_project(project, pairs):
    with WORKFLOW_LOCK:
        for task_id, request in pairs:
            if (load_task(task_id) or {}).get("status") == "cancelled":
                continue
            run_local_h3(task_id, request)
            if (load_task(task_id) or {}).get("status") == "failed":
                for following, _ in pairs:
                    if (load_task(following) or {}).get("status") == "queued":
                        update_task(following, status="cancelled", message="前一镜头失败，后续镜头已停止；修正后可重新提交")
                break


class StudioHandler(SimpleHTTPRequestHandler):
    def local_host_allowed(self):
        if len(self.headers.get_all('Host', [])) != 1 or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            self.json_response({'error':'拒绝跨站或含歧义Host的请求'},403)
            return False
        try:
            hostname=urllib.parse.urlsplit('//'+self.headers.get('Host','')).hostname
        except ValueError:
            hostname=None
        if hostname not in {'127.0.0.1','localhost','::1'}:
            self.json_response({'error':'只接受本机回环地址的Host请求'},403)
            return False
        return True

    server_version = "YingxuVideoStudio/2.0"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        super().end_headers()

    def log_message(self, format: str, *args: Any) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with (LOG_DIR / "studio.log").open("a", encoding="utf-8") as log:
            log.write(f"{self.log_date_time_string()} {format % args}\n")

    def json_response(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, limit: int = 1024 * 1024) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > limit:
            raise ValueError("请求内容为空或文件过大")
        value = json.loads(self.rfile.read(length).decode('utf-8'))
        if not isinstance(value, dict):
            raise ValueError('请求顶层必须是JSON对象')
        return value

    def receive_upload(self, target, length):
        with target.open('xb') as output:
            remaining = length
            while remaining:
                chunk = self.rfile.read(min(1024**2, remaining))
                if not chunk:
                    raise ValueError('文件上传未完成')
                output.write(chunk)
                remaining -= len(chunk)

    def do_GET(self) -> None:
        if not self.local_host_allowed():return
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/diagnostics':
            import studio_doctor
            self.json_response(studio_doctor.diagnose())
            return
        if parsed.path.startswith("/api/tools/jobs/"):
            try:
                self.json_response(video_tools.load_job(parsed.path.rsplit("/", 1)[-1]))
            except (ValueError, OSError):
                self.json_response({"error": "工具任务不存在"}, 404)
            return
        if parsed.path == "/api/projects":
            self.json_response({"projects": hub.list_projects()})
            return
        if parsed.path == "/api/engines":
            self.json_response({"engines": [dict(hub.engine_info(e), ready=hub.engine_ready(e)) for e in hub.ENGINES]})
            return
        if parsed.path == "/api/library":
            query = urllib.parse.parse_qs(parsed.query)
            items = hub.library()
            kind = query.get("kind", [""])[0]
            text = query.get("q", [""])[0].lower()
            items = [i for i in items if (not kind or i["kind"] == kind) and (not text or text in i["path"].lower())]
            if query.get("frames", ["0"])[0] != "1":
                items = [i for i in items if not (i["kind"] == "image" and re.fullmatch(r"frame[_\d]*", Path(i["name"]).stem, re.I))]
            self.json_response({"items": items[:240], "total": len(items)})
            return
        if parsed.path == "/api/config":
            self.json_response(
                {
                    "providers": PROVIDERS,
                    "local_presets": LOCAL_PRESETS,
                    "comfy_ready": comfy_is_ready(),
                    "local_models_ready": all(
                        (config.MODELS / folder / name).exists()
                        for folder, name in [
                            ("diffusion_models", MODEL_DEFAULTS["fl2va"]),
                            ("diffusion_models", MODEL_DEFAULTS["ref2va"]),
                            ("text_encoders", MODEL_DEFAULTS["clip"]),
                            ("vae", MODEL_DEFAULTS["vae"]),
                        ]
                    ),
                    "output_root": str(OUTPUT_ROOT),
                    "studio_version": "2.0",
                    "profiles": [hub.engine_info(p) for p in ("comfy_stable", "comfy_latest")],
                }
            )
            return
        if parsed.path == "/api/enhance/status":
            self.json_response(video_tools.studio_enhance.model_status())
            return
        if parsed.path == "/api/health":
            profile = urllib.parse.parse_qs(parsed.query).get("engine_profile", ["comfy_stable"])[0]
            if profile not in {"comfy_stable", "comfy_latest"}:
                self.json_response({"error": "未知本地引擎"}, 400)
                return
            self.json_response({"studio": True, "version": "2.0", "comfy": comfy_is_ready(profile)})
            return
        if parsed.path == "/api/tasks":
            self.json_response({"tasks": list_tasks()})
            return
        if parsed.path.startswith("/api/tasks/"):
            task_id = parsed.path.rsplit("/", 1)[-1]
            task = load_task(task_id)
            self.json_response(task or {"error": "任务不存在"}, 200 if task else 404)
            return
        if parsed.path.startswith(("/media/output/", "/media/library/", "/media/input/")):
            try:
                if parsed.path.startswith("/media/library/"):
                    rid, relative = parsed.path[len("/media/library/"):].split("/", 1)
                    target = hub.media_path(rid, urllib.parse.unquote(relative))
                else:
                    is_input = parsed.path.startswith("/media/input/")
                    prefix = "/media/input/" if is_input else "/media/output/"
                    root = INPUT_ROOT if is_input else OUTPUT_ROOT
                    target = (root / urllib.parse.unquote(parsed.path[len(prefix):])).resolve()
                    target.relative_to(root.resolve())
            except ValueError:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            if not target.is_file():
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            if target.suffix.lower() not in hub.IMAGE_EXT | hub.VIDEO_EXT | video_tools.studio_audio.AUDIO_EXT | {'.bmp'}:
                self.send_error(HTTPStatus.FORBIDDEN)
                return
            mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            total = target.stat().st_size
            range_header = self.headers.get("Range", "")
            start, end = 0, total - 1
            partial = False
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header)
            if range_header and (not match or not total):
                self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                return
            if match:
                left, right = match.groups()
                if left:
                    start = int(left)
                    end = min(int(right), total - 1) if right else total - 1
                elif right:
                    length = min(int(right), total)
                    start, end = total - length, total - 1
                if (not left and not right) or start >= total or end < start:
                    self.send_error(HTTPStatus.REQUESTED_RANGE_NOT_SATISFIABLE)
                    return
                partial = True
            length = end - start + 1
            self.send_response(206 if partial else 200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            if partial:
                self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.end_headers()
            with target.open("rb") as source:
                source.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = source.read(min(1024 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
            return
        super().do_GET()

    def do_POST(self) -> None:
        if not self.local_host_allowed():return
        parsed = urllib.parse.urlparse(self.path)
        try:
            if self.headers.get('Transfer-Encoding') or len(self.headers.get_all('Content-Length', [])) != 1:
                raise ValueError('仅接受带单一Content-Length的请求')
            origin = self.headers.get("Origin")
            if origin and urllib.parse.urlparse(origin).netloc != self.headers.get("Host"):
                self.json_response({"error": "只接受工作室页面提交的请求"}, 403)
                return
            if parsed.path == "/api/open-folder":
                data = self.read_json()
                folders = {"outputs": OUTPUT_ROOT, "logs": LOG_DIR, "archive": config.STATE / "desktop_archive", "projects": hub.PROJECTS}
                if data.get("folder") not in folders:
                    raise ValueError("未知工作室目录")
                folder = folders[data["folder"]]
                folder.mkdir(parents=True, exist_ok=True)
                subprocess.Popen(["explorer.exe", str(folder)])
                self.json_response({"ok": True})
                return
            if parsed.path == "/api/upload-audio":
                length = int(self.headers.get("Content-Length") or 0)
                name = urllib.parse.parse_qs(parsed.query).get("name", ["ambience.wav"])[0]
                ext = Path(name).suffix.lower()
                if not 0 < length <= 50 * 1024**2 or ext not in video_tools.studio_audio.AUDIO_EXT:
                    raise ValueError("请选择不超过50MB的 WAV、MP3、FLAC、M4A、OGG 或 AAC")
                folder = OUTPUT_ROOT / "工作室环境声素材"
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / (secrets.token_hex(8) + ext)
                try:
                    self.receive_upload(target, length)
                    if not video_tools.probe(target)['has_audio']:
                        raise ValueError('文件中没有可读取的音轨')
                except FileExistsError:
                    raise ValueError('上传文件名冲突，请重试；已有文件未改动')
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                self.json_response({"root": "h3", "path": target.relative_to(OUTPUT_ROOT).as_posix()})
                return
            if parsed.path == '/api/upload-motion':
                length = int(self.headers.get('Content-Length') or 0)
                name = urllib.parse.parse_qs(parsed.query).get('name', ['previs.mp4'])[0]
                ext = Path(name).suffix.lower()
                if not 0 < length <= 100 * 1024**2 or ext not in {'.mp4', '.mov', '.webm', '.mkv'}:
                    raise ValueError('请上传不超过100MB且不超过10秒的预演视频')
                folder = INPUT_ROOT / UPLOAD_SUBDIR
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / ('motion_' + secrets.token_hex(10) + ext)
                try:
                    with target.open('xb') as output:
                        remaining = length
                        while remaining:
                            chunk = self.rfile.read(min(1024**2, remaining))
                            if not chunk:
                                raise ValueError('预演视频上传未完成')
                            output.write(chunk)
                            remaining -= len(chunk)
                    info = video_tools.probe(target)
                    if not info.get('width') or not info.get('height') or not 0 < info.get('duration', 0) <= 10.1:
                        raise ValueError('预演必须有画面，且时长不超过10秒')
                except FileExistsError:
                    raise ValueError('上传文件名冲突，请重试；已有文件未改动')
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                self.json_response({'ok': True, 'input_asset': target.relative_to(INPUT_ROOT).as_posix(), 'kind': 'video', 'takes': 'motion', 'info': info})
                return
            if parsed.path == "/api/upload-video":
                length = int(self.headers.get("Content-Length") or 0)
                name = urllib.parse.parse_qs(parsed.query).get("name", ["reference.mp4"])[0]
                ext = Path(name).suffix.lower()
                if not 0 < length <= 1024**3 or ext not in hub.VIDEO_EXT:
                    raise ValueError("请选择不超过1GB的 MP4、MOV、WEBM 或 MKV 视频")
                folder = OUTPUT_ROOT / "工作室参考视频"
                folder.mkdir(parents=True, exist_ok=True)
                target = folder / (secrets.token_hex(8) + ext)
                try:
                    self.receive_upload(target, length)
                    info = video_tools.probe(target)
                    if not info.get('width') or not info.get('height'):
                        raise ValueError('文件中没有可读取的画面')
                except FileExistsError:
                    raise ValueError('上传文件名冲突，请重试；已有文件未改动')
                except Exception:
                    target.unlink(missing_ok=True)
                    raise
                hub._media_cache = (0, [])
                self.json_response({"ok": True, "info": info, "root": "h3", "path": target.relative_to(OUTPUT_ROOT).as_posix(), "name": name, "kind": "video", "url": "/media/library/h3/" + urllib.parse.quote(target.relative_to(OUTPUT_ROOT).as_posix(), safe="/")})
                return
            if parsed.path == "/api/tools/probe":
                data = self.read_json()
                self.json_response(video_tools.probe(hub.media_path(data.get("root"), data.get("path"))))
                return
            if parsed.path == "/api/tools/run":
                self.json_response(video_tools.begin(self.read_json()), 202)
                return
            if parsed.path == "/api/prepare":
                data = self.read_json()
                item = validate_request(data)
                if not item["id"].startswith("local_"):
                    raise ValueError("节点导出适用于本地模型")
                creator, inputs = build_h3_creator_data(data, "export")
                graph = wan_graph(data, "export") if item["id"] == "local_wan5b" else {"1": {"class_type": "MiniMaxH3Creator", "inputs": inputs}}
                self.json_response({"creator": creator, "prompt": graph})
                return
            if parsed.path == "/api/projects":
                self.json_response(hub.save_project(self.read_json()))
                return
            if parsed.path == "/api/projects/run":
                data = self.read_json()
                project = hub.load_project(data.get("id"))
                if not project["shots"]:
                    raise ValueError("先添加至少一个镜头")
                for shot in project["shots"]:
                    if shot.get("provider", "local_h3") not in {"local_h3", "local_wan5b"}:
                        raise ValueError("分镜批量生成当前支持本地 H3 和 Wan 2.2")
                    validate_request(dict(shot, provider=shot.get("provider", "local_h3")))
                    existing = load_task(shot.get("task_id", ""))
                    if existing and existing["status"] in {"queued", "starting", "running"}:
                        raise ValueError("项目已有未完成任务，请等待或先取消")
                pairs = []
                for shot in project["shots"]:
                    request = dict(shot, provider=shot.get("provider", "local_h3"), project_id=project["id"])
                    task = create_task_record(request)
                    shot["task_id"] = task["id"]
                    pairs.append((task["id"], request))
                project = hub.save_project(project)
                threading.Thread(target=run_project, args=(project, pairs), daemon=True).start()
                self.json_response(project, 202)
                return
            if parsed.path == "/api/assets/use":
                self.json_response(hub.use_asset(self.read_json()))
                return
            if parsed.path == "/api/engines/start":
                data = self.read_json()
                engine = hub.engine_info(data.get("id"))
                hub.start_engine(engine["id"])
                self.json_response(dict(engine, ready=hub.engine_ready(engine["id"])))
                return
            if parsed.path == "/api/engines/stop":
                data = self.read_json()
                if any(t["status"] in {"starting", "running"} and t.get("provider", "").startswith("local_") and local_profile(t["request"]) == data.get("id") for t in list_tasks()):
                    raise ValueError("工作室仍有任务在使用这个引擎，请先完成或取消任务")
                self.json_response(hub.stop_idle_engine(data.get("id")))
                return
            if parsed.path == "/api/tasks/cancel":
                data = self.read_json()
                with TASK_LOCK:
                    task = load_task(str(data.get("id") or ""))
                    if not task or task["status"] not in {"queued", "starting", "running"}:
                        raise ValueError("任务不在运行中")
                    if not task.get("provider", "").startswith("local_"):
                        raise ValueError("云端任务请在服务商控制台取消")
                    prompt_id = task.get("engine_task_id")
                    update_task(task["id"], status="cancelled", message="已取消本地任务")
                if prompt_id:
                    url = hub.engine_info(local_profile(task["request"]))["url"]
                    queue = http_json(url + "/queue")
                    if any(row[1] == prompt_id for row in queue.get("queue_running", [])):
                        http_json(url + "/interrupt", method="POST", payload={})
                    else:
                        http_json(url + "/queue", method="POST", payload={"delete": [prompt_id]})
                self.json_response(load_task(task["id"]))
                return
            if parsed.path == "/api/upload":
                data = self.read_json(limit=30 * 1024 * 1024)
                encoded = str(data.get("data") or "")
                match = re.match(r"^data:([^;]+);base64,(.+)$", encoded, re.DOTALL)
                if not match:
                    raise ValueError("上传数据格式不正确")
                mime, payload = match.groups()
                raw = base64.b64decode(payload, validate=True)
                if len(raw) > 20 * 1024 * 1024:
                    raise ValueError("图片不能超过 20MB")
                ext = mimetypes.guess_extension(mime) or Path(str(data.get("name") or "")).suffix or ".png"
                if ext.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                    ext = ".png"
                folder = INPUT_ROOT / UPLOAD_SUBDIR
                folder.mkdir(parents=True, exist_ok=True)
                filename = f"{datetime.now():%Y%m%d_%H%M%S}_{secrets.token_hex(3)}{ext}"
                path = folder / filename
                path.write_bytes(raw)
                relative = path.relative_to(INPUT_ROOT).as_posix()
                self.json_response({"ok": True, "input_asset": relative, "name": filename})
                return
            if parsed.path == "/api/generate":
                data = self.read_json()
                provider = validate_request(data)
                mode = str(data.get("mode") or "text")
                if mode not in provider["modes"]:
                    raise ValueError("这个模型不支持当前创作方式")
                api_key = str(data.get("api_key") or os.environ.get("ARK_API_KEY") or "").strip()
                if provider["needs_key"] and not api_key:
                    raise ValueError("Seedance API 模式需要火山方舟 API Key")
                task = create_task_record(data)
                if provider["id"].startswith("local_"):
                    target = run_local_h3
                    args = (task["id"], data)
                else:
                    target = run_seedance
                    args = (task["id"], data, api_key)
                threading.Thread(target=target, args=args, daemon=True).start()
                self.json_response(task, status=202)
                return
            if parsed.path == "/api/open-output":
                data = self.read_json()
                relative = str(data.get("relative_path") or "")
                target = (OUTPUT_ROOT / relative).resolve()
                target.relative_to(OUTPUT_ROOT.resolve())
                if not target.exists():
                    raise ValueError("输出文件不存在")
                if os.name == "nt":
                    subprocess.Popen(["explorer.exe", "/select,", str(target)])
                self.json_response({"ok": True})
                return
            if parsed.path == "/api/start-comfy":
                data = self.read_json()
                profile = local_profile(data)
                self.json_response({"started": start_comfyui(profile), "ready": comfy_is_ready(profile)})
                return
            self.json_response({"error": "接口不存在"}, 404)
        except (ValueError, json.JSONDecodeError) as exc:
            self.json_response({"error": str(exc)}, 400)
        except Exception as exc:
            self.json_response({"error": str(exc)}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="简易视频工作室")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument('--doctor',action='store_true',help='检查依赖和配置，不启动模型或网页服务')
    parser.add_argument("--port", type=int, default=7865)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-comfy", action="store_true")
    args = parser.parse_args()
    if args.doctor:
        import studio_doctor
        report=studio_doctor.diagnose()
        print(json.dumps(report,ensure_ascii=False,indent=2))
        return
    if args.host not in {'127.0.0.1', 'localhost'}:
        parser.error('社区预览版仅允许回环地址，不支持公网或局域网服务')
    if not 1 <= args.port <= 65535:
        parser.error('网页端口必须为1–65535整数')
    for folder in (DATA_DIR, TASK_DIR, LOG_DIR, INPUT_ROOT / UPLOAD_SUBDIR, OUTPUT_ROOT / OUTPUT_SUBDIR):
        folder.mkdir(parents=True, exist_ok=True)
    # Engines start on demand, so opening the studio does not load four GPU apps.
    url = f"http://{args.host}:{args.port}"
    server = ThreadingHTTPServer((args.host, args.port), StudioHandler)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    print(f"简易视频工作室已启动：{url}")
    print("按 Ctrl+C 可以关闭网页服务；已经提交的 ComfyUI 任务不会因此中断。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
