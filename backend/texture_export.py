"""Batch conversion using the ImageToPAA CLI bundled with DayZ Tools."""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from locale_studio import tr
from pipeline import detect_installs
from export_folders import output_folder

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.tga'}


def image_to_paa_path(settings):
    tools = detect_installs(settings).get('tools')
    converter = Path(tools) / 'Bin/ImageToPAA/ImageToPAA.exe' if tools else None
    if not converter or not converter.is_file():
        raise FileNotFoundError(tr('ImageToPAA не знайдено в DayZ Tools.', 'ImageToPAA was not found in DayZ Tools.'))
    return converter


def convert_textures(paths, settings, progress, output=None):
    if not isinstance(paths, list) or not 1 <= len(paths) <= 100:
        raise ValueError(tr('Вибери від 1 до 100 файлів.', 'Choose 1 to 100 files.'))
    converter = image_to_paa_path(settings)
    root = output_folder('textures', output)
    folder = Path(tempfile.mkdtemp(prefix='export-', dir=root))
    files, errors = [], []
    for index, value in enumerate(paths, 1):
        selected = Path(value)
        progress(index, selected.name)
        try:
            source = selected.resolve(strict=True)
            extension = source.suffix.lower()
            if not source.is_file() or extension not in IMAGE_EXTENSIONS | {'.paa'}:
                raise ValueError(tr('Підтримуються PNG, JPG, TGA та PAA.', 'Supported formats are PNG, JPG, TGA and PAA.'))
            target_extension = '.png' if extension == '.paa' else '.paa'
            stem = re.sub(r'[^a-zA-Z0-9_-]+', '_', source.stem).strip('_')[:80] or 'texture'
            with tempfile.TemporaryDirectory(prefix='dayz-texture-') as temp:
                stage = Path(temp)
                local = stage / (stem + ('.jpg' if extension == '.jpeg' else extension))
                output = stage / (stem + target_extension)
                shutil.copyfile(source, local)
                result = subprocess.run(
                    [str(converter), local.name, output.name], cwd=stage, capture_output=True,
                    encoding='utf-8', errors='replace', timeout=60, creationflags=subprocess.CREATE_NO_WINDOW,
                )
                if result.returncode or not output.is_file():
                    detail = (result.stderr + '\n' + result.stdout).strip()
                    raise ValueError(detail or tr('Конвертація не вдалася.', 'Conversion failed.'))
                with output.open('rb') as stream:
                    header = stream.read(8)
                if (target_extension == '.png' and header != b'\x89PNG\r\n\x1a\n') or (
                    target_extension == '.paa' and not (header[:2] in (b'\x44\x44', b'\x55\x15', b'\x44\x04', b'\x88\x88')
                    or header[1:2] == b'\xff' and header[0] in range(1, 6))
                ):
                    raise ValueError(tr('Конвертер повернув некоректний формат.', 'The converter returned an invalid format.'))
                destination = folder / output.name
                suffix = 2
                while destination.exists():
                    destination = folder / f'{stem}_{suffix:02d}{target_extension}'
                    suffix += 1
                shutil.copyfile(output, destination)
                files.append({'source': selected.name, 'output': destination.name})
        except (OSError, ValueError, subprocess.SubprocessError) as error:
            errors.append({'source': selected.name, 'error': str(error)})
    if not files:
        folder.rmdir()
    return {'folder': str(folder if files else root), 'files': files, 'errors': errors}
