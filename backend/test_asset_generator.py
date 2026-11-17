"""Run with DAYZ_BLENDER set to include real Blender acceptance tests."""
import json
import os
from pathlib import Path
import struct
import tempfile
import time
import unittest
from unittest.mock import patch

import asset_generator as generator


def request(root, **changes):
    return dict(name='MV_Catalyst', template='bottle', width=48, height=110, depth=48,
                capWidth=24, capHeight=14, material='amber', bodyColor='#8a4319',
                capColor='#171717', resolution=512, references=[], output=str(root), **changes)


def wait(identifier):
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        job = generator.snapshot(identifier)
        if job['state'] != 'running':
            return job
        time.sleep(.1)
    generator.cancel(identifier)
    raise AssertionError('Generator timeout')


class Parameters(unittest.TestCase):
    def test_missing_blender(self):
        with self.assertRaises(ValueError):
            generator.executable('Z:/missing/blender.exe')

    def test_invalid_sizes_and_names(self):
        for changes in ({'width': 0}, {'height': float('nan')}, {'depth': -4},
                        {'capWidth': 50}, {'name': '../item'}, {'name': 'CON'},
                        {'resolution': 8192}, {'template': 'box'}):
            values = request(Path('.'))
            values.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                generator.parameters(values)

    def test_photo_requires_template_confirmation(self):
        with self.assertRaises(ValueError):
            generator.parameters(dict(request(Path('.')), references=['photo.png']))


@unittest.skipUnless(os.environ.get('DAYZ_BLENDER'), 'Set DAYZ_BLENDER for real Blender tests')
class BlenderAcceptance(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        cls.bottle = wait(generator.start(request(cls.root))['id'])
        if cls.bottle['state'] != 'done':
            raise AssertionError(cls.bottle['error'])
        values = request(cls.root)
        values.update(name='Chemical_Canister', template='canister', width=180, height=270,
                      depth=100, capWidth=40, capHeight=24, material='plastic', bodyColor='#547b46')
        cls.canister = wait(generator.start(values)['id'])
        if cls.canister['state'] != 'done':
            raise AssertionError(cls.canister['error'])

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_amber_bottle_black_cap_files(self):
        folder = self.root / 'MV_Catalyst'
        for name in ('MV_Catalyst.blend', 'MV_Catalyst.glb', 'MV_Catalyst.obj',
                     'MV_Catalyst.mtl', 'textures/MV_Catalyst_co.png', 'preview.png', 'validation.json'):
            self.assertGreater((folder / name).stat().st_size, 0)
        self.assertIn('map_Kd textures/MV_Catalyst_co.png', (folder / 'MV_Catalyst.mtl').read_text())
        self.assertIn('\nf ', (folder / 'MV_Catalyst.obj').read_text())

    def test_canister_handle_has_through_hole(self):
        self.assertTrue(self.canister['result']['validation']['handleThroughHole'])
        self.assertEqual(self.canister['result']['validation']['mesh']['nonManifoldEdges'], 0)

    def test_uv_texture_and_embedded_glb(self):
        for job in (self.bottle, self.canister):
            report = job['result']['validation']
            self.assertEqual(report['uv']['overlappingTriangles'], 0)
            self.assertTrue(report['glb']['embeddedPNG'])
            self.assertEqual(report['textureResolution'], [512, 512])
            self.assertTrue(report['reimport']['imageTexture'])

    def test_glb_import_and_blend_reopen(self):
        for job in (self.bottle, self.canister):
            report = job['result']['validation']
            self.assertTrue(report['blendReopened'])
            self.assertGreater(report['reimport']['polygons'], 0)
            self.assertEqual(report['mesh']['dimensionsMM'], report['reimport']['dimensionsMM'])

    def test_regeneration_requires_confirmation_and_replaces_same_folder(self):
        values = request(self.root)
        with self.assertRaises(FileExistsError):
            generator.start(values)
        values.update(width=60, height=140, depth=60, overwrite=True)
        job = wait(generator.start(values)['id'])
        self.assertEqual(job['state'], 'done', job['error'])
        self.assertEqual(job['result']['validation']['mesh']['dimensionsMM'], [60, 140, 60])
        self.assertEqual(sorted(path.name for path in self.root.iterdir()), ['Chemical_Canister', 'MV_Catalyst'])

    def test_cancel_terminates_blender_and_preserves_prior_result(self):
        values = request(self.root)
        values.update(overwrite=True, resolution=2048)
        before = (self.root / 'MV_Catalyst/MV_Catalyst.glb').read_bytes()
        identifier = generator.start(values)['id']
        deadline = time.monotonic() + 10
        while generator.jobs[identifier]['process'] is None and time.monotonic() < deadline:
            time.sleep(.02)
        process = generator.jobs[identifier]['process']
        self.assertIsNotNone(process)
        generator.cancel(identifier)
        self.assertEqual(wait(identifier)['state'], 'cancelled')
        self.assertIsNotNone(process.poll())
        self.assertEqual((self.root / 'MV_Catalyst/MV_Catalyst.glb').read_bytes(), before)

    def test_export_failure_preserves_existing_result(self):
        values = request(self.root)
        values.update(overwrite=True)
        before = (self.root / 'MV_Catalyst/MV_Catalyst.glb').read_bytes()
        with patch('asset_generator.read_glb', side_effect=ValueError('Injected invalid GLB export')):
            job = wait(generator.start(values)['id'])
        self.assertEqual(job['state'], 'error')
        self.assertIn('Injected invalid GLB export', job['error'])
        self.assertEqual((self.root / 'MV_Catalyst/MV_Catalyst.glb').read_bytes(), before)
