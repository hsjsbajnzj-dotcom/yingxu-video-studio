import unittest
from pathlib import Path
from unittest.mock import patch
import studio
import studio_enhance as enhance


class EnhanceControls(unittest.TestCase):
    def test_gpu_lock_shared(self):
        self.assertIs(enhance.GPU_LOCK, studio.LOCAL_RENDER_LOCK)

    def test_preserve_aspect_and_preview(self):
        base = dict(width=992, height=576, duration=5.166667)
        config = enhance.settings({}, base)
        self.assertEqual((config['width'], config['height']), (1860, 1080))
        self.assertEqual(config['seconds'], 1)
        config = enhance.settings(dict(preview_only=False), base)
        self.assertEqual(config['seconds'], base['duration'])
        portrait = enhance.settings({}, dict(width=512, height=896, duration=5))
        self.assertEqual((portrait['width'], portrait['height']), (1080, 1890))

    def test_limits(self):
        info = dict(width=992, height=576, duration=5)
        for data in [dict(enhance_strength=float('nan')), dict(enhance_strength=1), dict(target_height=2160), dict(enhance_mode='seedvr_unverified'), dict(preview_only='false')]:
            with self.assertRaises(ValueError):
                enhance.settings(data, info)
        for info in [dict(width=0, height=576, duration=5), dict(width=992, height=576, duration=60), dict(width=1920, height=1080, duration=5)]:
            with self.assertRaises(ValueError):
                enhance.settings({}, info)

    def test_seedvr_is_preview_only(self):
        for mode in ('seedvr2_preview', 'flashvsr_plus_preview', 'flashvsr_v1_preview'):
            with self.assertRaises(ValueError):
                enhance.settings(dict(enhance_mode=mode, preview_only=False), dict(width=992, height=576, duration=5))

    def test_flash_canvas_bounds(self):
        import studio_flashvsr
        for info in [dict(width=992, height=576), dict(width=512, height=896), dict(width=1344, height=576)]:
            w, h = studio_flashvsr.canvas(info, 1080)
            self.assertEqual(w % 128, 0)
            self.assertEqual(h % 128, 0)
            self.assertLessEqual(w*h, 2000000)
            self.assertLessEqual(max(w, h), 1920)

    def test_resize_keeps_audio_fps_and_duration(self):
        import json
        import subprocess
        import sys
        import tempfile
        import studio_tools as tools
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'audio_source.mp4'
            subprocess.run([str(tools.FFMPEG), '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x96:d=2:r=24', '-f', 'lavfi', '-i', 'sine=frequency=440:duration=2', '-c:v', 'libx264', '-c:a', 'aac', str(source)], check=True)
            config = enhance.settings(dict(enhance_mode='resize', target_height=720), tools.probe(source))
            config.update(source=str(source), output=str(root / 'output.mp4'))
            spec = root / 'spec.json'
            spec.write_text(json.dumps(config), encoding='utf-8')
            subprocess.run([sys.executable, str(Path(enhance.__file__).with_name('enhance_worker.py')), str(spec)], check=True, capture_output=True, timeout=60)
            result = tools.probe(root / 'output.mp4')
            self.assertEqual(result['height'], 720)
            self.assertEqual(result['frame_rate'], '24/1')
            self.assertTrue(result['has_audio'])
            self.assertAlmostEqual(result['duration'], 1, delta=0.06)
            self.assertTrue(source.exists())

    def test_existing_external_queue_never_interrupted(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"queue_running":[[1,"external"]],"queue_pending":[]}'
        with patch.object(enhance.hub, 'engine_ready', return_value=True), patch.object(enhance.urllib.request, 'urlopen', return_value=Response()) as calls:
            with self.assertRaises(ValueError):
                enhance.release_idle_comfy()
            self.assertEqual(calls.call_count, 1)
            self.assertTrue(str(calls.call_args.args[0]).endswith('/queue'))


if __name__ == '__main__':
    unittest.main()
