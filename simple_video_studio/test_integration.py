"""Integration checks use isolated state and a real synthetic reference video."""
import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import studio
import studio_hub as hub
import studio_tools as tools


class StudioIntegration(unittest.TestCase):
    def test_non_loopback_host_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/config',headers={'Host':'untrusted.example'})
        self.assertEqual(caught.exception.code,403)

    def test_first_run_diagnostics(self):
        result=self.request('/api/diagnostics')
        self.assertIn('engines',result)
        self.assertIn('media_ready',result)
        self.assertIn('scope',result)

    def test_cross_site_requests_are_rejected(self):
        for data in [None, {'shots': []}]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/projects',data,{'Sec-Fetch-Site':'cross-site'})
            self.assertEqual(caught.exception.code,403)

    def test_non_object_json_rejected_readably(self):
        for data in [[], 'not an object', 12]:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.request('/api/projects',data)
            self.assertEqual(caught.exception.code,400)
            self.assertIn('JSON',json.load(caught.exception)['error'])

    def test_non_media_and_traversal_reads_are_blocked(self):
        (self.input/'private.json').write_text('{"private":"test"}',encoding='utf-8')
        for path in ['/media/input/private.json','/media/input/../private.json','/media/input/%2e%2e/private.json']:
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(self.url+path,timeout=10)
            self.assertEqual(caught.exception.code,403)

    def test_media_nosniff_and_valid_range(self):
        (self.input/'sample.mp4').write_bytes(b'0123456789')
        req=urllib.request.Request(self.url+'/media/input/sample.mp4',headers={'Range':'bytes=2-4'})
        with urllib.request.urlopen(req,timeout=10) as response:
            self.assertEqual(response.status,206)
            self.assertEqual(response.headers['X-Content-Type-Options'],'nosniff')
            self.assertEqual(response.read(),b'234')

    def test_json_size_limit_rejected(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request('/api/projects',{}, {'Content-Length':str(1024**2+1)})
        self.assertEqual(caught.exception.code,400)

    def test_unsatisfiable_and_invalid_media_ranges(self):
        (self.input/'short.mp4').write_bytes(b'123')
        for value in ['bytes=8-9','bytes=-0','bytes=-','bytes=2-1','bytes=0-1,2-3']:
            req=urllib.request.Request(self.url+'/media/input/short.mp4',headers={'Range':value})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req,timeout=10)
            self.assertEqual(caught.exception.code,416)
        (self.input/'empty.mp4').touch()
        req=urllib.request.Request(self.url+'/media/input/empty.mp4',headers={'Range':'bytes=0-'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req,timeout=10)
        self.assertEqual(caught.exception.code,416)

    def test_invalid_uploads_leave_no_files(self):
        for route,name in [('upload-audio','bad.wav'),('upload-video','bad.mp4')]:
            before=set(self.output.rglob('*'))
            req=urllib.request.Request(self.url+'/api/'+route+'?name='+name,data=b'not media',headers={'Content-Type':'application/octet-stream'})
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(req,timeout=10)
            self.assertEqual(caught.exception.code,400)
            self.assertEqual({p for p in self.output.rglob('*') if p.is_file()}, {p for p in before if p.is_file()})

    def test_upload_name_collision_never_deletes_existing_file(self):
        cases=[('upload-audio','a.wav',self.output/'工作室环境声素材'/'collision.wav'),
               ('upload-video','a.mp4',self.output/'工作室参考视频'/'collision.mp4'),
               ('upload-motion','a.mp4',self.input/studio.UPLOAD_SUBDIR/'motion_collision.mp4')]
        for route,name,target in cases:
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(b'preserve existing file')
            req=urllib.request.Request(self.url+'/api/'+route+'?name='+name,data=b'new upload')
            with patch.object(studio.secrets,'token_hex',return_value='collision'):
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(req,timeout=10)
            self.assertEqual(caught.exception.code,400)
            self.assertEqual(target.read_bytes(),b'preserve existing file')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="yingxu-test-")
        self.root = Path(self.tmp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.input = self.root / "input"
        self.input.mkdir()
        self.patches = [patch.object(studio, "TASK_DIR", self.root / "tasks"), patch.object(studio, "INPUT_ROOT", self.input), patch.object(studio, "OUTPUT_ROOT", self.output), patch.object(hub, "PROJECTS", self.root / "projects"), patch.object(hub, "INPUT", self.input), patch.object(hub, "MEDIA_ROOTS", {"h3": self.output}), patch.object(tools, "JOBS", self.root / "tool_jobs"), patch.object(studio, "comfy_is_ready", return_value=False)]
        for p in self.patches:
            p.start()
        hub._media_cache = (0, [])
        self.server = studio.ThreadingHTTPServer(("127.0.0.1", 0), studio.StudioHandler)
        self.url = "http://127.0.0.1:" + str(self.server.server_port)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def request(self, path, data=None, headers=None):
        raw = json.dumps(data).encode() if data is not None else None
        request = urllib.request.Request(self.url+path, data=raw, headers=headers or {})
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.load(response)

    def test_project_persistence_and_graph_export(self):
        shot = {"id": "shot01", "prompt": "一辆红色小车缓慢驶过雨夜街道", "provider": "local_wan5b", "duration": 2, "mode": "text", "aspect": "16:9", "quality": "draft", "realism_strength": 0.2}
        project = self.request("/api/projects", {"name": "持久化测试", "shots": [dict(shot, api_key="MUST_NOT_SAVE")]})
        saved = self.request("/api/projects")["projects"][0]
        self.assertEqual(saved["id"], project["id"])
        self.assertEqual(saved["shots"][0]["realism_strength"], 0.2)
        self.assertNotIn("api_key", saved["shots"][0])
        compiled = self.request("/api/prepare", shot)
        self.assertEqual(compiled["prompt"]["7"]["class_type"], "Wan22ImageToVideoLatent")
        self.assertEqual(compiled["prompt"]["8"]["inputs"]["steps"], 8)
        h3 = self.request("/api/prepare", dict(shot, provider="local_h3"))
        self.assertEqual(h3["prompt"]["1"]["class_type"], "MiniMaxH3Creator")
        self.assertNotIn("api_key", json.dumps(h3))
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/projects", {"id": "../../escape", "shots": []})
        self.assertEqual(caught.exception.code, 400)

        active = studio.create_task_record(dict(shot, provider="local_h3"))
        studio.update_task(active["id"], status="starting")
        with self.assertRaises(urllib.error.HTTPError) as stopped:
            self.request("/api/engines/stop", {"id": "comfy_stable"})
        self.assertEqual(stopped.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/projects", {"shots": []}, {"Origin": "https://example.com"})
        self.assertEqual(caught.exception.code, 403)

    def test_generation_adapter_and_task_history(self):
        out = self.output / "generated.mp4"
        out.write_bytes(b"test fixture")
        request = {"prompt": "测试动作", "provider": "local_wan5b", "duration": 1, "quality": "draft", "mode": "text", "engine_profile": "comfy_latest"}
        task = studio.create_task_record(request)
        calls = []
        def fake_http(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/prompt"):
                return {"prompt_id": "fake01"}
            return {"fake01": {"status": {"completed": True, "status_str": "success"}, "outputs": {"10": {"gifs": [{"filename": out.name, "subfolder": ""}]}}}}
        with patch.object(studio, "wait_for_comfyui", return_value=True), patch.object(studio, "http_json", side_effect=fake_http):
            studio.run_local_h3(task["id"], request)
        complete = studio.load_task(task["id"])
        self.assertEqual(complete["status"], "completed")
        self.assertIn(":8189/prompt", calls[0][0])
        self.assertEqual(calls[0][1]["payload"]["prompt"]["1"]["class_type"], "UNETLoader")
        self.assertEqual(len(studio.list_tasks()), 1)  # debug request JSON is not a task
        self.assertEqual(complete["compiled_prompt"], request["prompt"])

    def test_project_stops_after_failed_shot(self):
        pairs = [(studio.create_task_record({"provider": "local_h3", "prompt": str(i)})["id"], {}) for i in range(3)]
        def fail(tid, data):
            studio.update_task(tid, status="failed", message="synthetic failure")
        with patch.object(studio, "run_local_h3", side_effect=fail):
            studio.run_project({}, pairs)
        self.assertEqual([studio.load_task(tid)["status"] for tid, _ in pairs], ["failed", "cancelled", "cancelled"])

    def test_cancel_queued_task_does_not_start_engine(self):
        request = {"provider": "local_h3", "prompt": "队列取消测试"}
        task = studio.create_task_record(request)
        cancelled = self.request("/api/tasks/cancel", {"id": task["id"]})
        self.assertEqual(cancelled["status"], "cancelled")
        with patch.object(studio, "wait_for_comfyui") as starter:
            studio.run_local_h3(task["id"], request)
            starter.assert_not_called()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.request("/api/generate", {"provider": "seedance_mini", "prompt": "cloud test"})
        self.assertEqual(caught.exception.code, 400)

    def test_real_video_tools_and_first_frame_reuse(self):
        fixture = self.output / "three_scenes.mp4"
        cmd = [str(tools.FFMPEG), "-y", "-f", "lavfi", "-i", "color=c=red:s=320x192:r=24:d=1", "-f", "lavfi", "-i", "color=c=blue:s=320x192:r=24:d=1", "-f", "lavfi", "-i", "color=c=green:s=320x192:r=24:d=1", "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0[v]", "-map", "[v]", "-map", "3:a", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(fixture)]
        result = tools.subprocess.run(cmd, capture_output=True, timeout=30, creationflags=getattr(tools.subprocess, "CREATE_NO_WINDOW", 0))
        self.assertEqual(result.returncode, 0, result.stderr[-800:])
        info = self.request("/api/tools/probe", {"root": "h3", "path": fixture.name})
        self.assertEqual(info["width"], 320)
        self.assertTrue(info["has_audio"])
        motion_request=urllib.request.Request(self.url+'/api/upload-motion?name=previs.mp4',data=fixture.read_bytes(),headers={'Content-Type':'application/octet-stream'})
        with urllib.request.urlopen(motion_request,timeout=20) as response:
            motion=json.load(response)
        self.assertEqual(motion['kind'],'video')
        self.assertTrue((self.input/motion['input_asset']).is_file())
        before=set(self.input.rglob('motion_*'))
        invalid=urllib.request.Request(self.url+'/api/upload-motion?name=bad.mp4',data=b'not video',headers={'Content-Type':'application/octet-stream'})
        with self.assertRaises(urllib.error.HTTPError):
            urllib.request.urlopen(invalid,timeout=20)
        self.assertEqual(set(self.input.rglob('motion_*')),before)
        asset = self.request("/api/assets/use", {"root": "h3", "path": fixture.name})
        self.assertTrue((self.input / asset["input_asset"]).is_file())
        compiled = self.request("/api/prepare", {"provider": "local_wan5b", "prompt": "继续运动", "mode": "image", "input_asset": asset["input_asset"]})
        self.assertEqual(compiled["prompt"]["7"]["inputs"]["start_image"], ["11", 0])
        for action in ("analyze", "trim", "audio"):
            job = self.request("/api/tools/run", {"root": "h3", "path": fixture.name, "action": action, "duration": 1})
            deadline = time.time()+45
            while time.time()<deadline:
                job = self.request("/api/tools/jobs/"+job["id"])
                if job["status"] in {"completed", "failed"}:
                    break
                time.sleep(.1)
            self.assertEqual(job["status"], "completed", job)
            if action == "analyze":
                self.assertEqual(len(job["shots"]), 3)
                self.assertEqual(len(set(s["input_asset"] for s in job["shots"])), 3)
            else:
                with urllib.request.urlopen(self.url+urllib.parse.quote(job["output_url"], safe="/:")) as response:
                    self.assertGreater(len(response.read()), 100)
        with self.assertRaises(ValueError):
            hub.media_path("h3", "../outside.txt")

    def test_audio_upload_and_mix(self):
        source = self.output / "silent.mp4"
        ambience = self.output / "own.wav"
        tools.subprocess.run([str(tools.FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "color=green:s=160x96:d=2:r=24", "-c:v", "libx264", str(source)], check=True)
        tools.subprocess.run([str(tools.FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:duration=1", str(ambience)], check=True)
        request = urllib.request.Request(self.url + "/api/upload-audio?name=own.wav", data=ambience.read_bytes(), headers={"Content-Type": "application/octet-stream"})
        with urllib.request.urlopen(request, timeout=20) as response:
            asset = json.load(response)
        self.assertTrue((self.output / asset["path"]).is_file())
        job = self.request("/api/tools/run", {"root": "h3", "path": source.name, "action": "mix", "audio_root": asset["root"], "audio_path": asset["path"], "keep_original": False, "gain_db": -12, "offset": 0.1})
        deadline = time.time() + 15
        while time.time() < deadline:
            job = self.request("/api/tools/jobs/" + job["id"])
            if job["status"] in ("completed", "failed"):
                break
            time.sleep(.1)
        self.assertEqual(job["status"], "completed", job)
        self.assertTrue(job["info_after"]["has_audio"])
        self.assertFalse(tools.probe(source)["has_audio"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
