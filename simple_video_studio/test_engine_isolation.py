"""Launcher contract: new overlays/nodes must not leak into stable profiles."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import studio_hub as hub


class EngineIsolation(unittest.TestCase):
    def launch(self, engine_id):
        with tempfile.TemporaryDirectory() as tmp:
            app = Path(tmp)
            root = app / 'engine'
            root.mkdir()
            (root/'py_overlay').mkdir()
            info = dict(hub.ENGINES[engine_id], id=engine_id, root=str(root), installed=True,
                        configured=True,python=str(app/'engine-python.exe'),base_directory=str(root))
            process = Mock(pid=424242)
            with patch.object(hub, 'APP', app), patch.object(hub.config,'LOGS',app/'logs'), patch.object(hub, 'engine_ready', return_value=False), \
                 patch.object(hub, 'engine_info', return_value=info), \
                 patch.object(hub, 'prepare_comfy_preferences'), \
                 patch.object(Path, 'is_file', return_value=True), \
                 patch.object(hub.subprocess, 'Popen', return_value=process) as popen:
                self.assertTrue(hub.start_engine(engine_id))
                return popen.call_args, root

    def test_new_comfy_uses_own_nodes_and_overlay(self):
        call, root = self.launch('comfy_latest')
        args = call.args[0]
        self.assertEqual(args[args.index('--base-directory') + 1], str(root))
        self.assertEqual(call.kwargs['env']['PYTHONPATH'], str(root / 'py_overlay'))
        self.assertEqual(args[args.index('--user-directory') + 1], str(root / 'user'))

    def test_stable_comfy_keeps_existing_node_base(self):
        call, root = self.launch('comfy_stable')
        args = call.args[0]
        self.assertEqual(args[args.index('--base-directory') + 1], str(root))
        self.assertNotEqual(call.kwargs['env'].get('PYTHONPATH'), str(root / 'py_overlay'))

    def test_new_wangp_overlay_is_local_to_profile(self):
        call, root = self.launch('wangp_latest')
        self.assertEqual(call.kwargs['env']['PYTHONPATH'], str(root / 'py_overlay'))
        self.assertEqual(call.kwargs['cwd'], root / 'app')

    def test_stable_wangp_does_not_use_new_overlay(self):
        call, root = self.launch('wangp_stable')
        self.assertNotEqual(call.kwargs['env'].get('PYTHONPATH'), str(root / 'py_overlay'))

    def test_preferences_are_copied_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'new'
            source = Path(tmp) / 'old.json'
            source.write_text('{"video_crf":16}', encoding='utf-8')
            hub.prepare_comfy_preferences(root, source)
            target = root / 'user/minimax_creator.settings.json'
            self.assertEqual(target.read_text(encoding='utf-8'), source.read_text(encoding='utf-8'))
            target.write_text('{"video_crf":18}', encoding='utf-8')
            hub.prepare_comfy_preferences(root, source)
            self.assertEqual(target.read_text(encoding='utf-8'), '{"video_crf":18}')

    def test_stop_does_not_kill_same_port_process_in_other_directory(self):
        import psutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); logs=root/'logs';logs.mkdir()
            (logs/'comfy_stable.pid').write_text('424242')
            process=Mock()
            process.cmdline.return_value=['python','main.py','--port','8188']
            process.cwd.return_value=str(root/'unrelated')
            info=dict(hub.ENGINES['comfy_stable'],root=str(root/'expected'),port=8188)
            with patch.object(hub.config,'LOGS',logs), patch.object(hub,'engine_info',return_value=info), \
                 patch.object(hub,'engine_ready',return_value=False), patch.object(psutil,'Process',return_value=process):
                with self.assertRaisesRegex(ValueError,'进程已变化'):
                    hub.stop_idle_engine('comfy_stable')
            process.terminate.assert_not_called()
            process.children.assert_not_called()

    def test_absent_preferences_source_is_not_invented(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'new'
            hub.prepare_comfy_preferences(root, Path(tmp) / 'missing.json')
            self.assertFalse((root / 'user/minimax_creator.settings.json').exists())


if __name__ == '__main__':
    unittest.main()
