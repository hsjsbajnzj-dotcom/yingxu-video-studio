import tempfile
import unittest
from pathlib import Path
import studio
import studio_tools as tools
import studio_audio


class SoundControls(unittest.TestCase):
    def test_prompt_routing(self):
        data = dict(prompt="人物听见声音后回头", ambience="night_street", performance="listen", generate_audio=True)
        creator, _ = studio.build_h3_creator_data(data, "test")
        self.assertIn("夜间", creator["segments"][0]["soundscape"])
        self.assertIn("眼球先", creator["segments"][0]["prompt"])
        creator, _ = studio.build_h3_creator_data(dict(data, soundscape="自定义优先"), "test")
        self.assertEqual(creator["segments"][0]["soundscape"], "自定义优先")
        creator, _ = studio.build_h3_creator_data(dict(data, generate_audio=False, music=True), "test")
        self.assertEqual(creator["segments"][0]["soundscape"], "N/A")
        self.assertEqual(creator["segments"][0]["music"], "N/A")
        with self.assertRaises(ValueError):
            studio.build_h3_creator_data(dict(data, performance="invalid"), "test")

    def test_real_silent_and_mixing(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.mp4"
            audio = root / "amb.wav"
            subprocess.run([str(tools.FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=160x96:d=2:r=24", "-f", "lavfi", "-i", "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac", str(source)], check=True)
            output = tools.silent_outputs([dict(kind="video", relative_path=source.name)], root)[0]
            silent = root / output["relative_path"]
            self.assertFalse(tools.probe(silent)["has_audio"])
            self.assertTrue(source.is_file())
            subprocess.run([str(tools.FFMPEG), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=1", str(audio)], check=True)
            for keep in (True, False):
                target = root / (str(keep) + ".mp4")
                studio_audio.mix(source, target, audio, 2, gain_db=-12, offset=0.2, keep_original=keep)
                info = tools.probe(target)
                self.assertTrue(info["has_audio"])
                self.assertAlmostEqual(info["duration"], 2, delta=0.1)
            with self.assertRaises(ValueError):
                studio_audio.mix(source, root / "bad.mp4", audio, 2, gain_db=float("nan"))


if __name__ == "__main__":
    unittest.main()
