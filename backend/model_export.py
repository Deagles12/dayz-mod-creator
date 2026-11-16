"""Local export of a textured GLB into a visual DayZ model."""
import base64
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile

from locale_studio import tr
from pipeline import STORE, detect_installs, lines, steam_installs


def read_glb(value):
    path = Path(value).resolve(strict=True)
    if not path.is_file() or path.suffix.lower() != '.glb' or path.stat().st_size > 64 * 1024**2:
        raise ValueError(tr('Вибери GLB розміром до 64 МБ.', 'Choose a GLB of up to 64 MB.'))
    data = path.read_bytes()
    if len(data) < 20:
        raise ValueError('Incomplete GLB')
    magic, version, size, json_size, chunk = struct.unpack_from('<4sIII4s', data)
    if (magic, version, size, chunk) != (b'glTF', 2, len(data), b'JSON') or json_size > size - 20:
        raise ValueError('Invalid GLB header')
    model = json.loads(data[20:20 + json_size])
    if any('uri' in entry for key in ('buffers', 'images') for entry in model.get(key, [])):
        raise ValueError(tr('GLB має містити текстуру всередині файла.', 'The GLB must embed its texture.'))
    return path, data


def blender_path():
    candidates = [
        os.environ.get('DAYZ_BLENDER'),
        shutil.which('blender'),
        *(str(root / 'Blender/blender.exe') for root in steam_installs()),
        *(str(path) for path in sorted(Path(os.environ.get('ProgramFiles', 'C:/Program Files'))
          .glob('Blender Foundation/Blender */blender.exe'), reverse=True)),
        *(str(path) for path in sorted((Path.home() / 'Documents/Codex')
          .glob('*/*/outputs/DayZPipeline/tools/blender-*/blender.exe'), reverse=True)),
    ]
    for value in candidates:
        if value and Path(value).is_file():
            return Path(value)
    raise FileNotFoundError(tr('Blender не знайдено. Встанови Blender або задай DAYZ_BLENDER.',
                              'Blender was not found. Install Blender or set DAYZ_BLENDER.'))


def export_model(request):
    source, _ = read_glb(request['path'])
    settings = request.get('settings', {})
    tools = detect_installs(settings).get('tools')
    converter = Path(tools) / 'Bin/ImageToPAA/ImageToPAA.exe' if tools else None
    if not converter or not converter.is_file():
        raise FileNotFoundError(tr('ImageToPAA не знайдено в DayZ Tools.', 'ImageToPAA was not found in DayZ Tools.'))
    blender = blender_path()
    prefix = 'dayz_models'
    addons = lines(str(settings.get('addons', '')))
    if request.get('root') and len(addons) == 1:
        root = Path(request['root']).resolve()
        addon = (root / addons[0]).resolve()
        if addon.is_relative_to(root) and (addon / 'config.cpp').is_file():
            marker = addon / '$PBOPREFIX$'
            declared = marker.read_text(encoding='utf-8-sig').strip() if marker.is_file() else ''
            configured = str(settings.get('prefix', '')).strip()
            if configured and declared and configured != declared:
                raise ValueError(tr('Префікс у налаштуваннях не збігається з $PBOPREFIX$.',
                                    'The configured prefix differs from $PBOPREFIX$.'))
            prefix = configured or declared or str(settings.get('addon_name', '')).strip() or addon.name
    prefix = prefix.replace('/', '\\')
    if not re.fullmatch(r'[A-Za-z0-9_-]+(?:\\[A-Za-z0-9_-]+)*', prefix):
        raise ValueError(tr('Аддон має непідтримуваний префікс.', 'The addon prefix is unsupported.'))

    stem = re.sub(r'[^a-z0-9_]+', '_', source.stem.lower()).strip('_')[:60] or 'model'
    root = STORE / 'models' / Path(*prefix.split('\\'))
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='dayz-model-') as temp:
        stage = Path(temp)
        scratch = stage / 'out'
        scratch.mkdir()
        for index in range(1, 10000):
            name = stem if index == 1 else f'{stem}_{index:02d}'
            destination = root / name
            if not destination.exists():
                break
        else:
            raise FileExistsError(stem)
        result = subprocess.run(
            [str(blender), '-b', '-t', '4', '--python-exit-code', '1', '--python',
             str(Path(__file__).with_name('model_blender.py')), '--', str(source), str(scratch),
             str(converter), prefix, name], cwd=stage, capture_output=True,
            encoding='utf-8', errors='replace', timeout=180, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise RuntimeError((result.stderr or result.stdout).strip()[-1800:])
        model = scratch / f'{name}.p3d'
        texture = scratch / 'data' / f'{name}_co.paa'
        with model.open('rb') as file:
            valid = file.read(4) == b'MLOD'
        if not valid or not texture.is_file():
            raise RuntimeError('Missing P3D or PAA output')
        shutil.copytree(scratch, destination)
    return {'folder': str(destination), 'model': model.name, 'texture': texture.name, 'prefix': prefix}
