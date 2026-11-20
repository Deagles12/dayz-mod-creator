from base64 import b64decode
from pathlib import Path
import struct
import tempfile
import unittest

from locale_studio import set_language
from p3d_preview import preview_p3d


def lod(resolution, corners):
    points = [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)]
    normal_count = int(bool(corners))
    header = struct.pack('<4s6I', b'P3DM', 28, 256, len(points), normal_count, normal_count, 0)
    positions = b''.join(struct.pack('<3fI', *point, 0) for point in points)
    face = b''
    if corners:
        face = (struct.pack('<3fI', 0, 0, 1, len(corners)) +
                b''.join(struct.pack('<IIff', vertex, 0, 0, 0) for vertex in corners) +
                bytes((4 - len(corners)) * 16 + 4) + b'data\\test.paa\0test.rvmat\0')
    tags = (b'TAGG\x01selection\0' + struct.pack('<I', 5) + bytes(5) +
            b'\x01#EndOfFile#\0' + struct.pack('<If', 0, resolution))
    return header + positions + face + tags


class P3dPreview(unittest.TestCase):
    def test_reads_triangles_quads_and_points_across_lods(self):
        model = (struct.pack('<4sII', b'MLOD', 257, 3) + lod(1, (0, 1, 2)) +
                 lod(2, (0, 1, 2, 3)) + lod(1e15, ()))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'MODEL.P3D'
            path.write_bytes(model)
            first, second, memory = preview_p3d(path)
        self.assertEqual([first['resolution'], second['resolution']], [1, 2])
        self.assertEqual([first['triangles'], second['triangles'], memory['triangles']], [1, 2, 0])
        self.assertEqual(struct.unpack('<3I', b64decode(first['indices'])), (0, 2, 1))
        self.assertEqual(struct.unpack('<6I', b64decode(second['indices'])), (0, 2, 1, 0, 3, 2))
        self.assertEqual(len(b64decode(memory['positions'])), 48)

    def test_rejects_truncation_bad_indices_and_odol(self):
        header = struct.pack('<4sII', b'MLOD', 257, 1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.p3d'
            set_language('en')
            self.addCleanup(set_language, 'uk')
            for data, reason in [
                ((header + lod(1, (0, 1, 2)))[:-1], 'incomplete'),
                (header + lod(1, (0, 1, 4)), 'invalid'),
                (b'ODOL', 'binarized'),
            ]:
                with self.subTest(reason=reason):
                    path.write_bytes(data)
                    with self.assertRaisesRegex(ValueError, reason):
                        preview_p3d(path)
