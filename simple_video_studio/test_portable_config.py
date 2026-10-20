import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import studio_config as config
import studio_doctor
import studio_hub as hub


class PortableConfig(unittest.TestCase):
    def test_relative_paths_resolve_against_config_not_cwd(self):
        with tempfile.TemporaryDirectory(prefix='路径 空格-') as tmp:
            path=config.resolve('my models/input',Path(tmp))
            self.assertEqual(path,Path(tmp).resolve()/'my models/input')

    def test_empty_path_rejected(self):
        with self.assertRaises(ValueError):config.resolve('')

    def test_default_engines_unconfigured_and_do_not_probe(self):
        with patch.object(config,'SETTINGS',{}):
            engines=config.engines()
            self.assertTrue(all(not e['configured'] for e in engines.values()))
            with patch.object(hub,'engine_info',return_value=dict(engines['comfy_stable'],installed=False)), \
                 patch.object(hub.urllib.request,'urlopen',side_effect=AssertionError('must not probe')):
                self.assertFalse(hub.engine_ready('comfy_stable'))
                with self.assertRaisesRegex(ValueError,'config.local.json'):hub.start_engine('comfy_stable')

    def test_invalid_json_and_port_fail_readably(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'bad.json';path.write_text('{broken',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'JSON'):config.load_config(path)
        with patch.object(config,'SETTINGS',{'engines':{'comfy_stable':{'port':True}}}):
            with self.assertRaises(ValueError):config.engines()

    def test_optional_features_default_off(self):
        with patch.object(config,'SETTINGS',{}):
            self.assertFalse(config.feature('flashvsr'))
        with patch.object(config,'SETTINGS',{'features':{'flashvsr':'yes'}}):
            with self.assertRaises(ValueError):config.feature('flashvsr')

    def test_missing_media_tools_are_reported_without_download(self):
        with patch.object(studio_doctor.subprocess,'run',side_effect=FileNotFoundError):
            self.assertFalse(studio_doctor.tool('ffmpeg')['ready'])

    def test_non_loopback_cli_is_rejected(self):
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('studio.py')),
                               '--host','0.0.0.0','--no-browser'],capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0)

    def test_invalid_web_port_rejected_before_start(self):
        result=subprocess.run([sys.executable,str(Path(__file__).with_name('studio.py')),
                               '--port','65536','--no-browser'],capture_output=True,timeout=10)
        self.assertNotEqual(result.returncode,0)


if __name__=='__main__':unittest.main()
