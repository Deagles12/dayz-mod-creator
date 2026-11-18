import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from archive_workspace import ensure_workspace
from export_folders import default_folder


class ArchiveWorkspace(unittest.TestCase):
    def test_creates_named_portable_directory_and_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            install = Path(directory)
            root = ensure_workspace(install)
            self.assertEqual(root, install / '3D-Generator')
            for name in ('incoming', 'ready', 'materials/Weathered Wood'):
                self.assertTrue((root / name).is_dir())
            for name in ('Process_DayZ_Archives.ps1', 'DayZ_Archive_Finisher_Blender.py', 'validation.py'):
                self.assertGreater((root / name).stat().st_size, 0)
            with patch('export_folders.install_directory', return_value=install):
                self.assertEqual(default_folder('textures'), install / 'output/textures')

    def test_preserves_user_edits_and_existing_archives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = ensure_workspace(Path(directory))
            entry = root / 'DayZ_Archive_Finisher_Blender.py'
            entry.write_text('# user-edited script', encoding='utf-8')
            archive = root / 'incoming/user.zip'
            archive.write_bytes(b'archive fixture')
            ensure_workspace(Path(directory))
            self.assertEqual(entry.read_text(encoding='utf-8'), '# user-edited script')
            self.assertEqual(archive.read_bytes(), b'archive fixture')
