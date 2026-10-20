"""Local engine catalogue, durable shot projects, and shared media library."""
from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
import studio_config as config

APP = Path(__file__).resolve().parent
PROJECTS = config.STATE / "data" / "projects"
PROJECT_LOCK = threading.RLock()
START_LOCK = threading.Lock()
ENGINES = config.engines()
MEDIA_ROOTS = config.MEDIA
INPUT = config.INPUT
VIDEO_EXT = {".mp4", ".webm", ".mov", ".mkv"}
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
_media_cache = (0.0, [])


def engine_info(engine_id):
    if engine_id not in ENGINES:
        raise ValueError("未知本地引擎")
    engine = dict(ENGINES[engine_id], id=engine_id)
    engine["url"] = f"http://127.0.0.1:{engine['port']}"
    root=Path(engine['root'])
    entry=root / ('main.py' if engine['kind']=='comfy' else 'app/wgp.py')
    engine["installed"] = bool(engine.get("configured", False) and entry.is_file() and engine.get('python') and Path(engine['python']).is_file())
    return engine


def engine_ready(engine_id):
    engine = engine_info(engine_id)
    if not engine.get('installed'):
        return False
    try:
        path = "/system_stats" if engine["kind"] == "comfy" else "/config"
        with urllib.request.urlopen(engine["url"] + path, timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def prepare_comfy_preferences(root, source=None):
    """Seed new-user export preferences once; never overwrite a user's edits."""
    source = Path(source) if source is not None else Path(ENGINES['comfy_stable']['base_directory']) / 'user/minimax_creator.settings.json'
    user = Path(root) / "user"
    user.mkdir(parents=True, exist_ok=True)
    target = user / "minimax_creator.settings.json"
    if not target.exists() and source.is_file():
        shutil.copy2(source, target)


def start_engine(engine_id):
    with START_LOCK:
        if engine_ready(engine_id):
            return True
        engine = engine_info(engine_id)
        root = Path(engine["root"])
        if not engine["installed"]:
            raise ValueError("请先在config.local.json配置引擎目录和独立Python环境；工作室不会自动下载模型")
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONUTF8"] = "1"
        env["CUDA_MODULE_LOADING"] = "LAZY"
        env["PATH"] = str(Path(config.FFMPEG).parent) + os.pathsep + env.get("PATH", "")
        python = Path(engine.get('python') or '')
        if not engine.get('python') or not python.is_file():
            raise ValueError("请配置该引擎已有的Python路径；不要使用网页服务环境代替GPU引擎环境")
        if engine["kind"] == "comfy":
            args = [str(python), "main.py", "--base-directory", engine['base_directory'], "--listen", "127.0.0.1", "--port", str(engine["port"]), "--models-directory", str(config.MODELS), "--input-directory", str(INPUT), "--output-directory", str(MEDIA_ROOTS["h3"]), "--preview-method", "none", "--cache-none", "--reserve-vram", "0.5"]
            env["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
            if engine_id == "comfy_latest":
                prepare_comfy_preferences(root)
                # Keep compatibility fixes in the new engine, not shared nodes.
                if (root / "py_overlay").is_dir():env["PYTHONPATH"] = str(root / "py_overlay")
                args += ["--user-directory", str(root / "user")]
            cwd = root
        else:
            if engine_id == "wangp_latest":
                if (root / "py_overlay").is_dir():env["PYTHONPATH"] = str(root / "py_overlay")
            args = [str(python), "wgp.py", "--server-name", "127.0.0.1", "--server-port", str(engine["port"]), "--profile", "5", "--attention", "sdpa", "--config", str(root / "config"), "--settings", str(root / "settings"), "--advanced"]
            cwd = root / "app"
            env["HF_HOME"] = str(config.STATE / 'cache/huggingface')
            env["GRADIO_ANALYTICS_ENABLED"] = "False"
            git_candidates = list(Path(os.environ.get("LOCALAPPDATA", "" )).glob("GitHubDesktop/app-*/resources/app/git/cmd/git.exe"))
            if git_candidates:
                git = sorted(git_candidates)[-1]
                env["GIT_PYTHON_GIT_EXECUTABLE"] = str(git)
                env["PATH"] = str(git.parent) + os.pathsep + env.get("PATH", "")
        if not python.is_file():
            raise ValueError("找不到已有 Python 运行环境")
        logs = config.LOGS
        logs.mkdir(parents=True, exist_ok=True)
        pidfile = logs / f"{engine_id}.pid"
        if pidfile.exists() and time.time() - pidfile.stat().st_mtime < 150:
            # A recent launcher may still be importing GPU libraries.
            pid = int(pidfile.read_text().strip())
            import psutil
            if psutil.pid_exists(pid):
                try:
                    running=psutil.Process(pid)
                    if running.cwd()==str(cwd) and str(engine['port']) in running.cmdline():return True
                except (psutil.Error,OSError):pass
        with (logs / f"{engine_id}.log").open("a", encoding="utf-8") as log:
            proc = subprocess.Popen(args, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        pidfile.write_text(str(proc.pid))
        return True


def project_id(value):
    value = str(value)
    if not value or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in value):
        raise ValueError("项目编号无效")
    return value


def stop_idle_engine(engine_id):
    engine = engine_info(engine_id)
    if engine["kind"] != "comfy":
        raise ValueError("WanGP 请在完整工作台中确认任务后关闭")
    if engine_ready(engine_id):
        with urllib.request.urlopen(engine["url"] + "/queue", timeout=4) as response:
            queue = json.load(response)
        if queue.get("queue_running") or queue.get("queue_pending"):
            raise ValueError("引擎还有生成任务，请先完成或取消任务")
    pidfile = config.LOGS / (engine_id + ".pid")
    if not pidfile.is_file():
        raise ValueError("此引擎不是统一工作室启动的，请从原来的窗口关闭")
    import psutil
    try:
        parent = psutil.Process(int(pidfile.read_text().strip()))
        args = parent.cmdline()
        port_index = args.index('--port') if '--port' in args else -1
        root = Path(engine['root']).resolve()
        script_matches = any(Path(a).name == 'main.py' for a in args[1:])
        if (port_index < 0 or port_index+1 >= len(args) or args[port_index+1] != str(engine['port'])
                or Path(parent.cwd()).resolve() != root or not script_matches):
            raise ValueError("引擎进程已变化，请刷新状态")
        processes = parent.children(recursive=True) + [parent]
        for process in processes:
            process.terminate()
        _, alive = psutil.wait_procs(processes, timeout=3)
        for process in alive:
            process.kill()
    except psutil.NoSuchProcess:
        pass
    return {"ok": True, "id": engine_id}


def load_project(value):
    path = PROJECTS / (project_id(value) + ".json")
    if not path.is_file():
        raise ValueError("项目不存在")
    with PROJECT_LOCK:
        return json.loads(path.read_text(encoding="utf-8"))


def save_project(data):
    with PROJECT_LOCK:
        PROJECTS.mkdir(parents=True, exist_ok=True)
        pid = project_id(data.get("id") or (datetime.now().strftime("%Y%m%d_") + secrets.token_hex(4)))
        shots = data.get("shots", [])
        if not isinstance(shots, list) or len(shots) > 64:
            raise ValueError("每个项目最多 64 个镜头")
        allowed = {"id", "title", "prompt", "mode", "input_asset", "end_asset", "reference_assets", "duration", "aspect", "quality", "engine_profile", "soundscape", "ambience", "performance", "generate_audio", "music", "realism", "realism_strength", "seed", "task_id", "steps", "short_edge", "provider"}
        clean = [{key: value for key, value in shot.items() if key in allowed} for shot in shots]
        result = {"id": pid, "name": str(data.get("name") or "未命名项目")[:100], "notes": str(data.get("notes") or "")[:12000], "shots": clean, "updated_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        path = PROJECTS / (pid + ".json")
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
        return result


def list_projects():
    PROJECTS.mkdir(parents=True, exist_ok=True)
    result = []
    for file in PROJECTS.glob("*.json"):
        try:
            with PROJECT_LOCK:
                result.append(json.loads(file.read_text(encoding="utf-8")))
        except (ValueError, OSError):
            continue
    return sorted(result, key=lambda p: p.get("updated_at", ""), reverse=True)


def media_path(root_id, relative):
    if root_id not in MEDIA_ROOTS:
        raise ValueError("未知素材目录")
    root = MEDIA_ROOTS[root_id].resolve()
    target = (root / relative).resolve()
    target.relative_to(root)
    if not target.is_file():
        raise ValueError("素材文件不存在")
    return target


def library():
    global _media_cache
    if time.time() - _media_cache[0] < 30:
        return _media_cache[1]
    found = []
    for rid, root in MEDIA_ROOTS.items():
        if not root.is_dir():
            continue
        for directory, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d not in {".cache", "__pycache__", "temp"}]
            for name in files:
                if name == '增强视频流.mp4':
                    continue  # internal intermediate, never present as a finished clip
                path = Path(directory) / name
                if path.suffix.lower() not in VIDEO_EXT | IMAGE_EXT:
                    continue
                try:
                    stat = path.stat()
                    relative = path.relative_to(root).as_posix()
                    found.append({"root": rid, "path": relative, "name": name, "kind": "video" if path.suffix.lower() in VIDEO_EXT else "image", "bytes": stat.st_size, "modified": stat.st_mtime, "url": "/media/library/" + rid + "/" + urllib.parse.quote(relative, safe="/")})
                except OSError:
                    continue
    found.sort(key=lambda x: x["modified"], reverse=True)
    _media_cache = (time.time(), found)
    return found


def use_asset(data):
    source = media_path(str(data.get("root")), str(data.get("path")))
    dest_dir = INPUT / "simple_video_studio" / "uploads"
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = datetime.now().strftime("%Y%m%d_%H%M%S_") + secrets.token_hex(3)
    if source.suffix.lower() in IMAGE_EXT:
        target = dest_dir / (name + source.suffix.lower())
        shutil.copy2(source, target)
    elif source.suffix.lower() in VIDEO_EXT:
        target = dest_dir / (name + ".png")
        ffmpeg = Path(config.FFMPEG)
        args = [str(ffmpeg), "-y", "-sseof", "-0.15", "-i", str(source), "-frames:v", "1", str(target)]
        result = subprocess.run(args, capture_output=True, timeout=40, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode or not target.is_file():
            raise ValueError("未能提取视频尾帧，请选择图片素材")
    else:
        raise ValueError("仅支持图片或视频素材")
    relative = target.relative_to(INPUT).as_posix()
    return {"input_asset": relative, "url": "/media/input/" + urllib.parse.quote(relative, safe="/"), "name": target.name}
