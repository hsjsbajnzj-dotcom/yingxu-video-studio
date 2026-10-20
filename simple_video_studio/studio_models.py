"""ComfyUI API graph for the already installed Wan 2.2 TI2V 5B."""
import secrets


def wan_graph(data, task_id):
    edge = int(data.get("short_edge") or (384 if data.get("quality") == "draft" else 512))
    edge = max(256, min(768, edge)) // 32 * 32
    a, b = map(int, str(data.get("aspect") or "16:9").split(":"))
    width = round(edge * max(1, a / b) / 32) * 32
    height = round(edge * max(1, b / a) / 32) * 32
    seconds = max(1, min(15, int(data.get("duration") or 5)))
    frames = round((seconds * 24 - 1) / 4) * 4 + 1
    seed = int(data.get("seed", -1))
    if seed < 0:
        seed = secrets.randbelow(2**31)
    steps = int(data.get("steps") or {"draft": 8, "balanced": 16, "final": 24}.get(data.get("quality"), 16))
    graph = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "wan2.2_ti2v_5B_fp16.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "umt5_xxl_fp8_e4m3fn_scaled.safetensors", "type": "wan", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": "wan2.2_vae.safetensors"}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": str(data["prompt"])}},
        "5": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": "blurry, oversaturated, plastic skin, deformed hands, static pose, watermark, text, flicker"}},
        "6": {"class_type": "ModelSamplingSD3", "inputs": {"model": ["1", 0], "shift": 8.0}},
        "7": {"class_type": "Wan22ImageToVideoLatent", "inputs": {"vae": ["3", 0], "width": width, "height": height, "length": frames, "batch_size": 1}},
        "8": {"class_type": "KSampler", "inputs": {"model": ["6", 0], "positive": ["4", 0], "negative": ["5", 0], "latent_image": ["7", 0], "seed": seed, "steps": max(4, min(40, steps)), "cfg": 5.0, "sampler_name": "uni_pc", "scheduler": "simple", "denoise": 1.0}},
        "9": {"class_type": "VAEDecode", "inputs": {"samples": ["8", 0], "vae": ["3", 0]}},
        "10": {"class_type": "VHS_VideoCombine", "inputs": {"images": ["9", 0], "frame_rate": 24, "loop_count": 0, "filename_prefix": "统一视频工作室/Wan22/" + task_id, "format": "video/h264-mp4", "pix_fmt": "yuv420p", "crf": 18, "save_metadata": True, "trim_to_audio": False, "pingpong": False, "save_output": True}},
    }
    if data.get("mode") == "image":
        graph["11"] = {"class_type": "LoadImage", "inputs": {"image": data["input_asset"]}}
        graph["7"]["inputs"]["start_image"] = ["11", 0]
    return graph
