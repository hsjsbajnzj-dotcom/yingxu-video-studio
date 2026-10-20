import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import studio
import studio_hub as hub
from studio_images import image_assets


class ImageAssets(unittest.TestCase):
    def request(self, **extra):
        return dict(provider='local_h3', mode='image', prompt='安静望湖', duration=5,
                    realism=False, input_asset='first.png', **extra)

    def test_legacy_first_frame_is_unchanged(self):
        creator, _ = studio.build_h3_creator_data(self.request(), 'test')
        self.assertEqual(creator['segments'][0]['checkpoint'], 'fl2va')
        self.assertEqual(creator['segments'][0]['assets'][0]['role'], 'first_frame')

    def test_first_and_last(self):
        creator, _ = studio.build_h3_creator_data(self.request(end_asset='end.png'), 'test')
        self.assertEqual([a['role'] for a in creator['segments'][0]['assets']], ['first_frame','last_frame'])
        self.assertEqual(creator['segments'][0]['checkpoint'], 'fl2va')

    def test_motion_reference_is_explicit_and_uses_ref_checkpoint(self):
        data=self.request(reference_assets=[{'input_asset':'previs.mp4','kind':'video','takes':'motion'}])
        creator,_=studio.build_h3_creator_data(data,'test')
        segment=creator['segments'][0]
        self.assertEqual(segment['checkpoint'],'ref2va')
        self.assertEqual(segment['assets'][1]['kind'],'video')
        self.assertEqual(segment['assets'][1]['track'],'picture')
        self.assertIn('实验性',segment['prompt'])

    def test_multiple_motion_references_rejected(self):
        with self.assertRaises(ValueError):
            image_assets(self.request(reference_assets=[{'input_asset':'previs.mp4','kind':'video','takes':'motion'}]*2))

    def test_motion_extension_and_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'first.png').touch()
            for name in ['../outside.mp4','model.blend']:
                with self.assertRaises(ValueError):
                    image_assets(self.request(reference_assets=[{'input_asset':name,'kind':'video','takes':'motion'}]),root)

    def test_refs_switch_checkpoint_and_keep_roles(self):
        refs = [{'input_asset':'face.png','takes':'person'}, {'input_asset':'room.png','takes':'scene'}]
        creator, _ = studio.build_h3_creator_data(self.request(end_asset='end.png',reference_assets=refs), 'test')
        segment = creator['segments'][0]
        self.assertEqual(segment['checkpoint'], 'ref2va')
        self.assertEqual([a['takes'] for a in segment['assets']], ['full','full','person','scene'])
        self.assertEqual(len({a['handle'] for a in segment['assets']}), 4)

    def test_reference_only_does_not_invent_first_frame(self):
        data = self.request(reference_assets=[{'input_asset':'room.png'}])
        data['input_asset']=''
        creator, _ = studio.build_h3_creator_data(data, 'test')
        self.assertNotIn('从上传的首帧准确开始', creator['segments'][0]['prompt'])
        self.assertEqual(creator['segments'][0]['assets'][0]['role'], 'reference')

    def test_reject_excess_refs_and_invalid_purpose(self):
        with self.assertRaises(ValueError):
            image_assets(self.request(reference_assets=[{'input_asset':'a.png'}]*7))
        with self.assertRaises(ValueError):
            image_assets(self.request(reference_assets=[{'input_asset':'a.png','takes':'bad'}]))

    def test_unsupported_model_does_not_ignore_images(self):
        data=self.request(end_asset='end.png')
        for provider in ['local_wan5b','seedance_fast']:
            data['provider']=provider
            with self.assertRaisesRegex(ValueError,'本地H3'):
                image_assets(data)

    def test_text_mode_does_not_ignore_extras(self):
        data=self.request(end_asset='end.png');data['mode']='text'
        with self.assertRaises(ValueError):image_assets(data)

    def test_validate_every_file_and_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'first.png').touch()
            with self.assertRaisesRegex(ValueError,'不存在'):
                image_assets(self.request(end_asset='missing.png'),root)
            with self.assertRaisesRegex(ValueError,'目录'):
                image_assets(self.request(end_asset='../escape.png'),root)
            image_assets(self.request(),root)

    def test_project_persists_extra_images(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(hub,'PROJECTS',Path(tmp)):
            shot=self.request(end_asset='end.png',reference_assets=[{'input_asset':'face.png','takes':'person'}])
            saved=hub.save_project({'id':'multi_image_test','shots':[shot]})
            loaded=hub.load_project(saved['id'])['shots'][0]
            self.assertEqual(loaded['end_asset'],shot['end_asset'])
            self.assertEqual(loaded['reference_assets'],shot['reference_assets'])


if __name__=='__main__':unittest.main()
